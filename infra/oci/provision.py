"""Provisionamento idempotente da fase F0 (tarefas 1, 2, 5, 6, 7, 8) e do ambiente de execução.

Ambiente de execução: a máquina local é só IDE e repositório. Os scripts rodam na VM
dmb-vm (sub-rede de desenvolvimento, SSH só do IP autorizado) e em notebooks e jobs do
OCI Data Science. A sub-rede privada dmb-subnet-jobs continua sem saída para a internet.

Uso: PYTHONPATH=infra/oci .venv/bin/python infra/oci/provision.py
Registra os artefatos criados em .secrets/artefatos-OCI.md.
"""
import os
import time
from datetime import datetime, timezone

import oci

from session import CRED_DIR, REGION, load_config, settings

# Caminho do compartimento pai e CIDR do SSH ficam fora do Git: .secrets/oci-settings.json
PARENT_PATH = settings()["parent_compartment_path"]
COMPARTMENT_NAME = "decision-models"
TAGS = {"projeto": "benchmark-decisoes-ptbr", "ambiente": "benchmark"}  # centro_custo pendente (Q13)
BUCKETS = ["entrada", "artefatos", "resultados", "logs-imutaveis"]
VCN_CIDR = "10.20.0.0/16"
SUBNET_CIDR = "10.20.1.0/24"
DEV_SUBNET_CIDR = "10.20.2.0/24"
SSH_ALLOWED_CIDR = settings()["ssh_allowed_cidr"]
# VM de trabalho criada pelo usuário no console (o lançamento via API é negado neste compartment).
VM_NAME = "instance-20261007-1206"
VM_SSH_KEY = ".secrets/ssh/ssh-key-oci.key"
VM_USER = "opc"
NOTEBOOK_NAME = "dmb-notebook-cpu"
NOTEBOOK_SHAPE = ("VM.Standard.E4.Flex", 4, 32)
ARTIFACTS_FILE = CRED_DIR.parent / "artefatos-OCI.md"
# Região secundária só para jobs de GPU (A10 sem capacidade em us-chicago-1).
GPU_REGION = "sa-saopaulo-1"
GPU_SUFFIX = "-gru"
GPU_BUCKETS = ["artefatos", "resultados"]

artifacts = []


def record(kind, name, ocid, region):
    artifacts.append((kind, name, ocid, region))


def find_compartment(idn, tenancy):
    allc = oci.pagination.list_call_get_all_results(
        idn.list_compartments, tenancy, compartment_id_in_subtree=True,
        access_level="ACCESSIBLE", lifecycle_state="ACTIVE").data
    byid = {c.id: c for c in allc}

    def path(c):
        parts = []
        while c:
            parts.append(c.name)
            c = byid.get(c.compartment_id)
        return "root/" + "/".join(reversed(parts))

    parent = next(c for c in allc if path(c) == PARENT_PATH)
    comp = next((c for c in allc if c.compartment_id == parent.id and c.name == COMPARTMENT_NAME), None)
    if comp is None:
        comp = idn.create_compartment(oci.identity.models.CreateCompartmentDetails(
            compartment_id=parent.id, name=COMPARTMENT_NAME, freeform_tags=TAGS,
            description="Benchmark de modelos de decisão PT-BR para roteamento em orquestrador multiagente")).data
        for _ in range(30):
            try:
                if idn.get_compartment(comp.id).data.lifecycle_state == "ACTIVE":
                    break
            except oci.exceptions.ServiceError as e:
                if e.status != 404:
                    raise
            time.sleep(10)
    record("Compartment", f"{PARENT_PATH}/{COMPARTMENT_NAME}", comp.id, "global (home us-ashburn-1)")
    return comp.id


def ensure_ds_project(cfg, cid):
    ds = oci.data_science.DataScienceClient(cfg)
    name = "benchmark-decisoes-ptbr"
    proj = next((p for p in ds.list_projects(cid, lifecycle_state="ACTIVE").data if p.display_name == name), None)
    if proj is None:
        proj = ds.create_project(oci.data_science.models.CreateProjectDetails(
            compartment_id=cid, display_name=name, freeform_tags=TAGS,
            description="Benchmark de modelos de decisão PT-BR")).data
    record("Data Science Project", name, proj.id, cfg["region"])
    return proj.id


def ensure_buckets(cfg, cid, suffix="", buckets=BUCKETS):
    os_ = oci.object_storage.ObjectStorageClient(cfg)
    ns = os_.get_namespace().data
    existing = {b.name for b in oci.pagination.list_call_get_all_results(os_.list_buckets, ns, cid).data}
    for short in buckets:
        name = f"dmb-{short}{suffix}"
        if name not in existing:
            os_.create_bucket(ns, oci.object_storage.models.CreateBucketDetails(
                name=name, compartment_id=cid, public_access_type="NoPublicAccess",
                storage_tier="Standard", versioning="Enabled", freeform_tags=TAGS))
        b = os_.get_bucket(ns, name).data
        record("Object Storage Bucket", f"{name} (namespace {ns})", b.id, cfg["region"])


def ensure_network(cfg, cid):
    vn = oci.core.VirtualNetworkClient(cfg)
    comp = oci.wait_until  # alias curto

    vcn = next((v for v in vn.list_vcns(cid, display_name="dmb-vcn").data
                if v.lifecycle_state == "AVAILABLE"), None)
    if vcn is None:
        vcn = vn.create_vcn(oci.core.models.CreateVcnDetails(
            compartment_id=cid, display_name="dmb-vcn", cidr_blocks=[VCN_CIDR],
            dns_label="dmbvcn", freeform_tags=TAGS)).data
        vcn = comp(vn, vn.get_vcn(vcn.id), "lifecycle_state", "AVAILABLE").data
    record("VCN", f"dmb-vcn ({VCN_CIDR})", vcn.id, cfg["region"])

    svc = next(s for s in vn.list_services().data if s.cidr_block.startswith("all-") and "services-in-oracle-services-network" in s.cidr_block)
    sgw = next((g for g in vn.list_service_gateways(cid, vcn_id=vcn.id).data
                if g.lifecycle_state == "AVAILABLE"), None)
    if sgw is None:
        sgw = vn.create_service_gateway(oci.core.models.CreateServiceGatewayDetails(
            compartment_id=cid, vcn_id=vcn.id, display_name="dmb-sgw", freeform_tags=TAGS,
            services=[oci.core.models.ServiceIdRequestDetails(service_id=svc.id)])).data
        sgw = comp(vn, vn.get_service_gateway(sgw.id), "lifecycle_state", "AVAILABLE").data
    record("Service Gateway", f"dmb-sgw ({svc.cidr_block})", sgw.id, cfg["region"])

    rt = next((r for r in vn.list_route_tables(cid, vcn_id=vcn.id, display_name="dmb-rt-privada").data
               if r.lifecycle_state == "AVAILABLE"), None)
    if rt is None:
        rt = vn.create_route_table(oci.core.models.CreateRouteTableDetails(
            compartment_id=cid, vcn_id=vcn.id, display_name="dmb-rt-privada", freeform_tags=TAGS,
            route_rules=[oci.core.models.RouteRule(
                destination=svc.cidr_block, destination_type="SERVICE_CIDR_BLOCK",
                network_entity_id=sgw.id, description="Object Storage e serviços OCI via Service Gateway")])).data
        rt = comp(vn, vn.get_route_table(rt.id), "lifecycle_state", "AVAILABLE").data
    record("Route Table", "dmb-rt-privada (somente Service Gateway)", rt.id, cfg["region"])

    sl = next((s for s in vn.list_security_lists(cid, vcn_id=vcn.id, display_name="dmb-sl-privada").data
               if s.lifecycle_state == "AVAILABLE"), None)
    if sl is None:
        sl = vn.create_security_list(oci.core.models.CreateSecurityListDetails(
            compartment_id=cid, vcn_id=vcn.id, display_name="dmb-sl-privada", freeform_tags=TAGS,
            egress_security_rules=[
                oci.core.models.EgressSecurityRule(
                    destination=svc.cidr_block, destination_type="SERVICE_CIDR_BLOCK", protocol="6",
                    tcp_options=oci.core.models.TcpOptions(destination_port_range=oci.core.models.PortRange(min=443, max=443)),
                    description="HTTPS para serviços OCI"),
                oci.core.models.EgressSecurityRule(destination=VCN_CIDR, protocol="all", description="Tráfego interno da VCN"),
            ],
            ingress_security_rules=[
                oci.core.models.IngressSecurityRule(source=VCN_CIDR, protocol="all", description="Tráfego interno da VCN"),
            ])).data
        sl = comp(vn, vn.get_security_list(sl.id), "lifecycle_state", "AVAILABLE").data
    record("Security List", "dmb-sl-privada (egresso só para serviços OCI e VCN)", sl.id, cfg["region"])

    sub = next((s for s in vn.list_subnets(cid, vcn_id=vcn.id, display_name="dmb-subnet-jobs").data
                if s.lifecycle_state == "AVAILABLE"), None)
    if sub is None:
        sub = vn.create_subnet(oci.core.models.CreateSubnetDetails(
            compartment_id=cid, vcn_id=vcn.id, display_name="dmb-subnet-jobs", cidr_block=SUBNET_CIDR,
            dns_label="jobs", prohibit_public_ip_on_vnic=True, route_table_id=rt.id,
            security_list_ids=[sl.id], freeform_tags=TAGS)).data
        sub = comp(vn, vn.get_subnet(sub.id), "lifecycle_state", "AVAILABLE").data
    record("Subnet (privada)", f"dmb-subnet-jobs ({SUBNET_CIDR})", sub.id, cfg["region"])

    # O NAT é criado só por nat.py; aqui ele só é registrado, se existir.
    for nat in vn.list_nat_gateways(cid, vcn_id=vcn.id).data:
        if nat.lifecycle_state == "AVAILABLE":
            status = "bloqueado" if nat.block_traffic else "ATIVO"
            record("NAT Gateway (temporário)", f"{nat.display_name} ({status})", nat.id, cfg["region"])
    return vcn.id


USER_FAMILIES = [
    "data-science-family",
    "object-family",
    "virtual-network-family",
    "logging-family",
    "repos",
    "generative-ai-family",
    "instance-family",
    "volume-family",
    "instance-agent-command-family",
]


def ensure_policy(idn, cid, name, description, statements):
    pol = next((p for p in idn.list_policies(cid).data if p.name == name), None)
    if pol is None:
        pol = idn.create_policy(oci.identity.models.CreatePolicyDetails(
            compartment_id=cid, name=name, description=description,
            statements=statements, freeform_tags=TAGS)).data
    elif sorted(pol.statements) != sorted(statements):
        pol = idn.update_policy(pol.id, oci.identity.models.UpdatePolicyDetails(
            description=description, statements=statements)).data
    record("IAM Policy", f"{name} ({len(statements)} declarações)", pol.id, "global (home us-ashburn-1)")


def ensure_policies(idn, cid, user_id):
    # Sem acesso de administrador à tenancy: nada de grupos nem dynamic groups.
    # O usuário é identificado pelo OCID e os jobs pelo tipo de principal.
    comp = f"compartment id {cid}"
    user_stmts = [f"Allow any-user to manage {fam} in {comp} where request.user.id = '{user_id}'"
                  for fam in USER_FAMILIES]
    ensure_policy(idn, cid, "dmb-usuario-manager",
                  "Usuário do benchmark como manager das famílias usadas", user_stmts)

    job = f"request.principal.type = 'datasciencejob', request.principal.compartment.id = '{cid}'"
    read_buckets = "any {target.bucket.name = 'dmb-entrada', target.bucket.name = 'dmb-artefatos'}"
    write_buckets = "any {target.bucket.name = 'dmb-resultados', target.bucket.name = 'dmb-logs-imutaveis'}"
    job_stmts = [
        f"Allow any-user to read buckets in {comp} where all {{{job}}}",
        f"Allow any-user to read objects in {comp} where all {{{job}, {read_buckets}}}",
        f"Allow any-user to manage objects in {comp} where all {{{job}, {write_buckets}, "
        "any {request.permission = 'OBJECT_CREATE', request.permission = 'OBJECT_INSPECT', request.permission = 'OBJECT_READ'}}",
        f"Allow any-user to use log-content in {comp} where all {{{job}}}",
        f"Allow any-user to read repos in {comp} where all {{{job}}}",
        f"Allow service datascience to use virtual-network-family in {comp}",
        # copy_object entre regiões (réplica para a região de GPU)
        f"Allow service objectstorage-{REGION} to manage object-family in {comp}",
        f"Allow service objectstorage-{GPU_REGION} to manage object-family in {comp}",
    ]
    ensure_policy(idn, cid, "dmb-jobs-menor-privilegio",
                  "Jobs de benchmark: leitura de entrada/artefatos e escrita de resultados/logs (tarefa 7)",
                  job_stmts)


def ensure_workload_policy(idn, cid):
    """VM (instance principal) e notebooks do Data Science (resource principal), sem dynamic groups."""
    comp = f"compartment id {cid}"
    who = (f"all {{request.principal.compartment.id = '{cid}', "
           "any {request.principal.type = 'instance', request.principal.type = 'datasciencenotebooksession'}}")
    stmts = [f"Allow any-user to {verb} in {comp} where {who}" for verb in (
        "read buckets",
        "manage objects",
        "manage data-science-family",
        "manage repos",
        "use virtual-network-family",
        "use log-groups",
        "use log-content",
        "use generative-ai-family",
        "read compartments",
    )]
    ensure_policy(idn, cid, "dmb-workloads", "VM de trabalho e notebooks do benchmark", stmts)


def ensure_dev_network(vn, cid, vcn_id):
    cfg = {"region": REGION}  # a sub-rede de desenvolvimento só existe na região principal
    igw = next((g for g in vn.list_internet_gateways(cid, vcn_id=vcn_id).data
                if g.lifecycle_state == "AVAILABLE"), None)
    if igw is None:
        igw = vn.create_internet_gateway(oci.core.models.CreateInternetGatewayDetails(
            compartment_id=cid, vcn_id=vcn_id, display_name="dmb-igw-dev", is_enabled=True,
            freeform_tags=TAGS)).data
        igw = oci.wait_until(vn, vn.get_internet_gateway(igw.id), "lifecycle_state", "AVAILABLE").data
    record("Internet Gateway", "dmb-igw-dev (só para a sub-rede de desenvolvimento)", igw.id, cfg["region"])

    rt = next((r for r in vn.list_route_tables(cid, vcn_id=vcn_id, display_name="dmb-rt-dev").data
               if r.lifecycle_state == "AVAILABLE"), None)
    if rt is None:
        rt = vn.create_route_table(oci.core.models.CreateRouteTableDetails(
            compartment_id=cid, vcn_id=vcn_id, display_name="dmb-rt-dev", freeform_tags=TAGS,
            route_rules=[oci.core.models.RouteRule(destination="0.0.0.0/0", destination_type="CIDR_BLOCK",
                                                   network_entity_id=igw.id)])).data
        rt = oci.wait_until(vn, vn.get_route_table(rt.id), "lifecycle_state", "AVAILABLE").data
    record("Route Table", "dmb-rt-dev (internet via IGW)", rt.id, cfg["region"])

    ingress = [oci.core.models.IngressSecurityRule(
        source=SSH_ALLOWED_CIDR, protocol="6", description="SSH só do IP autorizado",
        tcp_options=oci.core.models.TcpOptions(destination_port_range=oci.core.models.PortRange(min=22, max=22)))]
    sl = next((x for x in vn.list_security_lists(cid, vcn_id=vcn_id, display_name="dmb-sl-dev").data
               if x.lifecycle_state == "AVAILABLE"), None)
    if sl is None:
        sl = vn.create_security_list(oci.core.models.CreateSecurityListDetails(
            compartment_id=cid, vcn_id=vcn_id, display_name="dmb-sl-dev", freeform_tags=TAGS,
            ingress_security_rules=ingress,
            egress_security_rules=[oci.core.models.EgressSecurityRule(destination="0.0.0.0/0", protocol="all")])).data
        sl = oci.wait_until(vn, vn.get_security_list(sl.id), "lifecycle_state", "AVAILABLE").data
    elif [r.source for r in sl.ingress_security_rules] != [SSH_ALLOWED_CIDR]:
        vn.update_security_list(sl.id, oci.core.models.UpdateSecurityListDetails(
            ingress_security_rules=ingress, egress_security_rules=sl.egress_security_rules))
    record("Security List", f"dmb-sl-dev (SSH de {SSH_ALLOWED_CIDR})", sl.id, cfg["region"])

    sub = next((x for x in vn.list_subnets(cid, vcn_id=vcn_id, display_name="dmb-subnet-dev").data
                if x.lifecycle_state == "AVAILABLE"), None)
    if sub is None:
        sub = vn.create_subnet(oci.core.models.CreateSubnetDetails(
            compartment_id=cid, vcn_id=vcn_id, display_name="dmb-subnet-dev", cidr_block=DEV_SUBNET_CIDR,
            dns_label="dev", prohibit_public_ip_on_vnic=False, route_table_id=rt.id,
            security_list_ids=[sl.id], freeform_tags=TAGS)).data
        sub = oci.wait_until(vn, vn.get_subnet(sub.id), "lifecycle_state", "AVAILABLE").data
    record("Subnet (desenvolvimento)", f"dmb-subnet-dev ({DEV_SUBNET_CIDR})", sub.id, cfg["region"])
    return sub.id


def ensure_vm(cfg, cid):
    """Registra a VM de trabalho, os volumes anexados e o acesso SSH. Não cria instâncias."""
    cc = oci.core.ComputeClient(cfg)
    vm = next((i for i in cc.list_instances(cid, display_name=VM_NAME).data
               if i.lifecycle_state not in ("TERMINATED", "TERMINATING")), None)
    if vm is None:
        print(f"aviso: VM {VM_NAME} não encontrada")
        return None
    vn = oci.core.VirtualNetworkClient(cfg)
    bs = oci.core.BlockstorageClient(cfg)
    vnic = vn.get_vnic(cc.list_vnic_attachments(cid, instance_id=vm.id).data[0].vnic_id).data
    record("Compute Instance", f"{VM_NAME} ({vm.shape}, {vm.shape_config.ocpus:.0f} OCPU, "
           f"{vm.shape_config.memory_in_gbs:.0f} GB, Oracle Linux 9, IP público {vnic.public_ip}, "
           f"usuário {VM_USER}, chave {VM_SSH_KEY})", vm.id, cfg["region"])
    for att in cc.list_boot_volume_attachments(vm.availability_domain, cid, instance_id=vm.id).data:
        bv = bs.get_boot_volume(att.boot_volume_id).data
        record("Boot Volume", f"{bv.display_name} ({bv.size_in_gbs} GB, raiz /)", bv.id, cfg["region"])
    for att in cc.list_volume_attachments(cid, instance_id=vm.id).data:
        if att.lifecycle_state == "ATTACHED":
            v = bs.get_volume(att.volume_id).data
            record("Block Volume", f"{v.display_name} ({v.size_in_gbs} GB, {att.attachment_type}, "
                   f"{att.device}, montado em /data)", v.id, cfg["region"])
    return vnic.public_ip


def ensure_notebook(cfg, cid, project_id):
    ds = oci.data_science.DataScienceClient(cfg)
    nb = next((n for n in ds.list_notebook_sessions(cid, project_id=project_id).data
               if n.display_name == NOTEBOOK_NAME and n.lifecycle_state not in ("DELETED", "DELETING")), None)
    if nb is None:
        shape, ocpus, mem = NOTEBOOK_SHAPE
        nb = ds.create_notebook_session(oci.data_science.models.CreateNotebookSessionDetails(
            compartment_id=cid, project_id=project_id, display_name=NOTEBOOK_NAME, freeform_tags=TAGS,
            notebook_session_config_details=oci.data_science.models.NotebookSessionConfigDetails(
                shape=shape, block_storage_size_in_gbs=200,
                notebook_session_shape_config_details=oci.data_science.models.NotebookSessionShapeConfigDetails(
                    ocpus=ocpus, memory_in_gbs=mem)))).data
    record("Data Science Notebook Session", f"{NOTEBOOK_NAME} ({NOTEBOOK_SHAPE[0]}, rede gerenciada, "
           f"estado {nb.lifecycle_state})", nb.id, cfg["region"])


def write_artifacts():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Artefatos OCI — benchmark de modelos de decisão",
        "",
        f"Atualizado em {now} por `infra/oci/provision.py`. Região principal: `{REGION}`; GPU também em `{GPU_REGION}`.",
        f"Tags livres aplicadas: {', '.join(f'`{k}={v}`' for k, v in TAGS.items())} (`centro_custo` pendente, Q13).",
        "",
        "| Tipo | Nome | OCID | Região |",
        "|------|------|------|--------|",
    ]
    lines += [f"| {k} | {n} | `{o}` | {r} |" for k, n, o, r in artifacts]
    ARTIFACTS_FILE.write_text("\n".join(lines) + "\n")


def main():
    home = load_config(region="us-ashburn-1")
    cfg = load_config()
    idn = oci.identity.IdentityClient(home)
    cid = find_compartment(idn, home["tenancy"])
    ensure_policies(idn, cid, home["user"])
    ensure_workload_policy(idn, cid)
    project_id = ensure_ds_project(cfg, cid)
    ensure_buckets(cfg, cid)
    vcn_id = ensure_network(cfg, cid)
    ensure_dev_network(oci.core.VirtualNetworkClient(cfg), cid, vcn_id)
    ensure_vm(cfg, cid)
    ensure_notebook(cfg, cid, project_id)

    gru = load_config(region=GPU_REGION)
    ensure_ds_project(gru, cid)
    ensure_buckets(gru, cid, suffix=GPU_SUFFIX, buckets=GPU_BUCKETS)
    try:
        ensure_network(gru, cid)
    except oci.exceptions.ServiceError as error:
        if error.code != "LimitExceeded":
            raise
        # Sem VCN disponível na região: jobs de GPU usam rede gerenciada + isolamento no processo.
        print(f"aviso: VCN indisponível em {GPU_REGION} ({error.message[:80]})")
    write_artifacts()
    for a in artifacts:
        print(" | ".join(a))


if __name__ == "__main__":
    main()

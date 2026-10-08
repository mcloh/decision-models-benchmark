"""Deprovisionamento completo do experimento (inverso de provision.py).

Sem --execute, só lista o que existe. Com --execute, apaga na ordem:
Data Science (notebooks, jobs e execuções, projetos) → logs → buckets (regras de retenção e todas as
versões de objetos) → rede (sub-redes, tabelas de rota, security lists, gateways, VCN) → políticas →
compartment. Nas regiões principal e de GPU.

Uso: PYTHONPATH=infra/oci .venv/bin/python infra/oci/teardown.py [--execute] [--keep-compartment]
"""
import sys
import time

import oci

import provision
from session import load_config

REGIONS = [provision.REGION, provision.GPU_REGION]


def compartment_id() -> str:
    home = load_config(region="us-ashburn-1")
    idn = oci.identity.IdentityClient(home)
    comps = oci.pagination.list_call_get_all_results(
        idn.list_compartments, home["tenancy"], compartment_id_in_subtree=True,
        access_level="ACCESSIBLE", lifecycle_state="ACTIVE").data
    parent = next(c for c in comps if c.name == provision.PARENT_PATH.rsplit("/", 1)[-1])
    return next(c.id for c in comps if c.compartment_id == parent.id and c.name == provision.COMPARTMENT_NAME)


def inventory(cid):
    for region in REGIONS:
        cfg = load_config(region=region)
        search = oci.resource_search.ResourceSearchClient(cfg)
        res = search.search_resources(oci.resource_search.models.StructuredSearchDetails(
            query=f"query all resources where compartmentId = '{cid}' && lifecycleState != 'TERMINATED' "
                  f"&& lifecycleState != 'DELETED'")).data.items
        print(f"\n== {region}: {len(res)} recursos")
        for r in sorted(res, key=lambda r: r.resource_type):
            print(f"  {r.resource_type:28} {r.display_name or ''}  [{r.lifecycle_state}]")


def wait_gone(get, *args, timeout=1800):
    start = time.time()
    while time.time() - start < timeout:
        try:
            state = get(*args).data.lifecycle_state
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                return
            raise
        if state in ("DELETED", "TERMINATED"):
            return
        time.sleep(10)


def data_science(cfg, cid):
    ds = oci.data_science.DataScienceClient(cfg)
    for nb in ds.list_notebook_sessions(cid).data:
        if nb.lifecycle_state not in ("DELETED", "DELETING"):
            ds.delete_notebook_session(nb.id)
            print("  notebook apagando:", nb.display_name)
    for nb in ds.list_notebook_sessions(cid).data:
        wait_gone(ds.get_notebook_session, nb.id)
    jobs = oci.pagination.list_call_get_all_results(ds.list_jobs, cid).data
    for j in jobs:
        if j.lifecycle_state not in ("DELETED", "DELETING"):
            ds.delete_job(j.id, delete_related_job_runs=True)
    for j in jobs:
        wait_gone(ds.get_job, j.id)
    print(f"  jobs apagados: {len(jobs)}")
    for p in ds.list_projects(cid).data:
        if p.lifecycle_state == "ACTIVE":
            ds.delete_project(p.id)
            wait_gone(ds.get_project, p.id)
            print("  projeto apagado:", p.display_name)


def logging(cfg, cid):
    lc = oci.logging.LoggingManagementClient(cfg)
    for g in lc.list_log_groups(cid).data:
        for log in lc.list_logs(g.id).data:
            lc.delete_log(g.id, log.id)
        for _ in range(60):
            if not lc.list_logs(g.id).data:
                break
            time.sleep(5)
        lc.delete_log_group(g.id)
        print("  grupo de logs apagado:", g.display_name)


def buckets(cfg, cid):
    os_ = oci.object_storage.ObjectStorageClient(cfg)
    ns = os_.get_namespace().data
    for b in oci.pagination.list_call_get_all_results(os_.list_buckets, ns, cid).data:
        for rule in os_.list_retention_rules(ns, b.name).data.items:
            os_.delete_retention_rule(ns, b.name, rule.id)
        if os_.get_bucket(ns, b.name).data.versioning == "Enabled":
            os_.update_bucket(ns, b.name, oci.object_storage.models.UpdateBucketDetails(versioning="Suspended"))
        versions = oci.pagination.list_call_get_all_results(os_.list_object_versions, ns, b.name).data
        for v in versions:
            os_.delete_object(ns, b.name, v.name, version_id=v.version_id)
        for u in oci.pagination.list_call_get_all_results(os_.list_multipart_uploads, ns, b.name).data:
            os_.abort_multipart_upload(ns, b.name, u.object, u.upload_id)
        for par in oci.pagination.list_call_get_all_results(os_.list_preauthenticated_requests, ns, b.name).data:
            os_.delete_preauthenticated_request(ns, b.name, par.id)
        os_.delete_bucket(ns, b.name)
        print(f"  bucket apagado: {b.name} ({len(versions)} versões de objetos)")


def network(cfg, cid):
    vn = oci.core.VirtualNetworkClient(cfg)
    for vcn in vn.list_vcns(cid).data:
        if vcn.lifecycle_state != "AVAILABLE":
            continue
        for s in vn.list_subnets(cid, vcn_id=vcn.id).data:
            vn.delete_subnet(s.id)
            wait_gone(vn.get_subnet, s.id)
        default_rt, default_sl = vcn.default_route_table_id, vcn.default_security_list_id
        vn.update_route_table(default_rt, oci.core.models.UpdateRouteTableDetails(route_rules=[]))
        for rt in vn.list_route_tables(cid, vcn_id=vcn.id).data:
            if rt.id != default_rt:
                vn.delete_route_table(rt.id)
                wait_gone(vn.get_route_table, rt.id)
        for sl in vn.list_security_lists(cid, vcn_id=vcn.id).data:
            if sl.id != default_sl:
                vn.delete_security_list(sl.id)
                wait_gone(vn.get_security_list, sl.id)
        for g in vn.list_service_gateways(cid, vcn_id=vcn.id).data:
            vn.delete_service_gateway(g.id)
            wait_gone(vn.get_service_gateway, g.id)
        for g in vn.list_internet_gateways(cid, vcn_id=vcn.id).data:
            vn.delete_internet_gateway(g.id)
            wait_gone(vn.get_internet_gateway, g.id)
        for g in vn.list_nat_gateways(cid, vcn_id=vcn.id).data:
            vn.delete_nat_gateway(g.id)
            wait_gone(vn.get_nat_gateway, g.id)
        vn.delete_vcn(vcn.id)
        wait_gone(vn.get_vcn, vcn.id)
        print("  VCN apagada:", vcn.display_name)


def iam(cid, keep_compartment):
    home = load_config(region="us-ashburn-1")
    idn = oci.identity.IdentityClient(home)
    for p in idn.list_policies(cid).data:
        idn.delete_policy(p.id)
        print("  política apagada:", p.name)
    if not keep_compartment:
        idn.delete_compartment(cid)
        print("  compartment em exclusão (assíncrona)")


def main():
    cid = compartment_id()
    inventory(cid)
    if "--execute" not in sys.argv:
        print("\n(somente inventário; use --execute para apagar)")
        return
    for region in REGIONS:
        cfg = load_config(region=region)
        print(f"\n## {region}")
        data_science(cfg, cid)
        logging(cfg, cid)
        buckets(cfg, cid)
        network(cfg, cid)
    print("\n## IAM")
    iam(cid, "--keep-compartment" in sys.argv)
    time.sleep(20)
    inventory(cid)


if __name__ == "__main__":
    main()

"""Liga e desliga a saída temporária por NAT Gateway (tarefas 9, 17 e 78; decisão Q3).

Uso:
  PYTHONPATH=infra/oci .venv/bin/python infra/oci/nat.py on            # cria/desbloqueia o NAT e abre a rota
  PYTHONPATH=infra/oci .venv/bin/python infra/oci/nat.py off           # fecha a rota e bloqueia o NAT
  PYTHONPATH=infra/oci .venv/bin/python infra/oci/nat.py off --delete  # fecha a rota e apaga o NAT (tarefa 78)

O NAT só deve ficar ativo durante a aquisição de dependências e pesos.
Ao final, regrava .secrets/artefatos-OCI.md.
"""
import sys

import oci

import provision
from session import load_config

NAT_NAME = "dmb-nat-temporario"
ANYWHERE = "0.0.0.0/0"


def lookup(vn, cid):
    vcn = next(v for v in vn.list_vcns(cid, display_name="dmb-vcn").data if v.lifecycle_state == "AVAILABLE")
    rt = next(r for r in vn.list_route_tables(cid, vcn_id=vcn.id, display_name="dmb-rt-privada").data
              if r.lifecycle_state == "AVAILABLE")
    sl = next(s for s in vn.list_security_lists(cid, vcn_id=vcn.id, display_name="dmb-sl-privada").data
              if s.lifecycle_state == "AVAILABLE")
    nat = next((n for n in vn.list_nat_gateways(cid, vcn_id=vcn.id, display_name=NAT_NAME).data
                if n.lifecycle_state == "AVAILABLE"), None)
    return vcn, rt, sl, nat


def nat_on(vn, cid):
    vcn, rt, sl, nat = lookup(vn, cid)
    if nat is None:
        nat = vn.create_nat_gateway(oci.core.models.CreateNatGatewayDetails(
            compartment_id=cid, vcn_id=vcn.id, display_name=NAT_NAME,
            freeform_tags=provision.TAGS)).data
        nat = oci.wait_until(vn, vn.get_nat_gateway(nat.id), "lifecycle_state", "AVAILABLE").data
    elif nat.block_traffic:
        vn.update_nat_gateway(nat.id, oci.core.models.UpdateNatGatewayDetails(block_traffic=False))

    if not any(r.destination == ANYWHERE for r in rt.route_rules):
        vn.update_route_table(rt.id, oci.core.models.UpdateRouteTableDetails(route_rules=rt.route_rules + [
            oci.core.models.RouteRule(destination=ANYWHERE, destination_type="CIDR_BLOCK",
                                      network_entity_id=nat.id, description="TEMPORÁRIO: aquisição de artefatos")]))
    if not any(r.destination == ANYWHERE for r in sl.egress_security_rules):
        vn.update_security_list(sl.id, oci.core.models.UpdateSecurityListDetails(
            ingress_security_rules=sl.ingress_security_rules,
            egress_security_rules=sl.egress_security_rules + [oci.core.models.EgressSecurityRule(
                destination=ANYWHERE, protocol="6", description="TEMPORÁRIO: HTTPS para aquisição",
                tcp_options=oci.core.models.TcpOptions(
                    destination_port_range=oci.core.models.PortRange(min=443, max=443)))]))
    print(f"NAT ativo: {nat.id}")


def nat_off(vn, cid, delete):
    _, rt, sl, nat = lookup(vn, cid)
    rules = [r for r in rt.route_rules if r.destination != ANYWHERE]
    if len(rules) != len(rt.route_rules):
        vn.update_route_table(rt.id, oci.core.models.UpdateRouteTableDetails(route_rules=rules))
    egress = [r for r in sl.egress_security_rules if r.destination != ANYWHERE]
    if len(egress) != len(sl.egress_security_rules):
        vn.update_security_list(sl.id, oci.core.models.UpdateSecurityListDetails(
            ingress_security_rules=sl.ingress_security_rules, egress_security_rules=egress))
    if nat is None:
        print("NAT inexistente; rota e egresso fechados")
        return
    if delete:
        vn.delete_nat_gateway(nat.id)
        print(f"NAT apagado: {nat.id}")
    else:
        vn.update_nat_gateway(nat.id, oci.core.models.UpdateNatGatewayDetails(block_traffic=True))
        print(f"NAT bloqueado: {nat.id}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("on", "off"):
        sys.exit(__doc__)
    cfg = load_config()
    home = load_config(region="us-ashburn-1")
    cid = provision.find_compartment(oci.identity.IdentityClient(home), home["tenancy"])
    vn = oci.core.VirtualNetworkClient(cfg)
    if sys.argv[1] == "on":
        nat_on(vn, cid)
    else:
        nat_off(vn, cid, delete="--delete" in sys.argv)
    provision.artifacts.clear()
    provision.main()


if __name__ == "__main__":
    main()

"""Execução no OCI Data Science: a máquina local só empacota o código e dispara jobs.

Uso:
  PYTHONPATH=infra/oci .venv/bin/python infra/ds/jobs.py run --name probe --entrypoint infra/ds/probe.sh \
      [--shape VM.Standard.E4.Flex --ocpus 2 --memory 16 | --shape VM.GPU.A10.1] [--private] \
      [--env K=V ...] [--wait]
  PYTHONPATH=infra/oci .venv/bin/python infra/ds/jobs.py logs <job_run_ocid>

--private usa a sub-rede dmb-subnet-jobs (sem internet; só Service Gateway).
Sem --private, o job usa a rede gerenciada do serviço (com internet), só para builds.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import oci

from session import load_config
import provision

ROOT = Path(__file__).resolve().parents[2]
EXCLUDE_DIRS = {".git", ".secrets", "models", "reports", "runs", "__pycache__", ".pytest_cache"}
LOG_GROUP = "dmb-logs"


def compartment(cfg_home) -> str:
    return provision.find_compartment(oci.identity.IdentityClient(cfg_home), cfg_home["tenancy"])


def code_zip() -> tuple[bytes, str]:
    """Snapshot do repositório local (sem segredos, modelos e venvs)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("dmb/"), "")
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if any(part in EXCLUDE_DIRS or part.startswith(".venv") for part in rel.parts):
                continue
            if p.is_dir():
                z.writestr(zipfile.ZipInfo(f"dmb/{rel.as_posix()}/"), "")
                continue
            info = zipfile.ZipInfo.from_file(p, f"dmb/{rel.as_posix()}")
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    try:
        rev = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip() or "sem-commit"
    except OSError:
        rev = "sem-commit"
    return buf.getvalue(), rev


def ensure_log_group(cfg, cid) -> str:
    lc = oci.logging.LoggingManagementClient(cfg)
    lg = next((g for g in lc.list_log_groups(cid, display_name=LOG_GROUP).data), None)
    if lg is None:
        lc.create_log_group(oci.logging.models.CreateLogGroupDetails(
            compartment_id=cid, display_name=LOG_GROUP, description="Logs dos jobs do benchmark",
            freeform_tags=provision.TAGS))
        for _ in range(30):
            lg = next((g for g in lc.list_log_groups(cid, display_name=LOG_GROUP).data), None)
            if lg:
                break
            time.sleep(5)
    return lg.id


def subnet_id(cfg, cid) -> str:
    vn = oci.core.VirtualNetworkClient(cfg)
    return next(s.id for s in vn.list_subnets(cid, display_name="dmb-subnet-jobs").data
                if s.lifecycle_state == "AVAILABLE")


def run_job(name, entrypoint, shape, ocpus, memory, private, env, storage_gb=100, max_minutes=240, region=None):
    cfg, home = load_config(region=region) if region else load_config(), load_config(region="us-ashburn-1")
    cid = compartment(home)
    ds = oci.data_science.DataScienceClient(cfg)
    project = next(p.id for p in ds.list_projects(cid, lifecycle_state="ACTIVE").data
                   if p.display_name == "benchmark-decisoes-ptbr")
    log_group = ensure_log_group(cfg, cid)
    flex = shape.endswith(".Flex")
    infra = oci.data_science.models.StandaloneJobInfrastructureConfigurationDetails(
        job_infrastructure_type="STANDALONE" if private else "ME_STANDALONE",
        shape_name=shape, block_storage_size_in_gbs=storage_gb,
        subnet_id=subnet_id(cfg, cid) if private else None,
        job_shape_config_details=oci.data_science.models.JobShapeConfigDetails(
            ocpus=ocpus, memory_in_gbs=memory) if flex else None)
    payload, rev = code_zip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    env = {"JOB_RUN_ENTRYPOINT": f"dmb/{entrypoint}", "DMB_CODE_REV": rev, **env}
    if cfg["region"] == provision.GPU_REGION:
        env.setdefault("DMB_BUCKET_ARTIFACTS", f"dmb-artefatos{provision.GPU_SUFFIX}")
        env.setdefault("DMB_BUCKET_RESULTS", f"dmb-resultados{provision.GPU_SUFFIX}")
        if not private:
            env.setdefault("DMB_ISOLATION", "app")
    job = ds.create_job(oci.data_science.models.CreateJobDetails(
        project_id=project, compartment_id=cid, display_name=f"dmb-{name}-{stamp}",
        freeform_tags=provision.TAGS,
        job_configuration_details=oci.data_science.models.DefaultJobConfigurationDetails(
            job_type="DEFAULT", environment_variables=env,
            maximum_runtime_in_minutes=max_minutes),
        job_infrastructure_configuration_details=infra,
        job_log_configuration_details=oci.data_science.models.JobLogConfigurationDetails(
            enable_logging=True, enable_auto_log_creation=True, log_group_id=log_group))).data
    ds.create_job_artifact(job.id, payload, content_disposition="attachment; filename=dmb.zip")
    run = ds.create_job_run(oci.data_science.models.CreateJobRunDetails(
        project_id=project, compartment_id=cid, job_id=job.id,
        display_name=f"dmb-{name}-{stamp}", freeform_tags=provision.TAGS)).data
    print(f"job {job.id}\nrun {run.id}", flush=True)
    return run.id


def region_of(ocid: str) -> str:
    return ocid.split(".")[3] if ocid.count(".") >= 4 and ocid.split(".")[3] else load_config()["region"]


def wait(run_id, poll=30):
    ds = oci.data_science.DataScienceClient(load_config(region=region_of(run_id)))
    while True:
        r = ds.get_job_run(run_id).data
        if r.lifecycle_state in ("SUCCEEDED", "FAILED", "CANCELED", "DELETED"):
            print("estado:", r.lifecycle_state, r.lifecycle_details or "", flush=True)
            return r
        time.sleep(poll)


def logs(run_id, limit=500):
    cfg = load_config(region=region_of(run_id))
    ds = oci.data_science.DataScienceClient(cfg)
    r = ds.get_job_run(run_id).data
    if not r.log_details:
        print("sem log configurado ainda")
        return
    search = oci.loggingsearch.LogSearchClient(cfg)
    start = r.time_accepted - timedelta(minutes=5)
    end = (r.time_finished or datetime.now(timezone.utc)) + timedelta(minutes=10)
    query = (f'search "{r.compartment_id}/{r.log_details.log_group_id}/{r.log_details.log_id}" '
             "| sort by datetime asc")
    try:
        res = search.search_logs(oci.loggingsearch.models.SearchLogsDetails(
            time_start=start, time_end=end, search_query=query, is_return_field_info=False), limit=limit).data
    except oci.exceptions.ServiceError as error:
        print(f"logs indisponíveis ({error.status} {error.code}); log_id={r.log_details.log_id}")
        return
    for item in res.results or []:
        print(item.data.get("logContent", {}).get("data", {}).get("message", ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--name", required=True)
    r.add_argument("--entrypoint", required=True)
    r.add_argument("--shape", default="VM.Standard.E4.Flex")
    r.add_argument("--ocpus", type=float, default=2)
    r.add_argument("--memory", type=float, default=16)
    r.add_argument("--storage", type=int, default=100)
    r.add_argument("--private", action="store_true")
    r.add_argument("--env", nargs="*", default=[])
    r.add_argument("--wait", action="store_true")
    r.add_argument("--region", help="padrão: us-chicago-1; sa-saopaulo-1 para GPU")
    lg = sub.add_parser("logs")
    lg.add_argument("run_id")
    args = ap.parse_args()
    if args.cmd == "logs":
        logs(args.run_id)
        return
    env = dict(kv.split("=", 1) for kv in args.env)
    run_id = run_job(args.name, args.entrypoint, args.shape, args.ocpus, args.memory, args.private,
                     env, storage_gb=args.storage, region=args.region)
    if args.wait:
        result = wait(run_id)
        time.sleep(60)  # ingestão dos logs
        logs(run_id)
        sys.exit(0 if result.lifecycle_state == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Seed incidents into ServiceNow PDI based on the SOP: Handling ServiceNow Incidents
for Airflow Issues (AC360 / BDP 501 Data Processing).

Creates assignment groups from SOP (APL_UDAP: Data Processing, BDP Support, etc.)
and assigns incidents accordingly. Use --delete-first to wipe existing incidents
before seeding fresh.

Usage:
    python seed_incidents_sop.py
    python seed_incidents_sop.py --delete-first   # Delete all, then seed
    python seed_incidents_sop.py --use-admin     # Seed with admin (fresh PDI)
"""

import argparse
import os
import random
import sys
import time
from dotenv import load_dotenv

load_dotenv(override=True)

import requests


# ── Config (can override via env) ───────────────────────────────────

def _get_auth(use_admin: bool):
    base = os.getenv("SERVICENOW_INSTANCE_URL", "").rstrip("/")
    if use_admin:
        user = os.getenv("SERVICENOW_ADMIN_USER", os.getenv("SERVICENOW_ADMIN_USERNAME", "admin"))
        password = os.getenv("SERVICENOW_ADMIN_PASSWORD", "")
        if not password:
            print("Error: SERVICENOW_ADMIN_PASSWORD required when using --use-admin")
            sys.exit(1)
    else:
        user = os.getenv("SERVICENOW_USERNAME", "incident.bot")
        password = os.getenv("SERVICENOW_PASSWORD", "")
    return base, user, password


def _verify_connection(base_url: str, auth: tuple) -> bool:
    """Test auth with a simple GET. Returns True if OK."""
    url = f"{base_url}/api/now/table/incident"
    params = {"sysparm_limit": 1, "sysparm_fields": "sys_id"}
    try:
        r = requests.get(url, auth=auth, headers={"Accept": "application/json"}, params=params, timeout=15)
        if r.status_code == 401:
            return False
        r.raise_for_status()
        return True
    except Exception:
        return False


def _create_incident(base_url: str, auth: tuple, payload: dict) -> dict:
    url = f"{base_url}/api/now/table/incident"
    r = requests.post(url, auth=auth, headers={"Accept": "application/json", "Content-Type": "application/json"}, json=payload, timeout=30)
    r.raise_for_status()
    return r.json().get("result", {})


def _delete_all_incidents(base_url: str, auth: tuple) -> int:
    """Delete all incidents. Returns count deleted."""
    url = f"{base_url}/api/now/table/incident"
    headers = {"Accept": "application/json"}
    deleted = 0
    while True:
        r = requests.get(url, auth=auth, headers=headers, params={"sysparm_limit": 100, "sysparm_fields": "sys_id"}, timeout=30)
        r.raise_for_status()
        results = r.json().get("result", [])
        if not results:
            break
        for rec in results:
            sid = rec.get("sys_id")
            if sid:
                dr = requests.delete(f"{base_url}/api/now/table/incident/{sid}", auth=auth, headers=headers, timeout=30)
                if dr.status_code in (200, 204):
                    deleted += 1
                elif dr.status_code == 404:
                    pass  # already deleted (e.g. cascade)
                else:
                    dr.raise_for_status()
        time.sleep(0.3)
    return deleted


def _get_or_create_group(base_url: str, auth: tuple, name: str) -> str | None:
    """Get group sys_id by name; create if not exists."""
    url = f"{base_url}/api/now/table/sys_user_group"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    # Escape colon for ServiceNow encoded query (^: = literal colon)
    query_name = name.replace("^", "^^").replace(":", "^:")
    r = requests.get(url, auth=auth, headers=headers, params={"sysparm_query": f"name={query_name}", "sysparm_fields": "sys_id"}, timeout=30)
    r.raise_for_status()
    results = r.json().get("result", [])
    if results:
        return results[0]["sys_id"]
    # Create
    r = requests.post(url, auth=auth, headers=headers, json={"name": name}, timeout=30)
    r.raise_for_status()
    return r.json().get("result", {}).get("sys_id")


def _get_user_sys_id(base_url: str, auth: tuple, user_name: str) -> str | None:
    """Get user sys_id by user_name."""
    url = f"{base_url}/api/now/table/sys_user"
    r = requests.get(url, auth=auth, headers={"Accept": "application/json"}, params={"sysparm_query": f"user_name={user_name}", "sysparm_fields": "sys_id"}, timeout=30)
    r.raise_for_status()
    results = r.json().get("result", [])
    return results[0]["sys_id"] if results else None


# SOP assignment groups: Production -> APL_UDAP; Non-Prod -> BDP Support; Infra -> Infrastructure; Data -> Data Engineering
ASSIGNMENT_GROUPS = [
    "APL_UDAP: Data Processing",  # SOP Step 5A - Production
    "BDP Support",                # Non-Production, Support/Operations
    "Data Engineering",            # Data pipelines, Spark, ELZ
    "Infrastructure",             # AKS, Database, platform
]


# ── Pools (SOP + seed_incidents inspired) ───────────────────────────

ENVS = ["c360-prod", "c360-nonprod", "c360-uat", "c360-dev"]
PROD_ENVS = ["c360-prod"]
FM_DAGS = [
    "c360-prod-fm-customer-profile", "c360-prod-fm-account-summary", "c360-prod-fm-transaction-ingest",
    "c360-prod-fm-party-master", "c360-nonprod-fm-customer-profile", "c360-nonprod-fm-transaction-ingest",
]
SM_DAGS = [
    "c360-prod-sm-risk-score", "c360-prod-sm-kyc-refresh", "c360-prod-sm-balance-agg",
    "c360-prod-sm-fraud-features", "c360-nonprod-sm-risk-score", "c360-nonprod-sm-kyc-refresh",
]
TM_DAGS = [
    "c360-prod-tm-gold-dashboard", "c360-prod-tm-reporting-agg", "c360-prod-tm-regulatory-extract",
    "c360-nonprod-tm-gold-dashboard",
]
BDP_DAGS = [
    "c360-prod-bdp-data-quality", "c360-prod-bdp-audit-reconciliation", "c360-prod-bdp-schema-validator",
    "c360-nonprod-bdp-data-quality",
]
DATA_DAGS = [
    "c360-prod-dp-payments-ingestion", "c360-prod-dp-loans-transform", "c360-prod-dp-cards-enrichment",
    "c360-prod-dp-deposits-agg", "c360-prod-dp-mortgage-load", "c360-nonprod-dp-payments-ingestion",
    "c360-nonprod-dp-loans-transform",
]
ALL_UTILITY_DAGS = FM_DAGS + SM_DAGS + TM_DAGS + BDP_DAGS + DATA_DAGS

HIVE_TABLES = [
    "bronze.elz_customer_raw", "bronze.elz_transaction_raw", "bronze.elz_account_raw",
    "core.c360_customer_profile", "core.c360_account_summary", "gold.rpt_customer_360",
]
SPARK_APPS = [
    "bdp-spark-customer-ingest", "bdp-spark-transaction-transform", "bdp-spark-risk-calc",
    "bdp-spark-balance-agg", "bdp-spark-fraud-detection", "bdp-spark-kyc-refresh",
]
AKS_NODES = ["aks-bdppool-node01", "aks-bdppool-node02", "aks-airflowpool-node01", "aks-airflowpool-node02"]
EXIT_CODES = [1, 2, 126, 127, 137, 139, 143]


def _r(lst):
    return random.choice(lst)


# ── Incident generators ─────────────────────────────────────────────

def sigterm_utility_dag():
    for dag in random.choices(ALL_UTILITY_DAGS, k=30):
        env = "Production" if "prod-" in dag and "nonprod" not in dag else "Non-Production"
        grp = "APL_UDAP: Data Processing" if env == "Production" else "BDP Support"
        yield {
            "short_description": f"Airflow DAG {dag} — Task received SIGTERM signal",
            "description": f"DAG: {dag}\nEnvironment: {env}\n\nThe task received a SIGTERM signal. Airflow logs show 'AirflowTaskTerminated'. Infrastructure disruption, worker restart, or pod eviction. Downstream tasks blocked.",
            "work_notes": f"[Triage] SIGTERM on {dag}. Worker pod evicted on {_r(AKS_NODES)}. {'Routing to APL_UDAP per SOP.' if env == 'Production' else 'Jira created, BDP notified.'}",
            "impact": "2", "urgency": "1" if env == "Production" else "2", "category": "Software",
            "assignment_group_name": grp,
        }


def airflow_platform():
    for env in random.choices(ENVS, k=12):
        is_prod = env in PROD_ENVS
        grp = "APL_UDAP: Data Processing" if is_prod else "BDP Support"
        yield {
            "short_description": f"Airflow platform instability — {env}",
            "description": f"Environment: {env}\n\nAirflow platform unstable or down. Scheduler heartbeat lost, workers disconnecting. Multiple utility DAG failures. AC360 / BDP 501 impacted.",
            "work_notes": f"[Triage] Validating Airflow availability per SOP. BDP to restore. {'Routed to APL_UDAP.' if is_prod else 'BDP notified.'}",
            "impact": "1" if is_prod else "2", "urgency": "1", "category": "Software",
            "assignment_group_name": grp,
        }


def downstream_dag_failures():
    for dag in random.choices(DATA_DAGS, k=20):
        env = "Production" if "prod-" in dag and "nonprod" not in dag else "Non-Production"
        grp = "APL_UDAP: Data Processing" if env == "Production" else "Data Engineering"
        yield {
            "short_description": f"Data Processing DAG {dag} failed — upstream Airflow issue",
            "description": f"DAG: {dag}\nEnvironment: {env}\n\nDownstream DAG failed due to upstream Airflow instability. AirflowTaskTerminated or SIGTERM in dependency chain. Per SOP: restart after stabilization.",
            "work_notes": f"[Triage] Upstream resolved. Restarting DAG from Airflow UI. {'Routed to APL_UDAP.' if env == 'Production' else 'BDP notified.'}",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": grp,
        }


def utility_dag_exit_codes():
    for dag in random.choices(ALL_UTILITY_DAGS, k=12):
        env = "Production" if "prod-" in dag and "nonprod" not in dag else "Non-Production"
        code = _r(EXIT_CODES)
        grp = "APL_UDAP: Data Processing" if env == "Production" else "BDP Support"
        yield {
            "short_description": f"Utility DAG {dag} failed with exit code {code}",
            "description": f"DAG: {dag}\nExit Code: {code}\nEnvironment: {env}\n\nUtility DAG failed. {'137=OOMKilled; 143=SIGTERM. ' if code in (137, 143) else ''}Task log indicates non-zero exit.",
            "work_notes": f"[Triage] Exit {code} on {dag}. {'Checking K8s limits.' if code == 137 else 'Checking pod eviction.' if code == 143 else 'Reviewing logs.'} {'Routing to APL_UDAP.' if env == 'Production' else 'Jira for BDP.'}",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": grp,
        }


def scheduler_heartbeat():
    for _ in range(15):
        env, node = _r(ENVS), _r(AKS_NODES)
        is_prod = env in PROD_ENVS
        grp = "APL_UDAP: Data Processing" if is_prod else "Infrastructure"
        yield {
            "short_description": f"Airflow scheduler heartbeat lost — {env}",
            "description": f"Environment: {env}\n\nScheduler has not sent heartbeat for 5+ minutes. No new tasks scheduled. DAG runs queued. All pipelines in {env} stalled.",
            "work_notes": f"[Triage] Scheduler pod on {node} in CrashLoopBackOff. PostgreSQL connection pool may be exhausted. Restarting scheduler. {'APL_UDAP engaged.' if is_prod else 'BDP notified.'}",
            "impact": "1" if is_prod else "2", "urgency": "1", "category": "Software",
            "assignment_group_name": grp,
        }


def sensor_timeout():
    tables = ["bronze.elz_customer_raw", "bronze.elz_transaction_raw", "core.c360_customer_profile"]
    for dag in random.choices(ALL_UTILITY_DAGS, k=10):
        table = _r(tables)
        env = "Production" if "prod-" in dag and "nonprod" not in dag else "Non-Production"
        grp = "APL_UDAP: Data Processing" if env == "Production" else "Data Engineering"
        yield {
            "short_description": f"Sensor timeout in {dag} waiting for {table}",
            "description": f"DAG: {dag}\nBlocked: ExternalTaskSensor / HivePartitionSensor\n\nSensor in 'up_for_reschedule' 2+ hours for {table}. Upstream Airflow/DAG issue may be cause.",
            "work_notes": f"[Triage] Upstream feed for {table} delayed. SLA T+2h — at T+3h. {'Routed to APL_UDAP.' if env == 'Production' else 'BDP notified.'}",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": grp,
        }


def dag_import_errors():
    for dag in random.choices(DATA_DAGS, k=5):
        yield {
            "short_description": f"DAG import error — {dag} not visible in Airflow UI",
            "description": f"DAG: {dag}\n\nThe DAG is no longer visible. Scheduler log shows Python import/syntax error. Blocking scheduled pipeline run.",
            "work_notes": "[Triage] Syntax error in DAG file from last deployment. Git commit identified. Notifying pipeline owner to fix and redeploy.",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": "Data Engineering",
        }


def celery_worker_disconnected():
    for node in random.choices(AKS_NODES, k=4):
        yield {
            "short_description": f"Airflow Celery worker disconnected on {node}",
            "description": f"Node: {node}\n\nCelery worker disconnected from message broker. Tasks stuck in 'queued'. Flower shows worker offline.",
            "work_notes": f"[Triage] Worker pod on {node} evicted due to ephemeral storage pressure. Airflow logs exceeded pod limit. Cleaning logs and restarting worker.",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": "Infrastructure",
        }


def connection_pool_exhausted():
    for env in random.choices(ENVS, k=4):
        is_prod = env in PROD_ENVS
        grp = "APL_UDAP: Data Processing" if is_prod else "Infrastructure"
        yield {
            "short_description": f"Airflow DB connection pool exhausted — {env}",
            "description": f"Environment: {env}\n\nAirflow metadata DB (PostgreSQL) connection pool exhausted. 'QueuePool limit of 5 overflow 10 reached'. Multiple DAGs affected.",
            "work_notes": "[Triage] pg_stat_activity shows 120 connections. Max 100. Idle connections from crashed workers. Running pg_terminate_backend. Recommending pgbouncer.",
            "impact": "1", "urgency": "1", "category": "Database",
            "assignment_group_name": grp,
        }


def spark_executor_oom():
    for app in random.choices(SPARK_APPS, k=12):
        mem = _r(["4g", "8g", "16g"])
        yield {
            "short_description": f"Spark executor OOM — {app}",
            "description": f"Application: {app}\nExecutor Memory: {mem}\n\nSpark executor OOM during shuffle. java.lang.OutOfMemoryError: GC overhead limit exceeded. BDP job failed, Airflow task FAILED.",
            "work_notes": f"[Triage] Shuffle spill at 95%. Partition count too low. Recommending repartition(200) and executor memory {'16g' if mem == '8g' else '32g'}.",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": "Data Engineering",
        }


def spark_driver_oom():
    for app in random.choices(SPARK_APPS, k=4):
        yield {
            "short_description": f"Spark driver OOM during collect/broadcast — {app}",
            "description": f"Application: {app}\n\nDriver crashed with OutOfMemoryError during collect() or broadcast join. Large dataset to driver. Airflow task exit 137.",
            "work_notes": "[Triage] Driver 4g. Broadcast join on table beyond auto-broadcast threshold. Disabling broadcast, sort-merge join. Increasing driver to 8g.",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": "Data Engineering",
        }


def pod_eviction():
    for node in random.choices(AKS_NODES, k=6):
        dag = _r(ALL_UTILITY_DAGS)
        env = "Production" if "prod-" in dag and "nonprod" not in dag else "Non-Production"
        grp = "APL_UDAP: Data Processing" if env == "Production" else "Infrastructure"
        yield {
            "short_description": f"Pod evicted — {node} — AirflowTaskTerminated for {dag}",
            "description": f"Node: {node}\nDAG: {dag}\nEnvironment: {env}\n\nKubernetes evicted pod due to memory pressure. AirflowTaskTerminated. Per SOP: validate Airflow, restore if down.",
            "work_notes": f"[Triage] Node {node} under memory pressure. Restarting DAG after stabilization. {'APL_UDAP engaged.' if env == 'Production' else 'BDP notified.'}",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": grp,
        }


def aks_node_notready():
    for node in random.choices(AKS_NODES, k=4):
        yield {
            "short_description": f"AKS node {node} in NotReady state — pods being evicted",
            "description": f"Node: {node}\n\nKubernetes node NotReady. All pods evicted. Airflow workers and Spark executors affected. Multiple pipelines impacted.",
            "work_notes": f"[Triage] Azure VM underlying {node} hardware issue. Autoscaler provisioning replacement. ETA ~5 min. Monitoring DAG runs.",
            "impact": "1", "urgency": "1", "category": "Software",
            "assignment_group_name": "Infrastructure",
        }


def elz_landing_delay():
    for table in random.choices(HIVE_TABLES[:7] if len(HIVE_TABLES) >= 7 else HIVE_TABLES, k=5):
        source = _r(["payments-upstream", "core-banking", "cards-system", "loans-origination"])
        yield {
            "short_description": f"ELZ landing delay — {table} — source: {source}",
            "description": f"Table: {table}\nSource: {source}\n\nData not landed in Bronze within SLA. Source delayed or file transfer failed. Downstream C360 Core blocked.",
            "work_notes": f"[Triage] No files for today's partition. Source {source} confirmed delay. ETA 2h. Notifying downstream.",
            "impact": "2", "urgency": "2", "category": "Software",
            "assignment_group_name": "Data Engineering",
        }


def adls_throttling():
    for container in ["bdp-bronze-landing", "bdp-gold-publish"]:
        yield {
            "short_description": f"ADLS Gen2 throttling — {container} — HTTP 429",
            "description": f"Container: {container}\n\nADLS Gen2 returning HTTP 429. Multiple BDP Spark jobs hitting storage concurrently. Jobs retrying, some timing out.",
            "work_notes": "[Triage] Per-account IOPS limit. 30+ concurrent jobs. Requesting Azure throughput increase. Short-term: staggering schedules.",
            "impact": "2", "urgency": "1", "category": "Software",
            "assignment_group_name": "Infrastructure",
        }


def hive_metastore_timeout():
    for app in random.choices(SPARK_APPS, k=3):
        table = _r(HIVE_TABLES)
        yield {
            "short_description": f"Spark job failed — Hive metastore timeout reading {table}",
            "description": f"Application: {app}\nTable: {table}\n\nMetaException: Hive metastore connection timed out. Metastore slow or unresponsive. Blocking all BDP jobs.",
            "work_notes": "[Triage] Metastore pod healthy but slow. PostgreSQL backend high CPU. Running VACUUM ANALYZE. Restarting metastore pod.",
            "impact": "1", "urgency": "1", "category": "Database",
            "assignment_group_name": "Infrastructure",
        }


def sla_breach():
    for dag in random.choices(DATA_DAGS, k=4):
        yield {
            "short_description": f"SLA breach — {dag} not completed by 06:00 UTC",
            "description": f"DAG: {dag}\nSLA: 06:00 UTC\nStatus: Running/Queued\n\nPipeline missed SLA. Downstream Gold dashboards stale. Stakeholders notified.",
            "work_notes": "[Triage] DAG started late due to upstream sensor delay. ELZ 90 min behind. Pipeline running — ETA 08:30 UTC. Notified dashboard consumers.",
            "impact": "2", "urgency": "1", "category": "Software",
            "assignment_group_name": "Data Engineering",
        }


def generate_all_incidents(limit: int = 150) -> list[dict]:
    random.seed(42)
    generators = [
        sigterm_utility_dag, airflow_platform, downstream_dag_failures, utility_dag_exit_codes,
        scheduler_heartbeat, sensor_timeout, dag_import_errors, celery_worker_disconnected,
        connection_pool_exhausted, spark_executor_oom, spark_driver_oom, pod_eviction,
        aks_node_notready, elz_landing_delay, adls_throttling, hive_metastore_timeout, sla_breach,
    ]
    all_incidents = []
    for gen in generators:
        all_incidents.extend(gen())
    random.shuffle(all_incidents)
    return all_incidents[:limit]


def push_to_servicenow(incidents: list[dict], base_url: str, auth: tuple, total: int, group_lookup: dict, assignee_sys_id: str | None, skip_assignment: bool = False):
    created, failed = [], []
    for i, inc in enumerate(incidents, 1):
        payload = {
            "short_description": inc["short_description"],
            "description": inc["description"],
            "work_notes": inc.get("work_notes", ""),
            "impact": inc.get("impact", "2"),
            "urgency": inc.get("urgency", "2"),
            "category": inc.get("category", "Software"),
            "state": "1",
        }
        if not skip_assignment:
            grp_name = inc.get("assignment_group_name")
            if grp_name and grp_name in group_lookup:
                payload["assignment_group"] = group_lookup[grp_name]
            if assignee_sys_id and random.random() < 0.35:
                payload["assigned_to"] = assignee_sys_id
        try:
            result = _create_incident(base_url, auth, payload)
            created.append(result.get("number", "???"))
            print(f"  [{i:3d}/{total}] Created {result.get('number', '???')} — {inc['short_description'][:50]}...")
        except Exception as exc:
            failed.append((i, str(exc)))
            print(f"  [{i:3d}/{total}] FAILED — {exc}")
        if i % 10 == 0:
            time.sleep(1)
    print(f"\n{'='*60}\n  Done: {len(created)} created, {len(failed)} failed\n{'='*60}")
    if failed:
        print("\nFailed:")
        for idx, err in failed:
            print(f"  #{idx}: {err}")
    return created, failed


def main():
    parser = argparse.ArgumentParser(description="Seed SOP-aligned incidents to ServiceNow")
    parser.add_argument("--use-admin", action="store_true", help="Use admin credentials (for fresh PDI before incident.bot exists)")
    parser.add_argument("--count", type=int, default=150, help="Number of incidents to seed (default 150)")
    parser.add_argument("--no-verify", action="store_true", help="Skip pre-flight auth check")
    parser.add_argument("--delete-first", action="store_true", help="Delete all existing incidents before seeding")
    parser.add_argument("--no-assignment", action="store_true", help="Skip assignment_group and assigned_to (use if 403 on create)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    base_url, user, password = _get_auth(args.use_admin)
    if not base_url:
        print("Error: SERVICENOW_INSTANCE_URL not set in .env")
        sys.exit(1)
    if not password:
        print("Error: SERVICENOW_PASSWORD not set in .env (or SERVICENOW_ADMIN_PASSWORD when using --use-admin)")
        sys.exit(1)

    auth = (user, password)

    if not args.no_verify:
        print(f"Verifying connection to {base_url} as {user}...")
        if not _verify_connection(base_url, auth):
            print("\n" + "="*60)
            print("401 Unauthorized — Authentication failed.")
            print("="*60)
            print("\nPossible causes:")
            print("1. incident.bot user does not exist on this PDI.")
            print("   Run first: python create_incident_bot_user.py")
            print("2. To seed with admin credentials (e.g. before creating incident.bot):")
            print("   python seed_incidents_sop.py --use-admin")
            print("3. Wrong password or instance URL in .env")
            sys.exit(1)
        print("OK\n")

    incidents = generate_all_incidents(limit=args.count)
    print(f"Generated {len(incidents)} SOP-aligned incidents")
    print(f"  Instance: {base_url}")
    print(f"  User: {user}")

    if not args.yes:
        confirm = input("\nPush to ServiceNow? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    if args.delete_first:
        print("\nDeleting all existing incidents...")
        deleted = _delete_all_incidents(base_url, auth)
        print(f"  Deleted {deleted} incidents.\n")

    group_lookup = {}
    assignee_sys_id = None
    if not args.no_assignment:
        print("Ensuring assignment groups exist...")
        for name in ASSIGNMENT_GROUPS:
            sid = _get_or_create_group(base_url, auth, name)
            if sid:
                group_lookup[name] = sid
                print(f"  {name}: OK")
            else:
                print(f"  {name}: failed")
        if not group_lookup:
            print("  Warning: No assignment groups available.")
        assignee_sys_id = _get_user_sys_id(base_url, auth, os.getenv("SERVICENOW_USERNAME", "incident.bot"))
        if assignee_sys_id:
            print(f"  Assignee (incident.bot): OK")
        else:
            print(f"  Assignee: not found")
    else:
        print("Skipping assignment (--no-assignment)")

    print("\nCreating incidents...")
    push_to_servicenow(incidents, base_url, auth, len(incidents), group_lookup, assignee_sys_id, skip_assignment=args.no_assignment)


if __name__ == "__main__":
    main()

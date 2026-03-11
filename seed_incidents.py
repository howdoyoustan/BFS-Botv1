#!/usr/bin/env python3
"""
Seed 100 realistic BDP / Data Engineering incidents into ServiceNow PDI.

Tech stack context:
  - BDP (Batch Data Processing): open-source Spark framework
  - Deployed on Azure AKS (Kubernetes resource manager)
  - Orchestrated by Airflow
  - Hive tables → Azure Synapse views
  - PostgreSQL audit tables
  - Data layers: ELZ/Bronze → C360 Core → Gold → Dashboards

Usage:
    python seed_incidents.py
"""

import random
import time
import sys
from mcp.servicenow import ServiceNowClient

# ── Randomisation pools ─────────────────────────────────────────────

ENVS = ["c360-prod", "c360-nonprod", "c360-uat", "c360-dev"]
PROD_ENVS = ["c360-prod"]
NON_PROD_ENVS = ["c360-nonprod", "c360-uat", "c360-dev"]

FM_DAGS = [
    "c360-prod-fm-customer-profile",
    "c360-prod-fm-account-summary",
    "c360-prod-fm-transaction-ingest",
    "c360-prod-fm-party-master",
    "c360-prod-fm-product-catalog",
    "c360-nonprod-fm-customer-profile",
    "c360-nonprod-fm-transaction-ingest",
]
SM_DAGS = [
    "c360-prod-sm-risk-score",
    "c360-prod-sm-kyc-refresh",
    "c360-prod-sm-balance-agg",
    "c360-prod-sm-fraud-features",
    "c360-nonprod-sm-risk-score",
    "c360-nonprod-sm-kyc-refresh",
]
TM_DAGS = [
    "c360-prod-tm-gold-dashboard",
    "c360-prod-tm-reporting-agg",
    "c360-prod-tm-regulatory-extract",
    "c360-nonprod-tm-gold-dashboard",
]
BDP_DAGS = [
    "c360-prod-bdp-data-quality",
    "c360-prod-bdp-audit-reconciliation",
    "c360-prod-bdp-schema-validator",
    "c360-prod-bdp-lineage-tracker",
    "c360-nonprod-bdp-data-quality",
]
DATA_DAGS = [
    "c360-prod-dp-payments-ingestion",
    "c360-prod-dp-loans-transform",
    "c360-prod-dp-cards-enrichment",
    "c360-prod-dp-deposits-agg",
    "c360-prod-dp-mortgage-load",
    "c360-prod-dp-wealth-transform",
    "c360-prod-dp-insurance-claims",
    "c360-nonprod-dp-payments-ingestion",
    "c360-nonprod-dp-loans-transform",
    "c360-nonprod-dp-cards-enrichment",
]

ALL_DAGS = FM_DAGS + SM_DAGS + TM_DAGS + BDP_DAGS + DATA_DAGS

HIVE_TABLES = [
    "bronze.elz_customer_raw",
    "bronze.elz_transaction_raw",
    "bronze.elz_account_raw",
    "bronze.elz_party_raw",
    "bronze.elz_product_raw",
    "bronze.elz_payments_raw",
    "bronze.elz_loans_raw",
    "core.c360_customer_profile",
    "core.c360_account_summary",
    "core.c360_transaction_enriched",
    "core.c360_risk_features",
    "core.c360_kyc_master",
    "core.c360_fraud_signals",
    "core.c360_balance_snapshot",
    "gold.rpt_customer_360",
    "gold.rpt_risk_dashboard",
    "gold.rpt_regulatory_extract",
    "gold.rpt_product_performance",
    "gold.rpt_fraud_summary",
]

SYNAPSE_VIEWS = [
    "synapse.vw_customer_360",
    "synapse.vw_risk_dashboard",
    "synapse.vw_regulatory_report",
    "synapse.vw_product_performance",
    "synapse.vw_fraud_summary",
    "synapse.vw_balance_overview",
]

AKS_NODES = [
    "aks-bdppool-node01",
    "aks-bdppool-node02",
    "aks-bdppool-node03",
    "aks-sparkpool-node01",
    "aks-sparkpool-node02",
    "aks-airflowpool-node01",
    "aks-airflowpool-node02",
]

SPARK_APPS = [
    "bdp-spark-customer-ingest",
    "bdp-spark-transaction-transform",
    "bdp-spark-risk-calc",
    "bdp-spark-balance-agg",
    "bdp-spark-fraud-detection",
    "bdp-spark-kyc-refresh",
    "bdp-spark-gold-publish",
    "bdp-spark-payments-load",
    "bdp-spark-loans-enrich",
    "bdp-spark-cards-process",
]

EXIT_CODES = [1, 2, 126, 127, 137, 139, 143]


def _r(lst):
    return random.choice(lst)


# ── Incident generators ─────────────────────────────────────────────
# Each returns a dict with: short_description, description, work_notes,
# impact, urgency, category

def airflow_incidents():
    """~25 Airflow / orchestration incidents."""
    incidents = []

    # Utility DAG SIGTERM (6)
    for dag in random.sample(FM_DAGS + SM_DAGS + TM_DAGS, 6):
        env = "Production" if "prod-" in dag and "nonprod" not in dag else "Non-Production"
        incidents.append({
            "short_description": f"Airflow DAG {dag} — Task received SIGTERM signal",
            "description": (
                f"DAG: {dag}\nEnvironment: {env}\n\n"
                f"The task received a SIGTERM signal during execution. "
                f"Airflow logs show 'AirflowTaskTerminated' at the task instance level. "
                f"This is likely caused by pod eviction or Airflow worker restart on AKS. "
                f"Downstream tasks in the DAG are blocked."
            ),
            "work_notes": (
                f"[Triage] Identified SIGTERM on {dag}. Checking Airflow worker pod status on AKS. "
                f"Worker pod was OOMKilled — Kubernetes evicted the pod due to memory pressure on {_r(AKS_NODES)}. "
                f"Escalating to BDP team for platform health check."
            ),
            "impact": "2", "urgency": "1" if env == "Production" else "2",
            "category": "Software",
        })

    # Utility DAG failures with exit codes (5)
    for _ in range(5):
        dag = _r(BDP_DAGS + FM_DAGS)
        code = _r(EXIT_CODES)
        incidents.append({
            "short_description": f"Utility DAG {dag} failed with exit code {code}",
            "description": (
                f"DAG: {dag}\nExit Code: {code}\n\n"
                f"The BDP utility DAG failed during the scheduled run. "
                f"Task log indicates a non-zero exit code. "
                f"This may indicate an infrastructure issue (exit code {code}) "
                f"or a data validation failure in the utility pipeline."
            ),
            "work_notes": (
                f"[Triage] Exit code {code} on {dag}. "
                f"{'Code 137 = OOMKilled. Checking K8s resource limits.' if code == 137 else ''}"
                f"{'Code 143 = SIGTERM. Checking for pod eviction.' if code == 143 else ''}"
                f"{'Non-OOM exit. Reviewing task logs for root cause.' if code not in (137, 143) else ''}"
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Airflow scheduler heartbeat lost (2)
    for env in random.sample(ENVS, 2):
        incidents.append({
            "short_description": f"Airflow scheduler heartbeat lost — {env}",
            "description": (
                f"Environment: {env}\n\n"
                f"Airflow scheduler has not sent a heartbeat for over 5 minutes. "
                f"No new tasks are being scheduled. DAG runs are accumulating in the 'queued' state. "
                f"All pipelines in the {env} environment are stalled."
            ),
            "work_notes": (
                f"[Triage] Scheduler pod on {_r(AKS_NODES)} is in CrashLoopBackOff. "
                f"Airflow metadata DB (PostgreSQL) connection pool may be exhausted. "
                f"Restarting scheduler pod and checking pg_stat_activity."
            ),
            "impact": "1", "urgency": "1",
            "category": "Software",
        })

    # DAG import errors (3)
    for dag in random.sample(DATA_DAGS, 3):
        incidents.append({
            "short_description": f"DAG import error — {dag} not visible in Airflow UI",
            "description": (
                f"DAG: {dag}\n\n"
                f"The DAG is no longer visible in the Airflow UI. "
                f"The scheduler log shows a Python import error or syntax error in the DAG file. "
                f"This is blocking the scheduled pipeline run."
            ),
            "work_notes": (
                f"[Triage] DAG file has a syntax error introduced in the last deployment. "
                f"Git commit SHA identified. Notifying the pipeline owner to fix and redeploy."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Sensor timeout (3)
    for dag in random.sample(DATA_DAGS, 3):
        table = _r(HIVE_TABLES[:7])
        incidents.append({
            "short_description": f"Sensor timeout in {dag} waiting for {table}",
            "description": (
                f"DAG: {dag}\nBlocked Sensor: ExternalTaskSensor / HivePartitionSensor\n\n"
                f"The sensor task has been in 'up_for_reschedule' state for over 2 hours, "
                f"waiting for upstream table {table} to land in the ELZ/Bronze layer. "
                f"The upstream source system may be delayed."
            ),
            "work_notes": (
                f"[Triage] Upstream feed for {table} has not arrived. "
                f"Checking source system status and ELZ landing zone. "
                f"SLA for this feed is T+2h — currently at T+3h. Escalating to source team."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Celery worker disconnected (2)
    for node in random.sample(AKS_NODES[:4], 2):
        incidents.append({
            "short_description": f"Airflow Celery worker disconnected on {node}",
            "description": (
                f"Node: {node}\n\n"
                f"Celery worker on {node} has disconnected from the message broker. "
                f"Tasks assigned to this worker are stuck in 'queued' state. "
                f"Flower dashboard shows the worker as offline."
            ),
            "work_notes": (
                f"[Triage] Worker pod on {node} was evicted due to ephemeral storage pressure. "
                f"Airflow logs directory exceeded pod storage limit. "
                f"Cleaning up old logs and restarting the worker pod."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Connection pool exhaustion (2)
    for env in random.sample(ENVS[:2], 2):
        incidents.append({
            "short_description": f"Airflow DB connection pool exhausted — {env}",
            "description": (
                f"Environment: {env}\n\n"
                f"Airflow metadata database (PostgreSQL) connection pool is exhausted. "
                f"Tasks are failing with 'QueuePool limit of 5 overflow 10 reached'. "
                f"Multiple DAGs are affected across all pipelines in {env}."
            ),
            "work_notes": (
                f"[Triage] pg_stat_activity shows 120 active connections. "
                f"Max connections set to 100. Idle connections from crashed workers not released. "
                f"Running pg_terminate_backend on idle-in-transaction sessions. "
                f"Recommending increase of max_connections and pgbouncer review."
            ),
            "impact": "1", "urgency": "1",
            "category": "Database",
        })

    # SLA miss (2)
    for dag in random.sample(DATA_DAGS[:5], 2):
        incidents.append({
            "short_description": f"SLA breach — {dag} not completed by 06:00 UTC",
            "description": (
                f"DAG: {dag}\nSLA Deadline: 06:00 UTC\nCurrent Status: Running / Queued\n\n"
                f"The pipeline has missed its SLA. Downstream dashboards on the Gold layer "
                f"are showing stale data. Business stakeholders have been notified."
            ),
            "work_notes": (
                f"[Triage] DAG started late due to upstream sensor delay. "
                f"ELZ landing was 90 minutes behind schedule. "
                f"Pipeline is now running — ETA for completion is 08:30 UTC. "
                f"Notified dashboard consumers of delayed refresh."
            ),
            "impact": "2", "urgency": "1",
            "category": "Software",
        })

    return incidents


def spark_bdp_incidents():
    """~25 Spark / BDP execution incidents."""
    incidents = []

    # Executor OOM (5)
    for app in random.sample(SPARK_APPS, 5):
        mem = _r(["4g", "8g", "16g"])
        incidents.append({
            "short_description": f"Spark executor OOM — {app}",
            "description": (
                f"Application: {app}\nExecutor Memory: {mem}\n\n"
                f"Spark executor ran out of memory during shuffle/aggregation phase. "
                f"Error: java.lang.OutOfMemoryError: GC overhead limit exceeded. "
                f"The BDP job failed and the Airflow task was marked as FAILED."
            ),
            "work_notes": (
                f"[Triage] Executor memory set to {mem}. Shuffle spill to disk is at 95%. "
                f"Partition count is too low for the data volume — causing large partitions. "
                f"Recommending repartition(200) and increasing executor memory to "
                f"{'16g' if mem == '8g' else '32g'}."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Driver OOM (3)
    for app in random.sample(SPARK_APPS, 3):
        incidents.append({
            "short_description": f"Spark driver OOM during collect/broadcast — {app}",
            "description": (
                f"Application: {app}\n\n"
                f"Spark driver crashed with OutOfMemoryError during a collect() or broadcast join. "
                f"A large dataset was being pulled to the driver node. "
                f"The BDP job terminated and the Airflow task failed with exit code 137."
            ),
            "work_notes": (
                f"[Triage] Driver memory is 4g. The job is doing a broadcast join on a table "
                f"that grew beyond the auto-broadcast threshold. "
                f"Disabling broadcast and switching to sort-merge join. "
                f"Also increasing driver memory to 8g as a safeguard."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Shuffle failures (3)
    for app in random.sample(SPARK_APPS, 3):
        node = _r(AKS_NODES)
        incidents.append({
            "short_description": f"Spark FetchFailedException — shuffle service on {node}",
            "description": (
                f"Application: {app}\nFailed Node: {node}\n\n"
                f"org.apache.spark.shuffle.FetchFailedException: Failed to connect to {node}. "
                f"The external shuffle service on the node is not responding. "
                f"Multiple executors lost, causing stage retry exhaustion."
            ),
            "work_notes": (
                f"[Triage] Node {node} had a transient network issue. "
                f"AKS node was under memory pressure and the shuffle service pod was evicted. "
                f"Node has recovered. Retriggering the BDP job."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Stage failure / data skew (3)
    for app in random.sample(SPARK_APPS, 3):
        table = _r(HIVE_TABLES)
        incidents.append({
            "short_description": f"Spark stage failure — data skew on {table}",
            "description": (
                f"Application: {app}\nTable: {table}\n\n"
                f"Spark job failed due to a skewed partition during a join operation. "
                f"One executor processed 95% of the data while others were idle. "
                f"Task exceeded the 4-hour timeout and was killed by Kubernetes."
            ),
            "work_notes": (
                f"[Triage] Key distribution analysis shows that customer_id='UNKNOWN' accounts for "
                f"40% of records in {table}. Recommending salted join or filtering null keys before join."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Checkpoint failure (2)
    for app in random.sample(SPARK_APPS, 2):
        incidents.append({
            "short_description": f"Spark checkpoint write failed — ADLS permission denied — {app}",
            "description": (
                f"Application: {app}\n\n"
                f"Spark streaming/batch checkpoint write to ADLS Gen2 failed with "
                f"'StatusCode=403 Forbidden'. The managed identity on the AKS pod does not "
                f"have write access to the checkpoint container."
            ),
            "work_notes": (
                f"[Triage] ADLS checkpoint container 'bdp-checkpoints' has a stale RBAC assignment. "
                f"The AKS managed identity was rotated last week but RBAC was not updated. "
                f"Requesting IAM team to re-grant Storage Blob Data Contributor role."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Serialization error (2)
    for app in random.sample(SPARK_APPS, 2):
        incidents.append({
            "short_description": f"Spark serialization error — {app} — NotSerializableException",
            "description": (
                f"Application: {app}\n\n"
                f"org.apache.spark.SparkException: Task not serializable. "
                f"A non-serializable object is being referenced inside a closure. "
                f"The BDP job fails immediately at the first stage."
            ),
            "work_notes": (
                f"[Triage] Code change in last deployment introduced a reference to a "
                f"database connection object inside a map() closure. "
                f"Notifying pipeline developer to fix serialization issue."
            ),
            "impact": "3", "urgency": "2",
            "category": "Software",
        })

    # K8s executor pod pending (3)
    for app in random.sample(SPARK_APPS, 3):
        incidents.append({
            "short_description": f"Spark executors stuck in Pending — insufficient AKS capacity — {app}",
            "description": (
                f"Application: {app}\n\n"
                f"Spark executor pods are in 'Pending' state on AKS. "
                f"Kubernetes cannot schedule pods due to insufficient CPU/memory on the spark node pool. "
                f"The BDP job is hanging with 0 active executors."
            ),
            "work_notes": (
                f"[Triage] AKS spark pool at capacity — all 3 nodes fully allocated. "
                f"Multiple BDP jobs running concurrently. "
                f"Requesting AKS autoscaler review and temporary node scale-up to 5 nodes."
            ),
            "impact": "2", "urgency": "1",
            "category": "Software",
        })

    # Hive metastore timeout from Spark (2)
    for app in random.sample(SPARK_APPS, 2):
        table = _r(HIVE_TABLES)
        incidents.append({
            "short_description": f"Spark job failed — Hive metastore timeout reading {table}",
            "description": (
                f"Application: {app}\nTable: {table}\n\n"
                f"Spark job failed with 'MetaException: Hive metastore connection timed out'. "
                f"The Hive metastore service is slow or unresponsive. "
                f"This is blocking all BDP jobs that read/write Hive tables."
            ),
            "work_notes": (
                f"[Triage] Hive metastore pod on AKS is healthy but slow. "
                f"PostgreSQL backend for metastore has high CPU due to full table scan on TBLS. "
                f"Running VACUUM ANALYZE on metastore DB. Restarting metastore pod."
            ),
            "impact": "1", "urgency": "1",
            "category": "Database",
        })

    # BDP framework version mismatch (2)
    for app in random.sample(SPARK_APPS, 2):
        incidents.append({
            "short_description": f"BDP framework version mismatch — {app} using stale JAR",
            "description": (
                f"Application: {app}\n\n"
                f"The BDP Spark job is running with an outdated framework JAR (v2.3.1) "
                f"while the cluster has been upgraded to v2.4.0. "
                f"This causes NoSuchMethodError at runtime during transformation phase."
            ),
            "work_notes": (
                f"[Triage] The Docker image for this pipeline was not rebuilt after the "
                f"BDP framework upgrade. Triggering CI/CD pipeline to rebuild with latest JAR. "
                f"Adding version check to BDP bootstrap script to prevent recurrence."
            ),
            "impact": "3", "urgency": "2",
            "category": "Software",
        })

    return incidents


def data_pipeline_incidents():
    """~25 data pipeline / layer incidents."""
    incidents = []

    # ELZ/Bronze landing delay (4)
    for table in random.sample(HIVE_TABLES[:7], 4):
        source = _r(["payments-upstream", "core-banking", "cards-system", "loans-origination", "party-master-feed"])
        incidents.append({
            "short_description": f"ELZ landing delay — {table} — source: {source}",
            "description": (
                f"Table: {table}\nSource System: {source}\n\n"
                f"Data for {table} has not landed in the Enterprise Landing Zone (Bronze layer) "
                f"within the expected SLA window. The source system {source} may be delayed "
                f"or the file transfer job may have failed. Downstream C360 Core pipelines are blocked."
            ),
            "work_notes": (
                f"[Triage] Checked ADLS landing container — no files for today's partition. "
                f"Source system {source} confirmed a batch job delay on their side. "
                f"ETA for file delivery: 2 hours. Notifying downstream pipeline owners."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Schema drift / mismatch (4)
    for table in random.sample(HIVE_TABLES[:7], 4):
        incidents.append({
            "short_description": f"Schema mismatch detected — {table} — new column in source",
            "description": (
                f"Table: {table}\n\n"
                f"BDP schema validator detected a schema mismatch between the incoming file "
                f"and the registered Hive table schema. A new column was added by the source "
                f"system without notification. The ingestion pipeline has been halted to prevent data corruption."
            ),
            "work_notes": (
                f"[Triage] New column 'risk_tier_v2' found in source file but not in Hive DDL. "
                f"BDP schema evolution policy requires manual approval for additive changes. "
                f"Creating Jira ticket for schema review. Pipeline paused until approved."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # C360 Core transformation failure (4)
    for table in random.sample(HIVE_TABLES[7:14], 4):
        incidents.append({
            "short_description": f"C360 Core transformation failed — {table}",
            "description": (
                f"Table: {table}\nLayer: C360 Core\n\n"
                f"The transformation job for {table} failed during the join/enrichment phase. "
                f"The Spark job encountered a data quality issue — null keys in the join column "
                f"caused unexpected row explosion. Output row count exceeded threshold by 300%."
            ),
            "work_notes": (
                f"[Triage] Row count check fired: expected ~5M rows, got ~20M. "
                f"Root cause: Bronze table has NULL customer_id for ~15% of records after "
                f"upstream system migration. Adding NULL filter to transformation SQL. "
                f"Notifying source team about data quality regression."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Gold layer publish failure (3)
    for table in random.sample(HIVE_TABLES[14:], 3):
        incidents.append({
            "short_description": f"Gold layer publish failed — {table} — partition overwrite error",
            "description": (
                f"Table: {table}\nLayer: Gold\n\n"
                f"The Gold layer publish job failed with 'Cannot overwrite partition — "
                f"concurrent write detected'. Another job was writing to the same partition. "
                f"Dashboard data is stale."
            ),
            "work_notes": (
                f"[Triage] Two DAGs attempted to write to the same Gold partition simultaneously. "
                f"Schedule overlap between reporting-agg and regulatory-extract. "
                f"Adjusting DAG schedule to add 30-minute buffer. Retriggering failed job."
            ),
            "impact": "2", "urgency": "1",
            "category": "Software",
        })

    # Data quality check failure (3)
    for dag in random.sample(BDP_DAGS[:3], 2) + [_r(DATA_DAGS)]:
        table = _r(HIVE_TABLES)
        incidents.append({
            "short_description": f"Data quality check failed — {table} — null rate above threshold",
            "description": (
                f"DAG: {dag}\nTable: {table}\n\n"
                f"BDP data quality framework detected that the null rate for column "
                f"'account_number' in {table} is 12.4%, exceeding the 5% threshold. "
                f"The pipeline has been halted to prevent bad data from propagating to Gold layer."
            ),
            "work_notes": (
                f"[Triage] Source system had a partial load — only 60% of expected records arrived. "
                f"Missing records have NULL account_number. "
                f"Waiting for source system to deliver the remaining batch. "
                f"Will retrigger pipeline after full file lands."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Duplicate records (2)
    for table in random.sample(HIVE_TABLES[7:14], 2):
        incidents.append({
            "short_description": f"Duplicate records detected in {table} after incremental load",
            "description": (
                f"Table: {table}\nLayer: C360 Core\n\n"
                f"Post-load validation detected duplicate primary keys in {table}. "
                f"The incremental merge (SCD Type 1) did not correctly deduplicate records. "
                f"Downstream Gold aggregations will produce inflated metrics."
            ),
            "work_notes": (
                f"[Triage] The dedup window filter used processing_date instead of event_date. "
                f"Late-arriving records from yesterday were not caught. "
                f"Fixing the merge condition and running a full reconciliation on {table}."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # SCD merge failure (2)
    for table in random.sample(HIVE_TABLES[7:14], 2):
        incidents.append({
            "short_description": f"SCD Type 2 merge failed — {table} — conflicting effective dates",
            "description": (
                f"Table: {table}\n\n"
                f"The Slowly Changing Dimension merge for {table} failed. "
                f"Conflicting effective_from dates found for the same surrogate key. "
                f"The BDP SCD framework aborted to prevent history corruption."
            ),
            "work_notes": (
                f"[Triage] Source system sent two updates for the same customer within the same "
                f"batch with different timestamps. BDP SCD framework does not handle intra-batch conflicts. "
                f"Deduplicating source batch by taking latest record per key. Retriggering."
            ),
            "impact": "3", "urgency": "2",
            "category": "Software",
        })

    # Synapse view out of sync (3)
    for view in random.sample(SYNAPSE_VIEWS, 3):
        incidents.append({
            "short_description": f"Synapse view stale — {view} not reflecting latest Gold data",
            "description": (
                f"View: {view}\nLayer: Gold → Synapse\n\n"
                f"Azure Synapse external table / view {view} is returning data from yesterday. "
                f"The Gold layer Hive table has been updated but the Synapse metadata cache "
                f"has not refreshed. Dashboard consumers are seeing stale data."
            ),
            "work_notes": (
                f"[Triage] Synapse external table metadata needs a manual refresh after "
                f"Gold layer partition overwrite. Running 'DBCC DROPRESULTSETCACHE'. "
                f"Adding Synapse refresh step to the Gold publish DAG to prevent recurrence."
            ),
            "impact": "2", "urgency": "1",
            "category": "Database",
        })

    return incidents


def infrastructure_incidents():
    """~15 infrastructure & platform incidents."""
    incidents = []

    # AKS node NotReady (3)
    for node in random.sample(AKS_NODES, 3):
        incidents.append({
            "short_description": f"AKS node {node} in NotReady state — pods being evicted",
            "description": (
                f"Node: {node}\n\n"
                f"Kubernetes node {node} has transitioned to NotReady state. "
                f"All pods on this node are being evicted. This includes Airflow worker pods "
                f"and Spark executor pods. Multiple pipelines affected."
            ),
            "work_notes": (
                f"[Triage] Azure VM underlying {node} had a hardware issue. "
                f"AKS cluster autoscaler is provisioning a replacement node. "
                f"ETA for new node: ~5 minutes. Affected pods will be rescheduled automatically. "
                f"Monitoring DAG runs for automatic recovery."
            ),
            "impact": "1", "urgency": "1",
            "category": "Software",
        })

    # Pod eviction — memory pressure (2)
    for node in random.sample(AKS_NODES, 2):
        pod = _r(["airflow-worker-0", "airflow-worker-1", "spark-driver-bdp", "hive-metastore-0"])
        incidents.append({
            "short_description": f"Pod evicted — memory pressure on {node} — {pod}",
            "description": (
                f"Node: {node}\nPod: {pod}\n\n"
                f"Kubernetes evicted pod {pod} due to memory pressure on node {node}. "
                f"Node memory utilisation was at 98%. "
                f"This caused task failures in Airflow and Spark job interruptions."
            ),
            "work_notes": (
                f"[Triage] Multiple large BDP jobs running concurrently saturated node memory. "
                f"Pod resource requests are too low — allowing over-commitment. "
                f"Increasing pod memory requests and setting PodDisruptionBudget for critical pods."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # PostgreSQL audit table failure (3)
    pg_errors = [
        ("connection refused", "PostgreSQL service on audit DB is down. Connection refused on port 5432."),
        ("disk full", "PostgreSQL audit database disk is 99% full. Write operations are failing."),
        ("deadlock detected", "Concurrent BDP audit writes caused a deadlock in the audit_log table."),
    ]
    for error_type, detail in pg_errors:
        incidents.append({
            "short_description": f"PostgreSQL audit DB — {error_type}",
            "description": (
                f"Database: bdp-audit-postgres\nError: {error_type}\n\n"
                f"{detail} "
                f"BDP audit trail writes are failing. Pipeline execution continues but "
                f"audit records are being lost. Compliance requirement at risk."
            ),
            "work_notes": (
                f"[Triage] {'Restarting PostgreSQL pod on AKS.' if error_type == 'connection refused' else ''}"
                f"{'Running VACUUM FULL and archiving old audit records to cold storage.' if error_type == 'disk full' else ''}"
                f"{'Adjusting isolation level and adding retry logic to audit writer.' if error_type == 'deadlock detected' else ''}"
            ),
            "impact": "2", "urgency": "2",
            "category": "Database",
        })

    # ADLS storage throttling (2)
    for container in ["bdp-bronze-landing", "bdp-gold-publish"]:
        incidents.append({
            "short_description": f"ADLS Gen2 throttling — {container} — HTTP 429",
            "description": (
                f"Storage Container: {container}\n\n"
                f"Azure Data Lake Storage Gen2 is returning HTTP 429 (Too Many Requests) "
                f"for read/write operations on container {container}. "
                f"Multiple BDP Spark jobs are hitting the storage account concurrently. "
                f"Jobs are retrying but some are timing out."
            ),
            "work_notes": (
                f"[Triage] Storage account is hitting per-account IOPS limit. "
                f"30+ Spark jobs running in parallel during the morning batch window. "
                f"Requesting Azure support to increase throughput limits. "
                f"Short-term: staggering job schedules to reduce concurrency."
            ),
            "impact": "2", "urgency": "1",
            "category": "Software",
        })

    # Hive metastore crash (1)
    incidents.append({
        "short_description": "Hive metastore pod CrashLoopBackOff — all BDP jobs blocked",
        "description": (
            "Component: Hive Metastore\nPod: hive-metastore-0\n\n"
            "The Hive metastore pod is in CrashLoopBackOff on AKS. "
            "All BDP Spark jobs that interact with Hive tables (read or write) are failing "
            "with 'MetaException: Could not connect to metastore'. "
            "This is a P1 blocking all data processing."
        ),
        "work_notes": (
            "[Triage] Metastore JVM is crashing with heap exhaustion. "
            "Recent schema change added 500 new partitions to gold.rpt_customer_360, "
            "causing metastore to OOM during startup partition scan. "
            "Increasing metastore heap from 2g to 4g and restarting."
        ),
        "impact": "1", "urgency": "1",
        "category": "Database",
    })

    # Network policy blocking (1)
    incidents.append({
        "short_description": "AKS network policy blocking Spark executor ↔ driver communication",
        "description": (
            "Component: AKS NetworkPolicy\n\n"
            "A recently applied Kubernetes NetworkPolicy is blocking TCP traffic "
            "between Spark executor pods and the driver pod. "
            "Executors cannot register with the driver, causing all BDP jobs to hang. "
            "The policy was applied as part of a security hardening initiative."
        ),
        "work_notes": (
            "[Triage] New NetworkPolicy 'deny-all-ingress' applied to spark namespace. "
            "This blocks Spark's internal RPC ports (7078-7079). "
            "Adding exception rule for spark-driver ↔ spark-executor communication. "
            "Rolling back policy until fix is validated."
        ),
        "impact": "1", "urgency": "1",
        "category": "Network",
    })

    # Certificate expiry (1)
    incidents.append({
        "short_description": "TLS certificate expired — Airflow webserver returning 502",
        "description": (
            "Component: Airflow Webserver\n\n"
            "The TLS certificate for the Airflow UI has expired. "
            "Users cannot access the Airflow webserver — Azure Application Gateway "
            "is returning HTTP 502. DAG management and monitoring are impacted. "
            "Scheduled DAG runs are unaffected but manual intervention is not possible."
        ),
        "work_notes": (
            "[Triage] Certificate issued by internal CA expired 2 days ago. "
            "Cert renewal was not automated. Requesting new certificate from security team. "
            "As a workaround, enabling direct pod port-forward for urgent DAG operations."
        ),
        "impact": "3", "urgency": "2",
        "category": "Network",
    })

    # DNS resolution failure (1)
    incidents.append({
        "short_description": "DNS resolution failure — Spark jobs cannot reach Hive metastore",
        "description": (
            "Component: AKS CoreDNS\n\n"
            "CoreDNS pods in the AKS cluster are intermittently failing to resolve "
            "internal service names. Spark jobs are failing with "
            "'UnknownHostException: hive-metastore.bdp.svc.cluster.local'. "
            "This is affecting all BDP jobs across all environments."
        ),
        "work_notes": (
            "[Triage] CoreDNS pods are throttled due to high query volume. "
            "BDP Spark jobs generate ~10k DNS queries/minute during peak. "
            "Scaling CoreDNS replicas from 2 to 5 and enabling DNS caching on nodes."
        ),
        "impact": "1", "urgency": "1",
        "category": "Network",
    })

    return incidents


def schedule_incidents():
    """~10 schedule & dependency chain incidents."""
    incidents = []

    # Cron schedule misfire (2)
    for dag in random.sample(DATA_DAGS, 2):
        incidents.append({
            "short_description": f"DAG {dag} did not trigger at scheduled time",
            "description": (
                f"DAG: {dag}\nSchedule: Daily at 02:00 UTC\n\n"
                f"The DAG did not trigger at its scheduled time. "
                f"The Airflow scheduler processed the DAG but the next execution date "
                f"was calculated incorrectly after a recent schedule change. "
                f"The DAG is showing as 'No runs' for today."
            ),
            "work_notes": (
                f"[Triage] DAG schedule was changed from '0 2 * * *' to '0 3 * * *' "
                f"but the catchup parameter was set to False. Airflow skipped today's run. "
                f"Manually triggering the DAG and correcting the schedule_interval."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Dependency chain failure (3)
    deps = [
        ("c360-prod-dp-payments-ingestion", "c360-prod-sm-fraud-features", "bronze.elz_payments_raw"),
        ("c360-prod-fm-customer-profile", "c360-prod-dp-loans-transform", "core.c360_customer_profile"),
        ("c360-prod-sm-balance-agg", "c360-prod-tm-gold-dashboard", "core.c360_balance_snapshot"),
    ]
    for upstream, downstream, table in deps:
        incidents.append({
            "short_description": f"Dependency chain broken — {downstream} blocked by {upstream}",
            "description": (
                f"Upstream DAG: {upstream}\nDownstream DAG: {downstream}\nBlocked Table: {table}\n\n"
                f"The downstream pipeline {downstream} cannot proceed because the upstream "
                f"pipeline {upstream} has not completed. The ExternalTaskSensor is in "
                f"'up_for_reschedule' state. The blocking table {table} has stale data."
            ),
            "work_notes": (
                f"[Triage] Upstream DAG {upstream} failed 3 hours ago due to a data quality issue. "
                f"The upstream issue is being worked on separately (see linked incident). "
                f"Downstream {downstream} will auto-resume once upstream completes. "
                f"No manual action needed on downstream."
            ),
            "impact": "2", "urgency": "2",
            "category": "Software",
        })

    # Backfill contention (2)
    for dag in random.sample(DATA_DAGS[:5], 2):
        incidents.append({
            "short_description": f"Backfill job for {dag} causing resource contention",
            "description": (
                f"DAG: {dag}\n\n"
                f"A backfill was triggered for {dag} covering the last 7 days. "
                f"This spawned 7 concurrent DAG runs, each launching Spark jobs on AKS. "
                f"The cluster is overloaded and regular daily pipelines are starved of resources."
            ),
            "work_notes": (
                f"[Triage] Backfill triggered without concurrency limit. "
                f"7 Spark applications competing for 3-node pool. "
                f"Pausing backfill and setting max_active_runs=2 for this DAG. "
                f"Will resume backfill in off-peak hours (18:00-06:00 UTC)."
            ),
            "impact": "2", "urgency": "1",
            "category": "Software",
        })

    # Timezone misconfiguration (1)
    incidents.append({
        "short_description": "DAG schedule timezone mismatch — pipelines running 1 hour early after DST",
        "description": (
            "Component: Airflow Scheduler\n\n"
            "After the Daylight Saving Time transition, multiple DAGs are triggering "
            "1 hour earlier than expected. The Airflow scheduler timezone is set to UTC "
            "but the DAG schedules were written assuming local time (Europe/London). "
            "Upstream source systems have not delivered data yet when pipelines start."
        ),
        "work_notes": (
            "[Triage] 12 DAGs affected. All have schedule_interval using cron expressions "
            "that assume BST but Airflow runs in UTC. "
            "Standardizing all DAG schedules to explicit UTC times. "
            "Adding timezone-aware schedule documentation to BDP DAG template."
        ),
        "impact": "2", "urgency": "2",
        "category": "Software",
    })

    # DAG concurrency limit hit (2)
    for dag in random.sample(DATA_DAGS, 2):
        incidents.append({
            "short_description": f"DAG {dag} — max_active_tasks limit reached — tasks queued",
            "description": (
                f"DAG: {dag}\n\n"
                f"The DAG has hit its max_active_tasks limit (16). "
                f"New tasks are stuck in 'queued' state. The DAG has 50+ tasks and "
                f"parallelism is limited by the Airflow pool configuration. "
                f"Pipeline runtime has increased from 45 minutes to 3+ hours."
            ),
            "work_notes": (
                f"[Triage] DAG task count grew after adding new transformation steps. "
                f"Default pool size is 128 but this DAG's pool 'bdp_spark' is set to 16. "
                f"Increasing pool size to 32 and reviewing task grouping for optimization."
            ),
            "impact": "3", "urgency": "2",
            "category": "Software",
        })

    return incidents


# ── Main ─────────────────────────────────────────────────────────────

def generate_all_incidents() -> list[dict]:
    random.seed(42)
    all_incidents = []
    all_incidents.extend(airflow_incidents())
    all_incidents.extend(spark_bdp_incidents())
    all_incidents.extend(data_pipeline_incidents())
    all_incidents.extend(infrastructure_incidents())
    all_incidents.extend(schedule_incidents())

    random.shuffle(all_incidents)
    return all_incidents[:100]


# Assignment groups for triage queries (e.g. "Find incidents assigned to Software team")
# Maps category -> group name for lookup. Groups must exist in ServiceNow (create via seed_incidents_sop or manually).
CATEGORY_TO_GROUP = {
    "Software": "Software",
    "Database": "Data Engineering",
    "Network": "Infrastructure",
}


def push_to_servicenow(incidents: list[dict]):
    client = ServiceNowClient()
    created = []
    failed = []

    # Build group lookup so "Find incidents assigned to Software team" returns results
    # Creates groups if they don't exist (requires admin/write on sys_user_group)
    group_lookup = {}
    for grp_name in ["Software", "Data Engineering", "Infrastructure", "Network"]:
        try:
            sid = client.get_or_create_group(grp_name)
            if sid:
                group_lookup[grp_name] = sid
        except Exception:
            pass
    if group_lookup:
        print(f"  Assignment groups: {list(group_lookup.keys())}")

    print(f"\nPushing {len(incidents)} incidents to ServiceNow...\n")

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

        # Assign to group so "assigned to Software team" etc. returns results
        grp_name = inc.get("assignment_group_name") or CATEGORY_TO_GROUP.get(inc.get("category", "Software"))
        if grp_name and grp_name in group_lookup:
            payload["assignment_group"] = group_lookup[grp_name]

        try:
            result = client.create_incident(payload)
            number = result.get("number", "???")
            created.append(number)
            print(f"  [{i:3d}/100] Created {number} — {inc['short_description'][:60]}")
        except Exception as exc:
            failed.append((i, str(exc)))
            print(f"  [{i:3d}/100] FAILED — {exc}")

        if i % 10 == 0:
            time.sleep(1)

    print(f"\n{'='*60}")
    print(f"  Done: {len(created)} created, {len(failed)} failed")
    print(f"{'='*60}")

    if failed:
        print("\nFailed incidents:")
        for idx, err in failed:
            print(f"  #{idx}: {err}")

    return created, failed


if __name__ == "__main__":
    incidents = generate_all_incidents()
    print(f"Generated {len(incidents)} incidents")
    print(f"  Airflow/Orchestration, Spark/BDP, Data Pipeline, Infrastructure, Schedule")
    print(f"  Categories: Software, Database, Network")

    confirm = input("\nPush to ServiceNow? (y/n): ").strip().lower()
    if confirm == "y":
        push_to_servicenow(incidents)
    else:
        print("Aborted.")
        for i, inc in enumerate(incidents[:5], 1):
            print(f"\n--- Sample {i} ---")
            print(f"  Title: {inc['short_description']}")
            print(f"  Impact: {inc['impact']} | Urgency: {inc['urgency']} | Category: {inc['category']}")

SOP_KEYWORDS = ["how to", "procedure", "sop", "runbook", "onboarding"]

TROUBLE_KEYWORDS = [
    "error", "failed", "permission denied",
    "no space left", "command not found"
]

DATA_ENGINEERING_KEYWORDS = [
    "spark", "airflow", "dag", "sql", "pipeline",
    "etl", "table", "schema", "lineage"
]

def classify_intent_rule_based(query: str) -> str:
    q = query.lower()

    # 1. DATA ENGINEERING FIRST (most specific)
    if any(k in q for k in DATA_ENGINEERING_KEYWORDS):
        return "DATA_ENGINEERING"

    # 2. SOP queries
    if any(k in q for k in SOP_KEYWORDS):
        return "SOP_QUERY"

    # 3. Generic troubleshooting (catch-all)
    if any(k in q for k in TROUBLE_KEYWORDS):
        return "TROUBLESHOOTING"

    return "AMBIGUOUS"


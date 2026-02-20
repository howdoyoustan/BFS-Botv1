import re

SOP_KEYWORDS = ["how to", "procedure", "sop", "runbook", "onboarding"]

TROUBLE_KEYWORDS = [
    "error", "failed", "permission denied",
    "no space left", "command not found"
]

DATA_ENGINEERING_KEYWORDS = [
    "spark", "airflow", "dag", "sql", "pipeline",
    "etl", "table", "schema", "lineage"
]

SERVICENOW_KEYWORDS = [
    "incident", "servicenow", "service now", "snow",
    "ticket", "work notes", "worknotes",
    "assignment group", "open incidents", "resolved incidents",
    "closed incidents",
]

INC_NUMBER_PATTERN = re.compile(r"INC\d{4,10}", re.IGNORECASE)

def classify_intent_rule_based(query: str) -> str:
    q = query.lower()

    # 1. SERVICENOW — explicit INC number is unambiguous
    if INC_NUMBER_PATTERN.search(query):
        return "SERVICENOW_INCIDENT"

    # 2. SERVICENOW — keyword match
    if any(k in q for k in SERVICENOW_KEYWORDS):
        return "SERVICENOW_INCIDENT"

    # 3. DATA ENGINEERING (most specific domain terms)
    if any(k in q for k in DATA_ENGINEERING_KEYWORDS):
        return "DATA_ENGINEERING"

    # 4. SOP queries
    if any(k in q for k in SOP_KEYWORDS):
        return "SOP_QUERY"

    # 5. Generic troubleshooting (catch-all)
    if any(k in q for k in TROUBLE_KEYWORDS):
        return "TROUBLESHOOTING"

    return "AMBIGUOUS"

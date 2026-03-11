# ServiceNow Incident Module (SN)

Exported from BFS Bot v2. Contains all SN nodes and required components.

## Structure

```
sn_extract/
├── mcp/servicenow.py          # ServiceNow REST client
├── resources/llm.py            # LLM factory (WAIP/OpenAI)
├── graph/
│   ├── state.py                # GraphState, SNSession
│   ├── intent/                 # Intent routing
│   │   ├── router.py
│   │   └── rules.py
│   ├── nodes/sn/               # SN nodes
│   │   ├── classify.py
│   │   ├── accumulator.py
│   │   ├── specificity.py
│   │   ├── disambiguate.py
│   │   ├── retrieve.py
│   │   ├── generate.py
│   │   ├── confirm.py
│   │   ├── execute_action.py
│   │   └── query_builder.py
│   └── sn_workflow.py          # Minimal SN-only workflow
├── requirements_sn.txt
├── .env.example
└── README.md
```

## Setup on another machine

1. Copy this folder to the target machine.
2. Create virtualenv: `python -m venv .venv`
3. Activate and install: `pip install -r requirements_sn.txt`
4. Copy `.env.example` to `.env` and fill in credentials.
5. Run from project root: `python -c "from graph.sn_workflow import build_sn_workflow; w = build_sn_workflow(); print(w.invoke({'question': 'list incidents', 'intent': 'SERVICENOW_INCIDENT'}))"`

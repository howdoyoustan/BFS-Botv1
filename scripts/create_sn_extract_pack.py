#!/usr/bin/env python3
"""
Generate sn_extract_pack.py — a single file that recreates the sn_extract directory.

Run this script to create sn_extract_pack.py. Copy that file to another machine
and run it to create the full sn_extract folder structure (~200KB, not MB).

Usage:
    python scripts/create_sn_extract_pack.py
    python scripts/create_sn_extract_pack.py --output sn_extract_pack.py
"""

import argparse
import base64
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
OUTPUT = SOURCE / "sn_extract_pack.py"

FILES = [
    "mcp/servicenow.py",
    "resources/llm.py",
    "graph/state.py",
    "graph/__init__.py",
    "graph/intent/__init__.py",
    "graph/intent/router.py",
    "graph/intent/rules.py",
    "graph/nodes/sn/__init__.py",
    "graph/nodes/sn/classify.py",
    "graph/nodes/sn/accumulator.py",
    "graph/nodes/sn/specificity.py",
    "graph/nodes/sn/disambiguate.py",
    "graph/nodes/sn/retrieve.py",
    "graph/nodes/sn/generate.py",
    "graph/nodes/sn/confirm.py",
    "graph/nodes/sn/execute_action.py",
    "graph/nodes/sn/query_builder.py",
]

PACKAGE_INITS = ["graph/nodes/__init__.py", "mcp/__init__.py", "resources/__init__.py"]

SN_WORKFLOW = '''"""
Minimal ServiceNow-only workflow.
"""
from langgraph.graph import StateGraph, START, END
from graph.state import GraphState
from graph.intent.router import intent_router_node
from graph.nodes.sn.classify import sn_classify_node
from graph.nodes.sn.accumulator import sn_accumulate_node
from graph.nodes.sn.specificity import sn_score_node
from graph.nodes.sn.disambiguate import sn_disambiguate_node
from graph.nodes.sn.retrieve import sn_retrieve_node
from graph.nodes.sn.generate import sn_generate_node
from graph.nodes.sn.confirm import sn_confirm_node
from graph.nodes.sn.execute_action import sn_execute_action_node

def build_sn_workflow():
    workflow = StateGraph(GraphState)
    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("sn_classify", sn_classify_node)
    workflow.add_node("sn_accumulate", sn_accumulate_node)
    workflow.add_node("sn_score", sn_score_node)
    workflow.add_node("sn_disambiguate", sn_disambiguate_node)
    workflow.add_node("sn_retrieve", sn_retrieve_node)
    workflow.add_node("sn_generate", sn_generate_node)
    workflow.add_node("sn_confirm", sn_confirm_node)
    workflow.add_node("sn_execute_action", sn_execute_action_node)
    workflow.add_edge(START, "intent_router")
    workflow.add_conditional_edges("intent_router", lambda s: s["intent"],
        {"SERVICENOW_INCIDENT":"sn_classify","AMBIGUOUS":"sn_classify",
         "SOP_QUERY":"sn_classify","TROUBLESHOOTING":"sn_classify","DATA_ENGINEERING":"sn_classify"})
    workflow.add_edge("sn_classify", "sn_accumulate")
    workflow.add_edge("sn_accumulate", "sn_score")
    workflow.add_conditional_edges("sn_score", lambda s: (s.get("sn_session") or {}).get("sn_action", "execute"),
        {"disambiguate":"sn_disambiguate","execute":"sn_retrieve","force_execute":"sn_retrieve",
         "confirm_action":"sn_confirm","execute_action":"sn_execute_action"})
    workflow.add_edge("sn_disambiguate", END)
    workflow.add_edge("sn_retrieve", "sn_generate")
    workflow.add_edge("sn_generate", END)
    workflow.add_edge("sn_confirm", END)
    workflow.add_edge("sn_execute_action", END)
    return workflow.compile()
'''

REQUIREMENTS = """# Minimal deps for ServiceNow SN module
langchain-core
langchain-openai>=0.3.9
langgraph>=0.3.18
python-dotenv>=1.0.1
requests>=2.32.3
pydantic
"""

ENV_EXAMPLE = """# ServiceNow
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_USERNAME=your_username
SERVICENOW_PASSWORD=your_password

# LLM (WAIP or OpenAI)
WAIP_API_KEY=your_waip_key
WAIP_API_ENDPOINT=https://api.waip.wiprocms.com
"""

README = """# ServiceNow Incident Module (SN)

## Setup
1. python -m venv .venv && .venv\\Scripts\\activate (or source .venv/bin/activate)
2. pip install -r requirements_sn.txt
3. cp .env.example .env and fill credentials
4. Run: python -c "from graph.sn_workflow import build_sn_workflow; w=build_sn_workflow(); print(w.invoke({'question':'list incidents','intent':'SERVICENOW_INCIDENT'}))"
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", type=Path, default=OUTPUT)
    args = parser.parse_args()

    data = {}
    for rel in FILES:
        src = SOURCE / rel
        if src.exists():
            data[rel] = base64.b64encode(src.read_bytes()).decode("ascii")
    for rel in PACKAGE_INITS:
        if rel not in data:
            data[rel] = base64.b64encode(b"# Package init\n").decode("ascii")
    data["graph/sn_workflow.py"] = base64.b64encode(SN_WORKFLOW.encode()).decode("ascii")
    data["requirements_sn.txt"] = base64.b64encode(REQUIREMENTS.encode()).decode("ascii")
    data[".env.example"] = base64.b64encode(ENV_EXAMPLE.encode()).decode("ascii")
    data["README.md"] = base64.b64encode(README.encode()).decode("ascii")

    out = [
        '#!/usr/bin/env python3\n"""Recreate sn_extract. Run: python sn_extract_pack.py [--output /path]"""\n',
        "import argparse,base64\nfrom pathlib import Path\n\nF=",
        "{\n",
    ]
    for k, v in data.items():
        out.append(f'  {repr(k)}:{repr(v)},\n')
    out.append("}\n\ndef unpack(d):\n d=Path(d).resolve();d.mkdir(parents=True,exist_ok=True)\n")
    out.append(' for p,c in F.items():(d/p).parent.mkdir(parents=True,exist_ok=True);(d/p).write_text(base64.b64decode(c).decode(),encoding="utf-8")\n')
    out.append(" print(f'Created {len(F)} files in {d}')\n\n")
    out.append("if __name__=='__main__':\n p=argparse.ArgumentParser();p.add_argument('-o','--output',default='sn_extract');a=p.parse_args();unpack(a.output)\n")

    args.output.write_text("".join(out))
    print(f"Wrote {args.output} ({args.output.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()

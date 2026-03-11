#!/usr/bin/env python3
"""
Export ServiceNow (SN) nodes and required components for deployment on another machine.

Scans the codebase and creates a self-contained directory structure with all SN-related
files. Run from project root. Output can be copied to another machine.

Usage:
    python scripts/export_sn_module.py
    python scripts/export_sn_module.py --output /path/to/dest
    python scripts/export_sn_module.py --source /path/to/bfs-bot --output ./sn_extract

Hardcode paths below if needed.
"""

import os
import sys
import argparse
from pathlib import Path


# ── Hardcoded configuration ────────────────────────────────────────────────

# Source project root (where BFS Bot v2 lives)
SOURCE_ROOT = Path(__file__).resolve().parent.parent

# Output root (where to create the SN module structure)
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "sn_extract"

# All SN-related files (relative to SOURCE_ROOT)
# Order: dependencies first, then nodes
SN_FILES = [
    # MCP / ServiceNow client
    "mcp/servicenow.py",
    # Resources (LLM for classify)
    "resources/llm.py",
    # Graph state
    "graph/state.py",
    "graph/__init__.py",
    # Intent routing (routes to SN chain)
    "graph/intent/__init__.py",
    "graph/intent/router.py",
    "graph/intent/rules.py",
    # SN nodes
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

# Empty __init__.py for packages that may not exist
PACKAGE_INIT_PATHS = [
    "graph/nodes/__init__.py",
    "mcp/__init__.py",
    "resources/__init__.py",
]


# ── Export logic ───────────────────────────────────────────────────────────

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        print(f"  [SKIP] {src} (not found)")
        return False
    ensure_dir(dst.parent)
    content = src.read_text(encoding="utf-8", errors="replace")
    dst.write_text(content, encoding="utf-8")
    print(f"  [OK]   {src.relative_to(SOURCE_ROOT)} -> {dst.relative_to(OUTPUT_ROOT)}")
    return True


def create_minimal_workflow(dest_root: Path) -> None:
    """Create a minimal SN-only workflow for standalone use."""
    workflow_content = '''"""
Minimal ServiceNow-only workflow.
Use this when you only need the SN chain (no SOP, GT, DE).
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
    """Build a workflow with only the ServiceNow chain."""
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
    # SN-only: route all intents to SN chain (override other chains)
    workflow.add_conditional_edges(
        "intent_router",
        lambda state: state["intent"],
        {
            "SERVICENOW_INCIDENT": "sn_classify",
            "AMBIGUOUS": "sn_classify",
            "SOP_QUERY": "sn_classify",
            "TROUBLESHOOTING": "sn_classify",
            "DATA_ENGINEERING": "sn_classify",
        },
    )
    workflow.add_edge("sn_classify", "sn_accumulate")
    workflow.add_edge("sn_accumulate", "sn_score")
    workflow.add_conditional_edges(
        "sn_score",
        lambda state: (state.get("sn_session") or {}).get("sn_action", "execute"),
        {
            "disambiguate": "sn_disambiguate",
            "execute": "sn_retrieve",
            "force_execute": "sn_retrieve",
            "confirm_action": "sn_confirm",
            "execute_action": "sn_execute_action",
        },
    )
    workflow.add_edge("sn_disambiguate", END)
    workflow.add_edge("sn_retrieve", "sn_generate")
    workflow.add_edge("sn_generate", END)
    workflow.add_edge("sn_confirm", END)
    workflow.add_edge("sn_execute_action", END)

    return workflow.compile()
'''
    out_path = dest_root / "graph" / "sn_workflow.py"
    ensure_dir(out_path.parent)
    out_path.write_text(workflow_content, encoding="utf-8")
    print(f"  [OK]   (generated) graph/sn_workflow.py")


def create_requirements_sn(dest_root: Path) -> None:
    """Create a minimal requirements file for SN module."""
    content = """# Minimal deps for ServiceNow SN module
langchain-core
langchain-openai>=0.3.9
langgraph>=0.3.18
python-dotenv>=1.0.1
requests>=2.32.3
pydantic
"""
    (dest_root / "requirements_sn.txt").write_text(content, encoding="utf-8")
    print(f"  [OK]   (generated) requirements_sn.txt")


def create_env_template(dest_root: Path) -> None:
    """Create .env.example for SN module."""
    content = """# ServiceNow
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_USERNAME=your_username
SERVICENOW_PASSWORD=your_password

# LLM (WAIP or OpenAI)
WAIP_API_KEY=your_waip_key
WAIP_API_ENDPOINT=https://api.waip.wiprocms.com
# Or use OpenAI:
# OPENAI_API_KEY=your_openai_key
"""
    (dest_root / ".env.example").write_text(content, encoding="utf-8")
    print(f"  [OK]   (generated) .env.example")


def create_readme(dest_root: Path) -> None:
    """Create README for the exported module."""
    content = """# ServiceNow Incident Module (SN)

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
"""
    (dest_root / "README.md").write_text(content, encoding="utf-8")
    print(f"  [OK]   (generated) README.md")


def export_sn_module(source_root: Path, output_root: Path) -> None:
    """Export all SN files and create supporting files."""
    print(f"Exporting SN module from {source_root} to {output_root}")
    print("-" * 60)

    copied = 0
    for rel_path in SN_FILES:
        src = source_root / rel_path
        dst = output_root / rel_path
        if copy_file(src, dst):
            copied += 1

    for rel_path in PACKAGE_INIT_PATHS:
        dst = output_root / rel_path
        if not dst.exists():
            ensure_dir(dst.parent)
            dst.write_text("# Package init\n", encoding="utf-8")
            print(f"  [OK]   (created) {rel_path}")

    create_minimal_workflow(output_root)
    create_requirements_sn(output_root)
    create_env_template(output_root)
    create_readme(output_root)

    print("-" * 60)
    print(f"Done. Exported {copied} files + generated files to {output_root}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export SN nodes and components")
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE_ROOT,
        help=f"Source project root (default: {SOURCE_ROOT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_ROOT,
        help=f"Output directory (default: {OUTPUT_ROOT})",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Error: Source path does not exist: {args.source}")
        sys.exit(1)

    export_sn_module(args.source, args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Create a single self-extracting Python file containing the entire BFS Bot v2 codebase.

Run this script on the source machine. It generates bfs_bot_pack.py (~400KB, under 10MB).
Copy bfs_bot_pack.py to another machine and run it there to recreate the full project.

Excludes: .venv, __pycache__, .git, chroma, sn_extract, pack outputs, archives (.rar/.7z/.zip),
notebooks, and files over 500KB (e.g. uv.lock). Run pip/uv install to regenerate deps.

Usage:
    python scripts/create_pack.py
    python scripts/create_pack.py --output /path/to/bfs_bot_pack.py
    python scripts/create_pack.py --source /path/to/project
    python scripts/create_pack.py --max-size 1024  # KB; default 500
"""

import argparse
import base64
import os
import sys
from pathlib import Path


# ── Hardcoded config ────────────────────────────────────────────────────────

SOURCE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = SOURCE_ROOT / "bfs_bot_pack.py"

# Directories/files to exclude from the pack
EXCLUDE_DIRS = {".venv", "__pycache__", ".git", ".cursor", "chroma", "sn_extract", "node_modules"}
EXCLUDE_FILES = {
    ".env", ".env.local", ".cursorignore",
    "bfs_bot_pack.py", "sn_extract_pack.py", "rebuild_project.py",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".ipynb", ".db", ".sqlite", ".pdf", ".rar", ".7z", ".zip"}

# File patterns to include (None = all text files)
INCLUDE_EXTENSIONS = {".py", ".txt", ".md", ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}

# Skip files larger than this to keep pack under ~10MB (base64 adds ~33% overhead)
MAX_FILE_SIZE = 500 * 1024  # 500 KB


# ── Pack logic ──────────────────────────────────────────────────────────────

def should_include(path: Path, rel_path: str) -> bool:
    parts = Path(rel_path).parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return False
    if path.name in EXCLUDE_FILES:
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if INCLUDE_EXTENSIONS and path.suffix.lower() not in INCLUDE_EXTENSIONS:
        return False
    return True


def collect_files(source_root: Path) -> list[tuple[str, str]]:
    """Return list of (relative_path, base64_content)."""
    collected = []
    for path in source_root.rglob("*"):
        if path.is_file():
            try:
                rel = path.relative_to(source_root)
                rel_str = str(rel).replace("\\", "/")
                if not should_include(path, rel_str):
                    continue
                size = path.stat().st_size
                if size > MAX_FILE_SIZE:
                    continue
                content = path.read_bytes()
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                encoded = base64.b64encode(content).decode("ascii")
                collected.append((rel_str, encoded))
            except Exception as e:
                print(f"  [SKIP] {path}: {e}", file=sys.stderr)
    return collected


def generate_pack_script(files: list[tuple[str, str]], output_path: Path) -> None:
    """Write the self-extracting Python script."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('#!/usr/bin/env python3\n')
        f.write('"""\n')
        f.write('BFS Bot v2 — Self-extracting codebase pack.\n')
        f.write('Run this script to recreate the full project on this machine.\n\n')
        f.write('Usage:\n')
        f.write('  python bfs_bot_pack.py              # Unpack to current directory\n')
        f.write('  python bfs_bot_pack.py --output /path/to/dest\n')
        f.write('"""\n\n')
        f.write('import argparse\n')
        f.write('import base64\n')
        f.write('from pathlib import Path\n\n\n')
        f.write('def unpack(dest: Path) -> None:\n')
        f.write('    dest = dest.resolve()\n')
        f.write('    dest.mkdir(parents=True, exist_ok=True)\n')
        f.write('    for rel_path, b64_content in FILES.items():\n')
        f.write('        out = dest / rel_path\n')
        f.write('        out.parent.mkdir(parents=True, exist_ok=True)\n')
        f.write('        content = base64.b64decode(b64_content).decode("utf-8")\n')
        f.write('        out.write_text(content, encoding="utf-8")\n')
        f.write('        print(f"  Created: {rel_path}")\n')
        f.write('    print(f"\\nDone. Project extracted to {dest}")\n\n\n')
        f.write('FILES = {\n')

        for rel_path, encoded in files:
            f.write(f'    {repr(rel_path)}: {repr(encoded)},\n')

        f.write('}\n\n\n')
        f.write('def main():\n')
        f.write('    parser = argparse.ArgumentParser(description="Unpack BFS Bot v2 codebase")\n')
        f.write('    parser.add_argument("--output", "-o", type=Path, default=Path("."),\n')
        f.write('                        help="Destination directory (default: current dir)")\n')
        f.write('    args = parser.parse_args()\n')
        f.write('    unpack(args.output)\n\n\n')
        f.write('if __name__ == "__main__":\n')
        f.write('    main()\n')

    print(f"Wrote {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    global MAX_FILE_SIZE
    parser = argparse.ArgumentParser(description="Create self-extracting codebase pack")
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT, help="Source project root")
    parser.add_argument("--output", "-o", type=Path, default=OUTPUT_FILE, help="Output .py file")
    parser.add_argument("--max-size", type=int, default=500, help="Max file size in KB (default 500)")
    args = parser.parse_args()

    MAX_FILE_SIZE = args.max_size * 1024

    if not args.source.exists():
        print(f"Error: Source not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {args.source} (max {args.max_size} KB/file)...")
    files = collect_files(args.source)
    print(f"Collected {len(files)} files")

    generate_pack_script(files, args.output)
    print(f"\nCopy {args.output.name} to another machine and run:")
    print(f"  python {args.output.name} --output /path/to/bfs-bot")


if __name__ == "__main__":
    main()

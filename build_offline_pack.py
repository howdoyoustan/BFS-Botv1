#!/usr/bin/env python3
"""
Build an offline self-extracting pack script (no compression).

The generated pack script stores project files as Base64 and recreates them on
another machine without network access.

Examples:
  python build_offline_pack.py
  python build_offline_pack.py --source . --output bfs_bot_pack.py --max-size-mb 15
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cursor",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
}

DEFAULT_EXCLUDE_FILES = {
    "bfs_bot_pack.py",
    "sn_extract_pack.py",
}

DEFAULT_EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".tmp",
    ".cache",
}


def _iter_files(source: Path, output_name: str) -> list[Path]:
    files: list[Path] = []
    for p in source.rglob("*"):
        if not p.is_file():
            continue

        rel = p.relative_to(source)
        parts = set(rel.parts)

        if parts & DEFAULT_EXCLUDE_DIRS:
            continue
        if p.name in DEFAULT_EXCLUDE_FILES:
            continue
        if p.name == output_name:
            continue
        if p.suffix.lower() in DEFAULT_EXCLUDE_SUFFIXES:
            continue

        files.append(p)
    return sorted(files)


def _escape_single_quotes(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def build_pack_script(source: Path, output_script: Path, max_size_mb: float) -> None:
    source = source.resolve()
    output_script = output_script.resolve()

    if not source.exists() or not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")

    files = _iter_files(source, output_script.name)
    if not files:
        raise ValueError("No files selected to pack. Check exclude rules/source path.")

    lines: list[str] = []
    lines.append("#!/usr/bin/env python3")
    lines.append('"""Offline BFS Bot codebase pack (no compression)."""')
    lines.append("import argparse")
    lines.append("import base64")
    lines.append("from pathlib import Path")
    lines.append("")
    lines.append("FILES = {")

    total_raw_bytes = 0
    total_b64_chars = 0

    for path in files:
        rel = path.relative_to(source).as_posix()
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")

        total_raw_bytes += len(raw)
        total_b64_chars += len(b64)

        lines.append(f"    '{_escape_single_quotes(rel)}': '{b64}',")

    lines.append("}")
    lines.append("")
    lines.append("def unpack(dest: Path) -> None:")
    lines.append("    dest = dest.resolve()")
    lines.append("    dest.mkdir(parents=True, exist_ok=True)")
    lines.append("    for rel_path, b64_content in FILES.items():")
    lines.append("        out = dest / rel_path")
    lines.append("        out.parent.mkdir(parents=True, exist_ok=True)")
    lines.append("        out.write_bytes(base64.b64decode(b64_content))")
    lines.append('        print(f"  Created: {rel_path}")')
    lines.append('    print(f"\\nDone. Project extracted to {dest}")')
    lines.append("")
    lines.append("def main() -> None:")
    lines.append('    parser = argparse.ArgumentParser(description="Unpack offline BFS Bot codebase")')
    lines.append('    parser.add_argument("--output", "-o", type=Path, default=Path("."),')
    lines.append('                        help="Destination directory (default: current dir)")')
    lines.append("    args = parser.parse_args()")
    lines.append("    unpack(args.output)")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    main()")
    lines.append("")

    script_text = "\n".join(lines)
    output_script.write_text(script_text, encoding="utf-8")

    script_bytes = output_script.stat().st_size
    max_bytes = int(max_size_mb * 1024 * 1024)
    size_mb = script_bytes / (1024 * 1024)

    print(f"Packed files: {len(files)}")
    print(f"Raw payload bytes: {total_raw_bytes}")
    print(f"Base64 payload chars: {total_b64_chars}")
    print(f"Output script: {output_script}")
    print(f"Output size: {size_mb:.2f} MB")

    if script_bytes > max_bytes:
        raise RuntimeError(
            f"Generated script is {size_mb:.2f} MB, above limit of {max_size_mb:.2f} MB."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a single-file offline pack script (Base64, no compression)."
    )
    parser.add_argument(
        "--source",
        "-s",
        type=Path,
        default=Path("."),
        help="Project directory to pack (default: current directory).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("bfs_bot_pack.py"),
        help="Generated pack script path (default: bfs_bot_pack.py).",
    )
    parser.add_argument(
        "--max-size-mb",
        type=float,
        default=15.0,
        help="Fail if generated script exceeds this size in MB (default: 15).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_pack_script(args.source, args.output, args.max_size_mb)


if __name__ == "__main__":
    main()

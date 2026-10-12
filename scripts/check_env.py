"""Phase 0 environment check.

Run from the repository root:  python scripts/check_env.py

Prints PASS / WARN / FAIL for each tool the project needs. It only reads
local information and talks to Ollama on 127.0.0.1; it never contacts
the internet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
EMBED_MODEL = "nomic-embed-text"

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))


def command_version(cmd: list[str]) -> str | None:
    """Return the first line of `cmd --version`, or None if not installed."""
    executable = shutil.which(cmd[0])
    if executable is None:
        return None
    run_cmd = (
        ["cmd", "/c", executable, *cmd[1:]]
        if sys.platform == "win32" and executable.lower().endswith((".bat", ".cmd"))
        else [executable, *cmd[1:]]
    )
    try:
        out = subprocess.run(run_cmd, capture_output=True, text=True, timeout=10)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return None
    # Java prints its version to stderr and may prefix a "Picked up ..." notice.
    lines = [
        line
        for line in (out.stdout + out.stderr).splitlines()
        if line.strip() and not line.startswith("Picked up")
    ]
    return lines[0].strip() if lines else "installed"


def check_python() -> None:
    v = sys.version_info
    label = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 12):
        record("PASS", "Python", label)
    else:
        record("FAIL", "Python", f"{label} (need 3.12 or newer)")


def check_virtualenv() -> None:
    if sys.prefix != sys.base_prefix:
        record("PASS", "Virtual env", sys.prefix)
    else:
        record("WARN", "Virtual env", "not active; run the activate command first")


def check_tool(name: str, cmd: list[str], required: bool = True) -> None:
    version = command_version(cmd)
    if version:
        record("PASS", name, version)
    else:
        record("FAIL" if required else "WARN", name, "not found on PATH")


def check_ollama() -> None:
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=3) as resp:  # noqa: S310
            models = [m["name"] for m in json.load(resp).get("models", [])]
    except OSError:
        record("FAIL", "Ollama server", "not reachable on 127.0.0.1:11434; is it running?")
        return
    record("PASS", "Ollama server", f"{len(models)} model(s) installed")

    if any(m.startswith(EMBED_MODEL) for m in models):
        record("PASS", "Embedding model", EMBED_MODEL)
    else:
        record("FAIL", "Embedding model", f"run: ollama pull {EMBED_MODEL}")

    chat = [m for m in models if not m.startswith(EMBED_MODEL)]
    if len(chat) >= 2:
        record("PASS", "Chat models", ", ".join(chat))
    elif chat:
        record("WARN", "Chat models", f"only {chat[0]}; Phase 5 compares two candidates")
    else:
        record("FAIL", "Chat models", "none; see README for the pull commands")


def main() -> int:
    check_python()
    check_virtualenv()
    check_tool("Git", ["git", "--version"])
    check_tool("Node.js", ["node", "--version"])
    check_tool("npm", ["npm", "--version"])
    check_tool("Java (for Synthea)", ["java", "-version"], required=False)
    check_ollama()

    width = max(len(name) for _, name, _ in results)
    for status, name, detail in results:
        print(f"[{status}] {name.ljust(width)}  {detail}")

    failed = sum(1 for status, _, _ in results if status == "FAIL")
    print(f"\n{len(results) - failed}/{len(results)} checks without failure.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

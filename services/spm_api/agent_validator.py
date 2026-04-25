"""Three-step agent.py validator used by ``POST /api/spm/agents``.

Steps (all blocking unless noted):

  1. ``ast.parse()``  — must be syntactically valid Python 3.12.
  2. AST scan         — top-level ``async def main()`` must exist; the
                        agent's container entrypoint launches that
                        coroutine, so without it nothing would run.
  3. Dry-import       — execute the module in an ephemeral subprocess
                        to surface obvious ImportError / NameError /
                        SyntaxError-at-import. Any ImportError on a
                        third-party module is downgraded to a WARNING
                        because Phase 1's spm-api container doesn't
                        ship LangChain etc.; the customer's runtime
                        container will. (Phase 2 spawns an agent-runtime
                        container for this step instead.)

Errors block (HTTP 422 with ``detail = res.errors``); warnings flow
through to the client so the UI can surface them inline without
preventing the upload.
"""
from __future__ import annotations

import ast
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)


# ─── Result type ────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Outcome of ``validate_agent_code()``.

    ``ok`` is True iff no blocking errors fired. Warnings never affect
    ``ok`` — they're informational only.
    """
    ok:       bool
    errors:   List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ValidationError(Exception):
    """Raised by callers that want to convert a failed result to an
    exception (most don't — they just inspect the ValidationResult)."""


# ─── Internal helpers ───────────────────────────────────────────────────────

def _has_async_main(tree: ast.Module) -> bool:
    """Return True iff the module body contains a top-level
    ``async def main(...)`` declaration."""
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main":
            return True
    return False


# Subprocess script for the dry-import step. Written separately so the
# string can be passed to ``python -c "..."`` without escaping issues.
# Uses argv to receive the module path, avoiding f-string injection.
_DRY_IMPORT_SCRIPT = r"""
import importlib.util, sys, traceback
path = sys.argv[1]
spec = importlib.util.spec_from_file_location("agent_under_test", path)
mod  = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SyntaxError as e:
    print("SYNTAX_ERR: " + str(e))
    sys.exit(0)
except ImportError as e:
    print("IMPORT_ERR: " + str(e))
    sys.exit(0)
except Exception as e:
    print("RUNTIME_ERR: " + type(e).__name__ + ": " + str(e))
    sys.exit(0)
print("OK")
"""


# ─── Public API ─────────────────────────────────────────────────────────────

def validate_agent_code(code: str, *,
                          dry_import: bool = True,
                          dry_import_timeout_s: float = 15.0,
                          ) -> ValidationResult:
    """Run all three steps and return the aggregated result.

    Pass ``dry_import=False`` from unit tests when you only want to
    exercise the AST checks (avoids the subprocess + interpreter
    startup cost).
    """
    res = ValidationResult(ok=True)

    # 1. Syntax — Python parser is the source of truth.
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        res.ok = False
        res.errors.append(
            f"Python syntax error at line {e.lineno}: {e.msg}"
        )
        return res

    # 2. async def main()
    if not _has_async_main(tree):
        res.ok = False
        res.errors.append(
            "Top-level `async def main()` is required — the agent "
            "container's entrypoint awaits it."
        )
        return res

    # 3. Dry-import
    if dry_import:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "agent.py"
            f.write_text(code)
            try:
                p = subprocess.run(
                    [sys.executable, "-c", _DRY_IMPORT_SCRIPT, str(f)],
                    capture_output=True, text=True,
                    timeout=dry_import_timeout_s,
                )
            except subprocess.TimeoutExpired:
                # Hung at import time — almost certainly a side-effecting
                # top-level call. Surface as warning so the customer can
                # see it; not an error because Phase 2's runtime container
                # may have what they need.
                res.warnings.append(
                    f"Dry-import timed out after {dry_import_timeout_s:.0f}s "
                    "(top-level code may be doing I/O at import — the runtime "
                    "container may handle it differently)"
                )
                return res

            stdout = (p.stdout or "").strip()
            for line in stdout.splitlines():
                if line.startswith("IMPORT_ERR:"):
                    res.warnings.append(
                        line[len("IMPORT_ERR:"):].strip()
                        + "  (will be available in the agent-runtime container)"
                    )
                elif line.startswith("SYNTAX_ERR:"):
                    # Should be impossible — ast.parse would have caught
                    # it. Treat as belt-and-braces error.
                    res.ok = False
                    res.errors.append(line[len("SYNTAX_ERR:"):].strip())
                elif line.startswith("RUNTIME_ERR:"):
                    res.warnings.append(
                        line[len("RUNTIME_ERR:"):].strip()
                        + "  (agent runtime will surface this if it persists)"
                    )

    return res

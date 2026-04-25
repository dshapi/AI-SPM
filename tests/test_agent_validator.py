"""Tests for services.spm_api.agent_validator (Task 10).

Three steps:
  - syntax (ast.parse) — blocking
  - top-level ``async def main()`` — blocking
  - dry-import — warning only (not blocking)
"""
from __future__ import annotations

import pytest

from agent_validator import (
    ValidationError,
    ValidationResult,
    validate_agent_code,
)


# ─── Fixtures: representative agent.py contents ────────────────────────────

GOOD = """\
import asyncio

async def main():
    pass

asyncio.run(main())
"""

BAD_SYNTAX = "def main(::"

NO_MAIN = """\
import asyncio

async def helper():
    pass
"""

SYNC_MAIN_ONLY = """\
def main():
    return None
"""

UNKNOWN_IMPORT = """\
import zzz_nonexistent_module_for_testing_only

async def main():
    await zzz_nonexistent_module_for_testing_only.do_thing()
"""

NESTED_MAIN = """\
class Outer:
    async def main(self):
        pass
"""

SIDE_EFFECTING_TOPLEVEL = """\
print("hello at import time")

async def main():
    pass
"""


# ─── Step 1: syntax ────────────────────────────────────────────────────────

class TestSyntaxStep:
    def test_valid_passes_syntax(self):
        # dry_import=False to keep the test cheap and isolated.
        res = validate_agent_code(GOOD, dry_import=False)
        assert res.ok is True
        assert res.errors == []

    def test_syntax_error_blocks(self):
        res = validate_agent_code(BAD_SYNTAX, dry_import=False)
        assert res.ok is False
        assert len(res.errors) == 1
        assert "syntax" in res.errors[0].lower()

    def test_syntax_error_short_circuits_other_steps(self):
        # If syntax fails, we should NOT also get an "async def main"
        # error — the user can't fix what they can't parse.
        res = validate_agent_code(BAD_SYNTAX, dry_import=False)
        assert all("main" not in e.lower() for e in res.errors)


# ─── Step 2: top-level async def main() ────────────────────────────────────

class TestAsyncMainStep:
    def test_missing_main_blocks(self):
        res = validate_agent_code(NO_MAIN, dry_import=False)
        assert res.ok is False
        assert "main" in res.errors[0].lower()

    def test_sync_main_blocks_too(self):
        # Spec is specific: must be `async def main()`. A sync one is
        # an error because the runtime awaits the coroutine.
        res = validate_agent_code(SYNC_MAIN_ONLY, dry_import=False)
        assert res.ok is False
        assert "main" in res.errors[0].lower()

    def test_nested_async_main_doesnt_count(self):
        # `Outer.main` is not at module level → the runtime can't find it.
        res = validate_agent_code(NESTED_MAIN, dry_import=False)
        assert res.ok is False
        assert "main" in res.errors[0].lower()


# ─── Step 3: dry-import (warning only) ─────────────────────────────────────

class TestDryImportStep:
    def test_unknown_import_warns_does_not_block(self):
        res = validate_agent_code(UNKNOWN_IMPORT)
        # syntax + async-main pass; the unknown import surfaces as WARN.
        assert res.ok is True
        # The exact message format is version-dependent, but the module
        # name must appear so the customer can locate the offender.
        assert any(
            "zzz_nonexistent_module_for_testing_only" in w
            for w in res.warnings
        )

    def test_side_effecting_toplevel_does_not_break(self):
        # The agent's top-level ``print()`` shouldn't trigger a warning
        # — only ImportError / RuntimeError do.
        res = validate_agent_code(SIDE_EFFECTING_TOPLEVEL)
        assert res.ok is True
        assert res.warnings == []

    def test_dry_import_can_be_disabled(self):
        # When dry_import=False, no subprocess is spawned (verified by
        # the test running quickly — we just assert the result is
        # warning-free even with code that *would* warn).
        res = validate_agent_code(UNKNOWN_IMPORT, dry_import=False)
        assert res.ok is True
        assert res.warnings == []   # no dry-import → no warning


# ─── Result-type sanity ────────────────────────────────────────────────────

class TestValidationResult:
    def test_default_result_is_ok_with_empty_lists(self):
        r = ValidationResult(ok=True)
        assert r.errors   == []
        assert r.warnings == []

    def test_validation_error_is_an_exception(self):
        # Just guards that the export exists — callers that want to
        # raise can catch it.
        with pytest.raises(ValidationError):
            raise ValidationError("boom")

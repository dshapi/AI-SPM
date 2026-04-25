"""Static checks on the spec § 8 example agents.

Both examples are user-facing snippets that get embedded in docs and
the V1 quickstart. The customer journey breaks if either example
drifts out of step with the SDK surface, so we lock that down here:

  - The files parse as valid Python (syntax)
  - Each defines a top-level ``async def main()``
  - Each imports ``aispm`` (the only required dependency for hello)
  - The hello-world example uses every public surface mentioned in
    spec § 8: ready, chat.subscribe, chat.reply, mcp.call, llm.complete

We don't actually RUN the agents — that's the job of the e2e smoke
test which boots the full stack.
"""
from __future__ import annotations

import ast
import pathlib

EXAMPLES = pathlib.Path(__file__).parent.parent.parent / "agent_runtime" / "examples"


def _parse(name: str) -> ast.Module:
    return ast.parse((EXAMPLES / name).read_text())


def _has_async_main(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.AsyncFunctionDef) and n.name == "main"
        for n in tree.body
    )


def _imports(tree: ast.Module) -> set[str]:
    """Top-level module imports — captures both `import x` and
    `from x import ...` style."""
    out: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module.split(".")[0])
    return out


# ─── hello_world.py ────────────────────────────────────────────────────────

class TestHelloWorldExample:
    def test_parses(self):
        # Just calling _parse already raises on syntax errors.
        _parse("hello_world.py")

    def test_has_async_main(self):
        assert _has_async_main(_parse("hello_world.py"))

    def test_imports_aispm(self):
        assert "aispm" in _imports(_parse("hello_world.py"))

    def test_uses_full_sdk_surface(self):
        src = (EXAMPLES / "hello_world.py").read_text()
        # Every public surface mentioned in spec §8's bare-minimum
        # example MUST appear so the example stays a complete demo.
        for needed in (
            "aispm.ready",
            "aispm.chat.subscribe",
            "aispm.chat.reply",
            "aispm.mcp.call",
            "aispm.llm.complete",
        ):
            assert needed in src, f"hello_world.py is missing call to {needed}"


# ─── langchain_research.py ─────────────────────────────────────────────────

class TestLangChainExample:
    def test_parses(self):
        _parse("langchain_research.py")

    def test_has_async_main(self):
        assert _has_async_main(_parse("langchain_research.py"))

    def test_imports_aispm_and_langchain(self):
        imports = _imports(_parse("langchain_research.py"))
        assert "aispm"          in imports
        # LangChain's split packages — just check at least one is
        # present so the example is recognisably a LangChain agent.
        assert any(i.startswith("langchain") for i in imports), imports

    def test_uses_aispm_connection_constants(self):
        src = (EXAMPLES / "langchain_research.py").read_text()
        # Spec §8 explicitly recommends using the platform's
        # connection constants for LangChain compatibility.
        assert "aispm.LLM_BASE_URL" in src
        assert "aispm.LLM_API_KEY"  in src

    def test_handles_concurrent_sessions(self):
        """Spec §8 docs that production agents should wrap handlers in
        ``asyncio.create_task`` so concurrent sessions don't serialise."""
        src = (EXAMPLES / "langchain_research.py").read_text()
        assert "asyncio.create_task" in src

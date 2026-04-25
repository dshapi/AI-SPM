"""spm-mcp tool package.

Importing this module registers every Phase-1 tool against the FastMCP
server in ``services.spm_mcp.main``. Each tool lives in its own module
(``web_fetch.py``, …) so adding a new tool is a single-file change.

The decorator binding (``@mcp.tool()``) happens lazily inside each
tool's ``register(mcp)`` function, called from this package's
``__init__`` once the FastMCP instance is available.
"""
from __future__ import annotations

# Avoid circular import: services.spm_mcp.main imports this package, so
# we pull the FastMCP instance from the parent module *only* at runtime.
from services.spm_mcp import main as _spm_mcp_main  # noqa: F401

if getattr(_spm_mcp_main, "mcp", None) is not None:  # pragma: no cover
    from . import web_fetch
    web_fetch.register(_spm_mcp_main.mcp)

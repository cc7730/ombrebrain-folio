"""Start Ombre Brain and expose its original breath pipeline to the 5s SPA."""
from __future__ import annotations

import inspect
import os
import runpy

from mcp.server.fastmcp import FastMCP

from five_s_native_bridge import register_five_s_native_bridge


_original_run = FastMCP.run


def _patched_run(self, *args, **kwargs):
    # server.py defines all MCP tools before it finally calls mcp.run().
    # Register here so the original breath() function already exists.
    caller = inspect.currentframe().f_back
    namespace = caller.f_globals if caller is not None else {}
    if callable(namespace.get("breath")) and not getattr(self, "_five_s_native_registered", False):
        register_five_s_native_bridge(self, namespace)
        setattr(self, "_five_s_native_registered", True)
    return _original_run(self, *args, **kwargs)


FastMCP.run = _patched_run

runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"),
    run_name="__main__",
)

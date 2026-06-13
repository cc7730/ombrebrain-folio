"""Start Ombre Brain with the branch-local 5s bridge registered.

This wrapper patches ``FastMCP.__init__`` before executing the untouched
upstream ``server.py`` as ``__main__``.  When server.py creates its MCP object,
the wrapper receives the caller globals (bucket manager, embedding engine and
dehydator) and attaches the 5s routes.
"""

from __future__ import annotations

import inspect
import os
import runpy

from mcp.server.fastmcp import FastMCP

from five_s_bridge import register_five_s_bridge


_original_init = FastMCP.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    caller = inspect.currentframe().f_back
    namespace = caller.f_globals if caller is not None else {}
    if {"bucket_mgr", "dehydrator"}.issubset(namespace):
        register_five_s_bridge(self, namespace)


FastMCP.__init__ = _patched_init

runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"),
    run_name="__main__",
)

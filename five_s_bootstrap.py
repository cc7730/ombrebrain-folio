"""Start Ombre Brain and expose its original breath pipeline to the 5s SPA."""
from __future__ import annotations

import inspect
import os
import runpy

from mcp.server.fastmcp import FastMCP

from five_s_native_bridge import register_five_s_native_bridge


_original_init = FastMCP.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    caller = inspect.currentframe().f_back
    namespace = caller.f_globals if caller is not None else {}
    if callable(namespace.get("breath")):
        register_five_s_native_bridge(self, namespace)


FastMCP.__init__ = _patched_init

runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"),
    run_name="__main__",
)

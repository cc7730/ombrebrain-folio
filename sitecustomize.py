"""Autoload the isolated 5s bridge without modifying upstream ``server.py``.

Python imports ``sitecustomize`` during interpreter startup.  We wrap
``FastMCP.__init__`` and register the bridge only when the constructor is
called from Ombre Brain's server module, where the core objects already exist.
This file is intentionally tiny and branch-local; it can be removed once the
bridge is folded into the main server explicitly.
"""

from __future__ import annotations

import inspect
import logging
import os

LOGGER = logging.getLogger("ombre_brain.five_s_autoload")


def _install() -> None:
    if os.environ.get("OMBRE_DISABLE_5S_BRIDGE", "").strip() == "1":
        return

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        # Other Python commands may run before dependencies are installed.
        return

    if getattr(FastMCP, "_ombre_5s_bridge_patched", False):
        return

    original_init = FastMCP.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            caller = inspect.currentframe().f_back
            namespace = caller.f_globals if caller is not None else {}
            if not {"bucket_mgr", "dehydrator"}.issubset(namespace):
                return
            from five_s_bridge import register_five_s_bridge

            register_five_s_bridge(self, namespace)
        except Exception as exc:
            # The bridge must never prevent the main memory server from starting.
            LOGGER.exception("Unable to register 5s bridge: %s", exc)

    FastMCP.__init__ = patched_init
    FastMCP._ombre_5s_bridge_patched = True


_install()

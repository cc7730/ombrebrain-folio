"""Expose Ombre Brain's original breath logic to the CanCanPhone SPA.

This module does not implement a second retrieval/rerank pipeline. It calls the
same ``breath`` tool used by the original MCP integration, preserving the
upstream surfacing, keyword/vector dual-channel retrieval, emotional
reconstruction, token budget and random-memory behavior.
"""
from __future__ import annotations

from typing import Any


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _clamp_float(value: Any, default: float = -1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if 0.0 <= parsed <= 1.0 else default


def register_five_s_native_bridge(mcp: Any, namespace: dict[str, Any]) -> bool:
    breath = namespace.get("breath")
    if not callable(breath):
        return False

    @mcp.custom_route("/api/5s/context", methods=["POST"])
    async def api_five_s_context(request):
        from starlette.responses import JSONResponse

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

        query = str(body.get("query") or "").strip()
        mode = str(body.get("mode") or "query").strip().lower()
        max_tokens = _clamp_int(body.get("max_tokens", 6000), 6000, 500, 20000)
        max_results = _clamp_int(body.get("max_results", 20), 20, 1, 50)
        domain = str(body.get("domain") or "")
        valence = _clamp_float(body.get("valence", -1))
        arousal = _clamp_float(body.get("arousal", -1))

        sections: list[str] = []

        # Match the original SessionStart behavior: surface the weight pool once
        # when a new conversation begins, then add query-specific breath results.
        if mode in {"session", "start", "new"}:
            surfaced = await breath(
                query="",
                max_tokens=min(max_tokens, 10000),
                max_results=min(max_results, 20),
            )
            if surfaced and "权重池平静" not in surfaced:
                sections.append("[Ombre Brain · 会话浮现]\n" + surfaced)

        if query:
            recalled = await breath(
                query=query,
                max_tokens=max_tokens,
                domain=domain,
                valence=valence,
                arousal=arousal,
                max_results=max_results,
            )
            if recalled and "未找到相关记忆" not in recalled:
                sections.append("[Ombre Brain · 当前相关记忆]\n" + recalled)

        context = "\n\n".join(sections).strip()
        return JSONResponse({
            "ok": True,
            "engine": "ombre-breath",
            "mode": mode,
            "has_context": bool(context),
            "context": context,
        })

    return True

"""Persistent runtime LLM configuration for the CanCanPhone 5s bridge."""
from __future__ import annotations

import json
import os
from typing import Any


def _config_path(config: dict[str, Any]) -> str:
    base = str(config.get("buckets_dir") or "/app/buckets")
    return os.path.join(base, "5s_reranker_config.json")


def _read_saved(config: dict[str, Any]) -> dict[str, Any]:
    path = _config_path(config)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _write_saved(config: dict[str, Any], payload: dict[str, Any]) -> None:
    path = _config_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    try:
        os.chmod(temp, 0o600)
    except Exception:
        pass
    os.replace(temp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _mask(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return value[:6] + "…" + value[-4:]


def _apply(namespace: dict[str, Any], saved: dict[str, Any]) -> None:
    config = namespace.get("config")
    dehydrator = namespace.get("dehydrator")
    if not isinstance(config, dict) or dehydrator is None:
        return

    dehy = config.setdefault("dehydration", {})
    for key in ("model", "base_url", "api_key"):
        value = saved.get(key)
        if isinstance(value, str) and value.strip():
            dehy[key] = value.strip()
    if "temperature" in saved:
        try:
            dehy["temperature"] = float(saved["temperature"])
        except (TypeError, ValueError):
            pass

    if hasattr(dehydrator, "reload"):
        dehydrator.reload(config)


def register_five_s_runtime_config(mcp: Any, namespace: dict[str, Any]) -> bool:
    """Register GET/POST /api/5s/config and apply saved settings at startup."""
    config = namespace.get("config")
    dehydrator = namespace.get("dehydrator")
    if not isinstance(config, dict) or dehydrator is None:
        return False

    saved = _read_saved(config)
    if saved:
        _apply(namespace, saved)

    @mcp.custom_route("/api/5s/config", methods=["GET"])
    async def api_five_s_config_get(request):
        from starlette.responses import JSONResponse

        current = _read_saved(config)
        return JSONResponse({
            "ok": True,
            "model": str(current.get("model") or getattr(dehydrator, "model", "")),
            "base_url": str(current.get("base_url") or getattr(dehydrator, "base_url", "")),
            "api_key_mask": _mask(str(current.get("api_key") or getattr(dehydrator, "api_key", ""))),
            "has_key": bool(current.get("api_key") or getattr(dehydrator, "api_key", "")),
            "api_available": bool(getattr(dehydrator, "api_available", False)),
            "temperature": current.get("temperature", getattr(dehydrator, "temperature", 0.0)),
        })

    @mcp.custom_route("/api/5s/config", methods=["POST"])
    async def api_five_s_config_post(request):
        from starlette.responses import JSONResponse

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be an object"}, status_code=400)

        previous = _read_saved(config)
        next_value = dict(previous)
        for key in ("model", "base_url"):
            if key in body:
                value = str(body.get(key) or "").strip()
                if value:
                    next_value[key] = value
        if "api_key" in body:
            value = str(body.get("api_key") or "").strip()
            if value:
                next_value["api_key"] = value
            elif body.get("clear_api_key"):
                next_value.pop("api_key", None)
        if "temperature" in body:
            try:
                next_value["temperature"] = float(body["temperature"])
            except (TypeError, ValueError):
                return JSONResponse({"error": "temperature must be numeric"}, status_code=400)

        if not next_value.get("model") or not next_value.get("base_url"):
            return JSONResponse({"error": "model and base_url are required"}, status_code=400)

        _write_saved(config, next_value)
        _apply(namespace, next_value)

        return JSONResponse({
            "ok": True,
            "model": getattr(dehydrator, "model", ""),
            "base_url": getattr(dehydrator, "base_url", ""),
            "api_key_mask": _mask(getattr(dehydrator, "api_key", "")),
            "has_key": bool(getattr(dehydrator, "api_key", "")),
            "api_available": bool(getattr(dehydrator, "api_available", False)),
        })

    @mcp.custom_route("/api/5s/config/test", methods=["POST"])
    async def api_five_s_config_test(request):
        from starlette.responses import JSONResponse

        if not getattr(dehydrator, "api_available", False) or getattr(dehydrator, "client", None) is None:
            return JSONResponse({"ok": False, "error": "API key is not configured"}, status_code=400)
        try:
            response = await dehydrator.client.chat.completions.create(
                model=dehydrator.model,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                temperature=0,
                max_tokens=8,
            )
            text = ""
            if getattr(response, "choices", None):
                text = str(response.choices[0].message.content or "").strip()
            return JSONResponse({"ok": True, "reply": text, "model": dehydrator.model})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    return True

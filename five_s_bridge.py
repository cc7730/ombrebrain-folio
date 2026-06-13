"""5s bridge routes for Ombre Brain.

The module is registered automatically by ``sitecustomize.py`` when
``server.py`` creates its FastMCP instance.  Keeping the bridge in a separate
module lets the feature live on an isolated branch without touching the large
upstream server file.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

LOGGER = logging.getLogger("ombre_brain.five_s_bridge")


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _is_internalized(meta: dict[str, Any]) -> bool:
    return bool(meta.get("internalized") or meta.get("digested"))


def _is_noise(meta: dict[str, Any]) -> bool:
    return bool(meta.get("resolved") and int(meta.get("importance", 5) or 5) <= 1)


def _is_hidden(meta: dict[str, Any]) -> bool:
    bucket_type = str(meta.get("type", "dynamic") or "dynamic").lower()
    return bucket_type in {"feel", "archive", "archived", "trash", "trashed"} or _is_internalized(meta) or _is_noise(meta)


def _clean_text(value: Any, limit: int = 1800) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _normalise_candidate(bucket: dict[str, Any], *, keyword_score: float = 0.0, vector_score: float = 0.0) -> dict[str, Any] | None:
    meta = bucket.get("metadata") or {}
    if _is_hidden(meta):
        return None

    content = _clean_text(bucket.get("content", ""), 2200)
    summary = _clean_text(meta.get("summary", ""), 500)
    name = _clean_text(meta.get("name") or bucket.get("id", ""), 180)
    importance = _clamp_int(meta.get("importance", 5), 5, 1, 10)

    # keyword scores are normally 0..100 while cosine similarity is 0..1.
    keyword_norm = max(0.0, min(float(keyword_score or 0.0) / 100.0, 1.0))
    vector_norm = max(0.0, min(float(vector_score or 0.0), 1.0))
    retrieval_score = max(keyword_norm, vector_norm)
    fallback_score = retrieval_score * (0.8 + importance / 25.0)

    return {
        "id": str(bucket.get("id", "")),
        "name": name,
        "summary": summary,
        "content": content,
        "domain": list(meta.get("domain") or []),
        "tags": list(meta.get("tags") or []),
        "importance": importance,
        "valence": meta.get("valence", 0.5),
        "arousal": meta.get("arousal", 0.3),
        "keyword_score": round(keyword_norm, 6),
        "vector_score": round(vector_norm, 6),
        "retrieval_score": round(retrieval_score, 6),
        "fallback_score": round(fallback_score, 6),
    }


def _merge_candidate(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    target["keyword_score"] = max(float(target.get("keyword_score", 0)), float(incoming.get("keyword_score", 0)))
    target["vector_score"] = max(float(target.get("vector_score", 0)), float(incoming.get("vector_score", 0)))
    target["retrieval_score"] = max(target["keyword_score"], target["vector_score"])
    target["fallback_score"] = target["retrieval_score"] * (0.8 + int(target.get("importance", 5)) / 25.0)


def _extract_ids(raw_text: str, allowed_ids: set[str], top_k: int) -> list[str]:
    raw = (raw_text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    attempts = [raw]
    obj = re.search(r"\{[\s\S]*\}", raw)
    arr = re.search(r"\[[\s\S]*\]", raw)
    if obj:
        attempts.append(obj.group(0))
    if arr:
        attempts.append(arr.group(0))

    for candidate in attempts:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, list):
            values = parsed
        elif isinstance(parsed, dict):
            values = parsed.get("ids") or parsed.get("selectedIds") or parsed.get("memories") or []
        else:
            values = []
        ids: list[str] = []
        for item in values:
            value = item if isinstance(item, str) else (item.get("id") if isinstance(item, dict) else None)
            value = str(value or "")
            if value in allowed_ids and value not in ids:
                ids.append(value)
            if len(ids) >= top_k:
                return ids
        if ids:
            return ids

    found = [candidate_id for candidate_id in allowed_ids if candidate_id and candidate_id in raw]
    return found[:top_k]


def _format_injection(memories: list[dict[str, Any]], max_chars: int = 7000) -> str:
    if not memories:
        return ""
    header = (
        "[Ombre Brain · 5s Bridge]\n"
        "以下是从长期记忆库检索并重排出的相关记忆。把它们当作背景事实使用；"
        "与用户当前消息冲突时，以当前消息为准，不要声称看到了未提供的内容。\n"
    )
    parts = [header]
    used = len(header)
    for index, memory in enumerate(memories, 1):
        body = memory.get("content") or memory.get("summary") or memory.get("name") or ""
        line = (
            f"\n{index}. [{memory.get('name') or memory.get('id')}] "
            f"(importance={memory.get('importance', 5)}, id={memory.get('id')})\n"
            f"{body.strip()}\n"
        )
        if used + len(line) > max_chars:
            remaining = max_chars - used
            if remaining > 120:
                parts.append(line[:remaining].rstrip() + "…\n")
            break
        parts.append(line)
        used += len(line)
    return "".join(parts).strip()


async def _rerank(
    *,
    dehydrator: Any,
    query: str,
    conversation_context: str,
    candidates: list[dict[str, Any]],
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    fallback = sorted(candidates, key=lambda item: item.get("fallback_score", 0), reverse=True)[:top_k]
    client = getattr(dehydrator, "client", None)
    model = getattr(dehydrator, "model", "")
    api_available = bool(getattr(dehydrator, "api_available", False))
    if not api_available or client is None or not model or len(candidates) <= top_k:
        return fallback, "fallback"

    compact = []
    for item in candidates:
        compact.append(
            {
                "id": item["id"],
                "name": item["name"],
                "summary": item["summary"],
                "content": item["content"][:700],
                "domain": item["domain"],
                "tags": item["tags"],
                "importance": item["importance"],
                "retrieval_score": item["retrieval_score"],
            }
        )

    prompt = (
        "你是长期记忆重排器。请根据用户最新消息和最近对话，从候选记忆中选择最应该注入给聊天模型的记忆。\n"
        f"最多选择 {top_k} 条。优先真正相关、能改变回答方式或事实判断的记忆；不要只因为情绪相近就选。\n"
        "只返回严格 JSON：{\"ids\":[\"id1\",\"id2\"]}，不要解释。\n\n"
        f"用户最新消息：\n{query[:2500]}\n\n"
        f"最近对话：\n{conversation_context[:9000]}\n\n"
        "候选记忆：\n"
        + json.dumps(compact, ensure_ascii=False)
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=500,
        )
        content = ""
        if getattr(response, "choices", None):
            content = response.choices[0].message.content or ""
        allowed_ids = {item["id"] for item in candidates}
        selected_ids = _extract_ids(content, allowed_ids, top_k)
        if not selected_ids:
            return fallback, "fallback"
        by_id = {item["id"]: item for item in candidates}
        return [by_id[item_id] for item_id in selected_ids if item_id in by_id][:top_k], "llm"
    except Exception as exc:
        LOGGER.warning("5s reranker failed, using retrieval fallback: %s", exc)
        return fallback, "fallback"


def register_five_s_bridge(mcp: Any, namespace: dict[str, Any]) -> bool:
    """Register bridge routes on an existing FastMCP instance."""

    bucket_mgr = namespace.get("bucket_mgr")
    embedding_engine = namespace.get("embedding_engine")
    dehydrator = namespace.get("dehydrator")
    if bucket_mgr is None or dehydrator is None:
        LOGGER.warning("5s bridge skipped: Ombre globals are not ready")
        return False

    @mcp.custom_route("/api/5s/recall", methods=["POST"])
    async def api_five_s_recall(request):
        from starlette.responses import JSONResponse

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

        query = str(body.get("query") or "").strip()
        if not query:
            return JSONResponse({"error": "query is required"}, status_code=400)

        conversation_context = str(body.get("conversation_context") or body.get("conversationContext") or "")
        candidate_limit = _clamp_int(body.get("candidate_limit", 50), 50, 5, 50)
        top_k = _clamp_int(body.get("top_k", 5), 5, 1, 10)

        merged: dict[str, dict[str, Any]] = {}

        try:
            keyword_hits = await bucket_mgr.search(query, limit=candidate_limit)
        except Exception as exc:
            LOGGER.warning("5s keyword recall failed: %s", exc)
            keyword_hits = []

        for bucket in keyword_hits:
            candidate = _normalise_candidate(bucket, keyword_score=float(bucket.get("score", 0) or 0))
            if not candidate or not candidate["id"]:
                continue
            merged[candidate["id"]] = candidate

        if embedding_engine is not None and getattr(embedding_engine, "enabled", False):
            try:
                vector_hits = await embedding_engine.search_similar(query, top_k=candidate_limit)
            except Exception as exc:
                LOGGER.warning("5s vector recall failed: %s", exc)
                vector_hits = []
            for bucket_id, similarity in vector_hits:
                try:
                    bucket = await bucket_mgr.get(bucket_id)
                except Exception:
                    bucket = None
                if not bucket:
                    continue
                candidate = _normalise_candidate(bucket, vector_score=float(similarity or 0))
                if not candidate or not candidate["id"]:
                    continue
                if candidate["id"] in merged:
                    _merge_candidate(merged[candidate["id"]], candidate)
                else:
                    merged[candidate["id"]] = candidate

        candidates = sorted(merged.values(), key=lambda item: item.get("fallback_score", 0), reverse=True)[:candidate_limit]
        selected, reranker_mode = await _rerank(
            dehydrator=dehydrator,
            query=query,
            conversation_context=conversation_context,
            candidates=candidates,
            top_k=top_k,
        )

        selected_ids = [item["id"] for item in selected]
        if selected_ids:
            try:
                bucket_mgr.record_surfacing(selected_ids)
            except Exception:
                pass

        injection = _format_injection(selected)
        return JSONResponse(
            {
                "ok": True,
                "query": query,
                "candidate_count": len(candidates),
                "selected_count": len(selected),
                "reranker": reranker_mode,
                "memories": selected,
                "injection": injection,
            }
        )

    LOGGER.info("5s bridge registered: POST /api/5s/recall")
    return True

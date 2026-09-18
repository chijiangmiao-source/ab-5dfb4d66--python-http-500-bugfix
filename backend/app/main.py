"""FastAPI application for interpreter handoff alignment.

The only business endpoint is ``POST /api/align`` accepting::

    {"left": [{"time": int, "text": str}, ...],
     "right": [{"time": int, "text": str}, ...],
     "anchors": [{"left": int, "right": int}, ...]}   # optional

The optional ``anchors`` array pins human-confirmed record pairs; each anchor
forces a match row and the segments between anchors are aligned by the same
DP.  Requests without ``anchors`` (or with an empty array) produce exactly
the legacy response.

Malformed JSON and every structural/semantic violation (wrong type, too many
items, missing/empty field, duplicate or non-increasing time, unknown field,
out-of-range/duplicated/crossing anchor) produce exactly ONE 4xx failure
carrying the first error path, e.g. ``{"error": "...", "path": "left[2].time"}``
or ``{"error": "...", "path": "anchors[1].left"}``.  Pydantic's bulk error
lists are deliberately bypassed so the caller can mark a single location.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .alignment import align, align_with_anchors
from .validation import MAX_ITEMS, validate_anchors, validate_sequence

app = FastAPI(title="Interpreter Handoff Aligner", version="1.0.0")

# Direct browser -> API calls (Vite dev server) are allowed; in Docker the
# frontend nginx proxies /api to this service same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _failure(status: int, message: str, path: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": message, "path": path},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/align")
async def align_notes(request: Request) -> JSONResponse:
    raw = await request.body()
    try:
        payload: Any = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _failure(400, "请求体不是合法的 JSON。")

    if not isinstance(payload, dict):
        return _failure(422, "请求根节点必须是包含 left 与 right 的对象。")

    for side in ("left", "right"):
        if side not in payload:
            return _failure(422, f"缺少 {side} 数组。", side)

    # Validate the two sequences independently; left is examined first, so a
    # failure there is reported before any right-side problem.
    for side in ("left", "right"):
        bad_path = validate_sequence(payload[side], side)
        if bad_path is not None:
            return _failure(422, _describe(payload[side], bad_path, side), bad_path)

    # Optional human-confirmed anchors.  Absent (or an empty array) keeps the
    # legacy code path — and the legacy response — byte-for-byte identical.
    anchors = payload.get("anchors")
    if anchors is not None:
        anchor_error = validate_anchors(
            anchors, len(payload["left"]), len(payload["right"])
        )
        if anchor_error is not None:
            path, message = anchor_error
            return _failure(422, message, path)
        if anchors:
            result = align_with_anchors(payload["left"], payload["right"], anchors)
            return JSONResponse(result)

    result = align(payload["left"], payload["right"])
    return JSONResponse(result)


def _describe(seq: Any, path: str, side: str) -> str:
    """Turn the first error path into one clear Chinese message."""
    if path == side and not isinstance(seq, list):
        return f"{side} 必须是数组。"

    if path == f"{side}[{MAX_ITEMS}]":
        return f"{side} 最多包含 {MAX_ITEMS} 项。"

    # Parse `side[index][.field]`.
    rest = path[len(side) + 1 :]
    idx_str, _, field = rest.partition("].")
    idx = int(idx_str)

    if "." not in rest:  # the item itself is not an object
        return f"{path} 必须是包含 time 与 text 的对象。"

    item = seq[idx]
    if field == "time":
        value = item.get("time")
        if "time" not in item:
            return f"{path} 缺少整数字段 time。"
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path} 必须是整数毫秒时间戳。"
        # Non-increasing: locate the previous time for a helpful message.
        if idx > 0 and isinstance(seq[idx - 1], dict) and isinstance(
            seq[idx - 1].get("time"), int
        ):
            return (
                f"{path} 为 {value}，未严格递增（上一项时间为 "
                f"{seq[idx - 1]['time']}）。"
            )
        return f"{path} 必须严格递增且不可重复。"

    if field == "text":
        if "text" not in item:
            return f"{path} 缺少非空字符串字段 text。"
        return f"{path} 必须是非空字符串。"

    return f"{path} 是多余字段，每项仅允许 time 与 text。"

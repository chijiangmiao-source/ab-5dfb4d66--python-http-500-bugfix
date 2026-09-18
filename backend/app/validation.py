"""Sequence validation for the handoff alignment API.

Each interpreter note is an object of the form ``{"time": <int ms>, "text": <str>}``.
The rules enforced here, in check order, are:

1. the payload must be an array (objects are not silently accepted);
2. the array contains at most ``MAX_ITEMS`` entries;
3. every entry is a JSON object;
4. every object contains an integer ``time`` (booleans and floats are rejected)
   and a non-empty ``text`` string, and no other keys (each item contains
   only ``time`` and ``text``);
5. ``time`` values are strictly increasing (duplicates and decreases fail).

``first_error_path`` is a JSON-Pointer-ish path of the *first* failure only,
e.g. ``left[2].time``, so the UI can mark exactly one place and the user fixes
errors one at a time without being flooded.

``validate_anchors`` applies the same single-failure contract to the optional
``anchors`` array (human-confirmed ``left``/``right`` index pairs): indices
must exist, may not be reused, and must be strictly increasing on both sides
(no crossing).  It returns ``(path, message)`` because the message needs
context (the offending value, the earlier anchor) that the path alone cannot
carry.
"""

from __future__ import annotations

from typing import Any

MAX_ITEMS = 200


def _is_plain_int(value: Any) -> bool:
    # bool is a subclass of int in Python; JSON true/false are not timestamps.
    return isinstance(value, int) and not isinstance(value, bool)


def validate_sequence(seq: Any, side: str) -> str | None:
    """Return the first error path, or None when the sequence is valid."""
    prefix = side

    if not isinstance(seq, list):
        return prefix

    if len(seq) > MAX_ITEMS:
        return f"{prefix}[{MAX_ITEMS}]"

    prev_time: int | None = None
    for i, item in enumerate(seq):
        item_path = f"{prefix}[{i}]"
        if not isinstance(item, dict):
            return item_path

        if "time" not in item:
            return f"{item_path}.time"
        time_value = item["time"]
        if not _is_plain_int(time_value):
            return f"{item_path}.time"

        if "text" not in item:
            return f"{item_path}.text"
        text_value = item["text"]
        if not isinstance(text_value, str) or len(text_value) == 0:
            return f"{item_path}.text"

        extra_keys = [k for k in item if k not in ("time", "text")]
        if extra_keys:
            return f"{item_path}.{extra_keys[0]}"

        if prev_time is not None and time_value <= prev_time:
            return f"{item_path}.time"
        prev_time = time_value

    return None


def validate_anchors(
    anchors: Any, left_len: int, right_len: int
) -> tuple[str, str] | None:
    """Validate the optional ``anchors`` array of human-confirmed pairs.

    Each anchor is ``{"left": <index>, "right": <index>}`` pinning one left
    record to one right record.  The rules, in check order, are:

    1. the payload must be an array of objects containing only integer
       ``left`` / ``right`` fields (booleans are rejected);
    2. both indices exist (``0 <= left < left_len``, same for ``right``);
    3. neither side's index may be reused by a later anchor;
    4. anchors must not cross: both index sequences are strictly increasing.

    Returns ``(path, message)`` of the FIRST problem only — e.g.
    ``("anchors[1].left", ...)`` so the UI can mark that exact anchor — or
    ``None`` when every anchor is usable.
    """
    if not isinstance(anchors, list):
        return "anchors", "anchors 必须是数组。"

    # index -> position of the anchor that first used it (for the message)
    used_left: dict[int, int] = {}
    used_right: dict[int, int] = {}
    prev_left: int | None = None
    prev_right: int | None = None

    for k, anchor in enumerate(anchors):
        path = f"anchors[{k}]"
        if not isinstance(anchor, dict):
            return path, f"{path} 必须是包含 left 与 right 的对象。"

        for field in ("left", "right"):
            if field not in anchor:
                return f"{path}.{field}", f"{path} 缺少整数字段 {field}。"
            if not _is_plain_int(anchor[field]):
                return f"{path}.{field}", f"{path}.{field} 必须是整数索引。"

        extra_keys = [key for key in anchor if key not in ("left", "right")]
        if extra_keys:
            return (
                f"{path}.{extra_keys[0]}",
                f"{path}.{extra_keys[0]} 是多余字段，锚点仅允许 left 与 right。",
            )

        li: int = anchor["left"]
        ri: int = anchor["right"]

        if li < 0 or li >= left_len:
            return (
                f"{path}.left",
                f"{path}.left 为 {li}，超出左侧记录索引范围（共 {left_len} 条）。",
            )
        if ri < 0 or ri >= right_len:
            return (
                f"{path}.right",
                f"{path}.right 为 {ri}，超出右侧记录索引范围（共 {right_len} 条）。",
            )

        if li in used_left:
            return (
                f"{path}.left",
                f"{path}.left 为 {li}，与 anchors[{used_left[li]}].left 重复，"
                "同一左侧记录不可复用。",
            )
        if ri in used_right:
            return (
                f"{path}.right",
                f"{path}.right 为 {ri}，与 anchors[{used_right[ri]}].right 重复，"
                "同一右侧记录不可复用。",
            )

        if prev_left is not None and li <= prev_left:
            return (
                f"{path}.left",
                f"{path}.left 为 {li}，未大于上一锚点的 {prev_left}，锚点不可交叉。",
            )
        if prev_right is not None and ri <= prev_right:
            return (
                f"{path}.right",
                f"{path}.right 为 {ri}，未大于上一锚点的 {prev_right}，锚点不可交叉。",
            )

        used_left[li] = k
        used_right[ri] = k
        prev_left, prev_right = li, ri

    return None

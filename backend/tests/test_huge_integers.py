"""Arbitrary-precision integer handling across parse, DP and serialization.

The public contract (README, “超大毫秒整数”) is that ``time`` is an
arbitrary-precision integer.  Python 3.12's default PEP 682 cap rejects
decimal strings longer than 4300 digits; these tests pin that a timestamp at
the boundary (4300 digits), just over it (4301 digits — the original HTTP 500
report) and far beyond it (10000 digits):

* parses to a genuine ``int`` (never a float) and never produces a 500;
* round-trips through the response with every decimal digit unchanged;
* drives the match/gap/anchor cost computation exactly;
* still fails *structurally* (one 4xx with a ``path``) when the value is a
  duplicate or out of order — including via a huge anchor index.

They also assert the interpreter-wide safety threshold is restored after a
request (the cap is lifted only around parse/format/encode).
"""

from __future__ import annotations

import contextlib
import json
import sys

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=True)


@contextlib.contextmanager
def _unlimited():
    """Lift the digit cap for the test's own (client-side) conversions."""
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(old)


def as_int(digits: str) -> int:
    with _unlimited():
        return int(digits)


def parse(resp) -> dict:
    # The client-side parse of a huge-int response needs the cap lifted too;
    # production callers use the BigInt-aware parser, stdlib json does not.
    with _unlimited():
        return json.loads(resp.content)


def post_raw(raw: bytes):
    return client.post(
        "/api/align",
        content=raw,
        headers={"content-type": "application/json"},
    )


def wrap(digits: str, *, anchors: str | None = None, right: str = "[]") -> bytes:
    anchor_part = f',"anchors":{anchors}' if anchors is not None else ""
    return (
        b'{"left":[{"time":'
        + digits.encode()
        + b',"text":"x"}],"right":'
        + right.encode()
        + anchor_part.encode()
        + b"}"
    )


def test_threshold_is_at_the_pep6822_default_in_tests():
    # Sanity: the test interpreter enforces the documented default; without a
    # cap the whole point of these regression tests would be moot.
    assert sys.get_int_max_str_digits() == 4300


def test_4300_digit_boundary_aligns_and_round_trips():
    digits = "9" * 4300
    resp = post_raw(wrap(digits))
    assert resp.status_code == 200, resp.text
    step = parse(resp)["steps"][0]
    # Exact decimal value, and an int rather than a float/string.
    assert step["left"]["time"] == as_int(digits)
    assert isinstance(step["left"]["time"], int)
    # The raw response body carries the full digit run verbatim.
    assert digits in resp.text
    assert "Internal Server Error" not in resp.text


def test_4301_digit_report_returns_200_not_500():
    digits = "9" * 4301
    resp = post_raw(wrap(digits))
    assert resp.status_code == 200, resp.text
    body = parse(resp)
    assert body["steps"][0]["action"] == "right_gap"
    assert body["steps"][0]["left"]["time"] == as_int(digits)
    assert body["total_cost"] == 2000
    assert digits in resp.text


def test_far_over_threshold_timestamp_round_trips_exactly():
    digits = "1" + "234567890" * 1111  # 10000 digits
    assert len(digits) == 10000
    resp = post_raw(wrap(digits))
    assert resp.status_code == 200, resp.text
    assert parse(resp)["steps"][0]["left"]["time"] == as_int(digits)
    assert digits in resp.text


def test_huge_negative_timestamp_is_exact_int():
    digits = "-" + "8" * 5000
    resp = post_raw(wrap(digits))
    assert resp.status_code == 200, resp.text
    value = parse(resp)["steps"][0]["left"]["time"]
    assert value == as_int(digits)
    assert isinstance(value, int)
    assert digits.lstrip("-") in resp.text


def test_two_distinct_huge_times_are_not_false_duplicates():
    # Adjacent values that only differ in their last digit; parsed naively as
    # floats they would compare equal. Strictly increasing: ...9998 < ...9999.
    smaller = "9" * 4300 + "8"
    larger = "9" * 4301
    assert len(smaller) == len(larger) == 4301 and smaller < larger
    raw = (
        b'{"left":[{"time":' + smaller.encode() + b',"text":"a"},'
        b'{"time":' + larger.encode() + b',"text":"b"}],"right":[]}'
    )
    resp = post_raw(raw)
    assert resp.status_code == 200, resp.text
    times = [s["left"]["time"] for s in parse(resp)["steps"]]
    # Traceback is reverse chronological -> sort to compare input order.
    assert sorted(times) == sorted([as_int(smaller), as_int(larger)])


def test_genuine_duplicate_huge_time_is_one_structured_422():
    digits = "7" * 5000
    raw = (
        b'{"left":[{"time":' + digits.encode() + b',"text":"a"},'
        b'{"time":' + digits.encode() + b',"text":"b"}],"right":[]}'
    )
    resp = post_raw(raw)
    assert resp.status_code == 422
    body = parse(resp)
    assert set(body.keys()) == {"error", "path"}
    assert body["path"] == "left[1].time"
    # The message embeds the huge decimal without tripping the digit cap.
    assert digits in body["error"]
    assert "Internal Server Error" not in resp.text


def test_non_increasing_huge_time_message_is_safe():
    big = "5" * 4301
    small = "1" * 4301
    raw = (
        b'{"left":[{"time":' + big.encode() + b',"text":"a"},'
        b'{"time":' + small.encode() + b',"text":"b"}],"right":[]}'
    )
    resp = post_raw(raw)
    assert resp.status_code == 422
    body = parse(resp)
    assert body["path"] == "left[1].time"
    assert big in body["error"] and small in body["error"]


def test_huge_timestamps_flow_through_anchor_cost_and_serialization():
    # A forced anchor between two records whose times differ by exactly 3;
    # the anchor row must be computed, serialized and round-trip exactly.
    left_t = "9" * 4301
    right_t = "9" * 4300 + "6"  # ...9996 vs ...9999 -> |diff| = 3
    assert as_int(left_t) - as_int(right_t) == 3
    right = '[{"time":' + right_t + ',"text":"y"}]'
    resp = post_raw(wrap(left_t, anchors='[{"left":0,"right":0}]', right=right))
    assert resp.status_code == 200, resp.text
    body = parse(resp)
    assert len(body["steps"]) == 1
    step = body["steps"][0]
    assert step["anchor"] is True
    assert step["action"] == "match"
    assert step["cost"] == 3 + 3000  # texts differ -> mismatch penalty
    assert step["left"]["time"] == as_int(left_t)
    assert step["right"]["time"] == as_int(right_t)
    assert left_t in resp.text and right_t in resp.text


def test_huge_anchor_index_out_of_range_is_one_structured_422():
    # A 4301-digit anchor index is a valid integer but cannot be a valid
    # index; formatting it into the message must not raise past the handler.
    resp = post_raw(
        wrap(
            "1",
            anchors='[{"left":' + ("9" * 4301) + ',"right":0}]',
        )
    )
    assert resp.status_code == 422
    body = parse(resp)
    assert set(body.keys()) == {"error", "path"}
    assert body["path"] == "anchors[0].left"
    assert "Internal Server Error" not in resp.text


def test_no_timestamp_is_ever_serialized_as_a_float():
    digits = "9" * 4301
    resp = post_raw(wrap(digits))
    raw = resp.content.decode()
    assert '"time":' + digits in raw
    assert '"time":' + digits + ".0" not in raw
    assert "e+" not in raw and "E+" not in raw


def test_threshold_is_restored_after_each_request():
    post_raw(wrap("9" * 4301))
    # The cap is scoped to parsing/encoding; the process default is intact.
    assert sys.get_int_max_str_digits() == 4300
    try:
        json.loads("9" * 4301)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("global integer digit cap was left disabled")


def test_response_content_type_is_json():
    resp = post_raw(wrap("9" * 4301))
    assert resp.headers["content-type"] == "application/json"

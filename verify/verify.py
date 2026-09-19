#!/usr/bin/env python3
"""One-off acceptance check for the deployed Compose stack.

Runs against the LIVE containers (no mocks):

  * API health endpoint;
  * web container serves the built SPA and proxies /api to the API container;
  * a golden handoff alignment with exact steps, costs and tie-break order;
  * every cost rule (same-text |time diff|, mismatch +3000, gap 2000);
  * the single-failure contract for duplicates, over-limit and bad shapes;
  * human-confirmed anchors: pinned rows, segment optimality, single-error
    validation (out-of-range / reused / crossing) and legacy compatibility
    for requests without anchors;
  * arbitrary-precision timestamps: boundary (4300-digit) and over-threshold
    (4301+ digit) real API requests succeed with digit-for-digit fidelity,
    the anchor path computes and serializes huge integers exactly, and
    rejected huge inputs yield ONE structured 4xx — never HTTP 500.

Uses only the Python standard library so it can run in the slim API image.
Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# The API contract is arbitrary-precision `time` (see README).  This checker
# runs on stock Python 3.12, whose default int<->str cap of 4300 digits would
# otherwise make json.loads/json.dumps below blow up on the very responses
# this script exists to verify.
_set_int_max_str_digits = getattr(sys, "set_int_max_str_digits", None)
if _set_int_max_str_digits is not None:
    _set_int_max_str_digits(0)

API_URL = os.environ.get("API_URL", "http://api:8000")
WEB_URL = os.environ.get("WEB_URL", "http://web:80")

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def http(method: str, url: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def http_raw(url: str, body: str) -> tuple[int, str]:
    """POST a raw JSON text and return (status, raw response text).

    Needed for the arbitrary-precision checks: the exact digit sequence must
    be verified on the wire, not after a round trip through a serializer.
    """
    req = urllib.request.Request(
        url,
        data=body.encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read().decode()


def main() -> int:
    # 1. API health
    status, body = http("GET", f"{API_URL}/health")
    check("API /health returns 200 ok", status == 200 and body.get("status") == "ok")

    # 2. Web serves the SPA
    wstatus, html = get(f"{WEB_URL}/")
    check("web serves index.html", wstatus == 200 and "口译交接时间轴对齐" in html)

    # 3. Web nginx proxies /api through to the API container (integration!)
    pstatus, pbody = http(
        "POST",
        f"{WEB_URL}/api/align",
        {"left": [], "right": []},
    )
    check(
        "web /api proxy reaches FastAPI",
        pstatus == 200 and pbody.get("total_cost") == 0 and pbody.get("steps") == [],
        f"status={pstatus} body={pbody}",
    )

    # 4. Golden handoff
    left = [
        {"time": 0, "text": "各位媒体朋友下午好"},
        {"time": 4200, "text": "新产品将于下月上市"},
        {"time": 9000, "text": "感谢各位的提问"},
    ]
    right = [
        {"time": 150, "text": "各位媒体朋友下午好"},
        {"time": 4100, "text": "新产品将于下月上市"},
        {"time": 12000, "text": "交接后的补充记录"},
    ]
    status, body = http("POST", f"{API_URL}/api/align", {"left": left, "right": right})
    actions = [s["action"] for s in body["steps"]]
    costs = [s["cost"] for s in body["steps"]]
    check(
        "golden alignment actions + tie-break order",
        status == 200 and actions == ["match", "match", "right_gap", "left_gap"],
        f"actions={actions}",
    )
    # Action name must equal the side that is actually blank on that row.
    check(
        "gap action name matches the blank side (row 2 right_gap keeps left note)",
        body["steps"][2]["left"] == {"time": 9000, "text": "感谢各位的提问"}
        and body["steps"][2]["right"] is None,
    )
    check(
        "gap action name matches the blank side (row 3 left_gap keeps right note)",
        body["steps"][3]["left"] is None
        and body["steps"][3]["right"] == {"time": 12000, "text": "交接后的补充记录"},
    )
    check("golden per-step costs", costs == [150, 100, 2000, 2000], f"costs={costs}")
    check("golden total cost 4250", body.get("total_cost") == 4250)
    cumulative = [s["cumulative_cost"] for s in body["steps"]]
    check("cumulative costs replay to total", cumulative == [150, 250, 2250, 4250])
    check(
        "step costs sum to total",
        sum(costs) == body["total_cost"],
    )

    # 5a. Same-text match cost = absolute time difference
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [{"time": 1000, "text": "same"}],
            "right": [{"time": 1250, "text": "same"}],
        },
    )
    check("same-text match costs |time diff| (250)", body["total_cost"] == 250)

    # 5b. Different-text match cost = |diff| + 3000
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [{"time": 1000, "text": "a"}],
            "right": [{"time": 1000, "text": "b"}],
        },
    )
    check("different-text match costs |diff| + 3000", body["total_cost"] == 3000)

    # 5c. Only a left note: the RIGHT side is blank on that row -> right_gap,
    # costing exactly 2000 (action name = the side that is blank).
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {"left": [{"time": 1, "text": "a"}], "right": []},
    )
    check(
        "left-only note -> right_gap (right side blank) costs 2000",
        body["total_cost"] == 2000 and body["steps"][0]["action"] == "right_gap",
        f"body={body}",
    )
    check(
        "right_gap row carries the left note with right = null",
        body["steps"][0]["left"] == {"time": 1, "text": "a"}
        and body["steps"][0]["right"] is None,
    )

    # 5c-bis. Only a right note -> left_gap (left side blank).
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {"left": [], "right": [{"time": 1, "text": "a"}]},
    )
    check(
        "right-only note -> left_gap (left side blank)",
        body["steps"][0]["action"] == "left_gap"
        and body["steps"][0]["left"] is None
        and body["steps"][0]["right"] == {"time": 1, "text": "a"},
        f"body={body}",
    )

    # 5c-ter. Timestamps beyond Number.MAX_SAFE_INTEGER must keep exact
    # precision end to end: two adjacent increasing values that collide when
    # rounded to a JS double must NOT be reported as duplicates, and the
    # server-computed cost must reflect the exact 1ms difference.
    big_a = 9007199254740993  # 2^53+1
    big_b = 9007199254740995  # 2^53+3; JSON.parse rounds both together
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [
                {"time": big_a, "text": "交接点"},
                {"time": big_b, "text": "结束语"},
            ],
            "right": [{"time": big_a + 1, "text": "交接点"}],
        },
    )
    check(
        "huge increasing integers are not false duplicates (200 ok)",
        status == 200 and body.get("total_cost") is not None,
        f"status={status} body={body}",
    )
    check(
        "huge integer digits survive response exactly (|Δt| = 1)",
        body["steps"][0]["left"]["time"] == big_a
        and body["steps"][0]["right"]["time"] == big_a + 1
        and body["steps"][0]["cost"] == 1,
        f"step0={body.get('steps', [None])[0]}",
    )
    # A genuine duplicate at huge magnitude must still fail exactly once.
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [
                {"time": big_a, "text": "a"},
                {"time": big_a, "text": "b"},
            ],
            "right": [],
        },
    )
    check(
        "genuine duplicate huge integer still fails once at left[1].time",
        status == 422 and body.get("path") == "left[1].time",
        f"status={status} body={body}",
    )

    # 5d. Two gaps preferred to a 9000-time-difference match; tie at 4000
    # prefers the match.
    status, far = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [{"time": 0, "text": "s"}],
            "right": [{"time": 9000, "text": "s"}],
        },
    )
    check(
        "two gaps (4000) beat a 9000 match",
        far["total_cost"] == 4000
        and [s["action"] for s in far["steps"]] == ["right_gap", "left_gap"],
    )
    status, tie = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [{"time": 0, "text": "s"}],
            "right": [{"time": 4000, "text": "s"}],
        },
    )
    check(
        "tie at 4000 prefers the match",
        [s["action"] for s in tie["steps"]] == ["match"] and tie["total_cost"] == 4000,
    )

    # 6a. Duplicate time -> exactly one failure with first path
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": [
                {"time": 1, "text": "a"},
                {"time": 1, "text": "b"},
            ],
            "right": [{"time": "x", "text": "y"}],  # also wrong, must not be reported
        },
    )
    check(
        "duplicate time: single 422 at left[1].time",
        status == 422
        and set(body.keys()) == {"error", "path"}
        and body["path"] == "left[1].time",
        f"status={status} body={body}",
    )

    # 6b. Over the 200-item limit -> first over-limit index
    many = [{"time": i, "text": "x"} for i in range(201)]
    status, body = http(
        "POST", f"{API_URL}/api/align", {"left": many, "right": []}
    )
    check("201 items fail once at left[200]", status == 422 and body["path"] == "left[200]")

    # 6c. Non-increasing time, missing field, empty text, extra key
    cases = [
        (
            {"left": [{"time": 9, "text": "a"}, {"time": 8, "text": "b"}], "right": []},
            "left[1].time",
        ),
        (
            {"left": [{"text": "a"}], "right": []},
            "left[0].time",
        ),
        (
            {"left": [{"time": 1, "text": ""}], "right": []},
            "left[0].text",
        ),
        (
            {"left": [{"time": 1, "text": "a", "who": "z"}], "right": []},
            "left[0].who",
        ),
        (
            {"left": "not-an-array", "right": []},
            "left",
        ),
        (
            {"left": [], "right": [{"time": 1.5, "text": "a"}]},
            "right[0].time",
        ),
    ]
    for payload, expected_path in cases:
        status, body = http("POST", f"{API_URL}/api/align", payload)
        check(
            f"validation {expected_path} yields one failure",
            status == 422 and body.get("path") == expected_path and len(body) == 2,
            f"got status={status} body={body}",
        )

    # 7. Uniqueness: the same payload always produces an identical timeline.
    payload = {"left": left, "right": right}
    _, first = http("POST", f"{API_URL}/api/align", payload)
    for _ in range(3):
        _, again = http("POST", f"{API_URL}/api/align", payload)
    check("repeated runs return an identical unique timeline", again == first)

    # 8. Human-confirmed anchors (配对锚点).
    # 8a. Requests without anchors keep the legacy response exactly: no
    # `anchor` key anywhere, same golden timeline.
    status, plain = http("POST", f"{API_URL}/api/align", {"left": left, "right": right})
    check(
        "no-anchor response unchanged (no anchor key, total 4250)",
        status == 200
        and plain["total_cost"] == 4250
        and all("anchor" not in s for s in plain["steps"]),
        f"steps={plain.get('steps')}",
    )
    # 8b. An explicit empty anchors array is identical to no anchors.
    status, empty_anchors = http(
        "POST", f"{API_URL}/api/align", {"left": left, "right": right, "anchors": []}
    )
    check("empty anchors array equals the legacy response", empty_anchors == plain)

    # 8c. A legal anchor is pinned and flagged; the segments around it stay
    # optimal (this anchor matches the free optimum, so the total is 4250).
    status, anchored = http(
        "POST",
        f"{API_URL}/api/align",
        {"left": left, "right": right, "anchors": [{"left": 1, "right": 1}]},
    )
    check(
        "legal anchor pinned with total unchanged (4250)",
        status == 200 and anchored["total_cost"] == 4250,
        f"body={anchored}",
    )
    check(
        "anchor row flagged true, all others false",
        [s["anchor"] for s in anchored["steps"]] == [False, True, False, False],
    )
    check(
        "pinned row pairs the anchored records with its own cost (100)",
        anchored["steps"][1]["left"] == {"time": 4200, "text": "新产品将于下月上市"}
        and anchored["steps"][1]["right"] == {"time": 4100, "text": "新产品将于下月上市"}
        and anchored["steps"][1]["cost"] == 100,
    )
    check(
        "anchored steps replay to the same total",
        anchored["steps"][-1]["cumulative_cost"] == 4250
        and sum(s["cost"] for s in anchored["steps"]) == 4250,
    )

    # 8d. An anchor can override the free optimum; the forced pairing keeps
    # its ordinary cost and each segment is independently optimal.
    left2 = [{"time": 0, "text": "a"}, {"time": 5000, "text": "b"}]
    right2 = [{"time": 120, "text": "a"}, {"time": 4800, "text": "b"}]
    _, free2 = http("POST", f"{API_URL}/api/align", {"left": left2, "right": right2})
    _, pinned = http(
        "POST",
        f"{API_URL}/api/align",
        {"left": left2, "right": right2, "anchors": [{"left": 1, "right": 0}]},
    )
    check(
        "anchor overrides the free optimum (320 -> 11880)",
        free2["total_cost"] == 320 and pinned["total_cost"] == 11880,
        f"free={free2['total_cost']} pinned={pinned['total_cost']}",
    )
    check(
        "forced row is a flagged mismatch match costing 4880 + 3000",
        pinned["steps"][1]["anchor"] is True
        and pinned["steps"][1]["action"] == "match"
        and pinned["steps"][1]["cost"] == 7880,
    )
    # Segment optimality: head/tail segments cost exactly what the plain
    # endpoint computes for them in isolation.
    _, head = http("POST", f"{API_URL}/api/align", {"left": left2[:1], "right": []})
    _, tail = http("POST", f"{API_URL}/api/align", {"left": [], "right": right2[1:]})
    check(
        "segments around the anchor are independently optimal",
        head["total_cost"] + 7880 + tail["total_cost"] == pinned["total_cost"],
        f"head={head['total_cost']} tail={tail['total_cost']}",
    )

    # 8e. Anchor validation failures are single 422s at the first offender.
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": left,
            "right": right,
            "anchors": [{"left": 1, "right": 0}, {"left": 0, "right": 1}],
        },
    )
    check(
        "crossing anchors fail once at anchors[1].left",
        status == 422
        and set(body.keys()) == {"error", "path"}
        and body["path"] == "anchors[1].left",
        f"status={status} body={body}",
    )
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {
            "left": left,
            "right": right,
            "anchors": [{"left": 0, "right": 0}, {"left": 0, "right": 1}],
        },
    )
    check(
        "reused anchor index fails once at anchors[1].left",
        status == 422 and body.get("path") == "anchors[1].left",
        f"status={status} body={body}",
    )
    status, body = http(
        "POST",
        f"{API_URL}/api/align",
        {"left": left, "right": right, "anchors": [{"left": 9, "right": 0}]},
    )
    check(
        "out-of-range anchor fails once at anchors[0].left",
        status == 422 and body.get("path") == "anchors[0].left",
        f"status={status} body={body}",
    )

    # 8f. Removing the anchors restores the original result exactly.
    status, restored = http(
        "POST", f"{API_URL}/api/align", {"left": left, "right": right}
    )
    check("removing anchors restores the original result", restored == plain)

    # 9. Arbitrary-precision timestamps (README public contract).  Stock
    # Python 3.12 caps int<->str conversions at 4300 digits; the API disables
    # that cap, so boundary AND over-threshold values must align with their
    # decimal digits preserved exactly, while invalid huge values must fail
    # ONCE with a structured 4xx.  No request in this section may produce
    # HTTP 500 / "Internal Server Error".

    # 9a. Boundary value: exactly 4300 digits (CPython's default limit).
    boundary = "8" * 4300
    st, txt = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":' + boundary + ',"text":"x"}],"right":[]}',
    )
    body4300 = json.loads(txt) if st == 200 else {}
    check(
        "boundary 4300-digit timestamp aligns (200, digits exact)",
        st == 200
        and str(body4300["steps"][0]["left"]["time"]) == boundary
        and boundary in txt,
        f"status={st} text={txt[:120]}",
    )

    # 9b. The reported regression: a 4301-digit `time`, one left record,
    # empty right side — used to crash json.loads into a bare HTTP 500.
    over = "9" * 4301
    st, txt = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":' + over + ',"text":"x"}],"right":[]}',
    )
    body4301 = json.loads(txt) if st == 200 else {}
    check(
        "4301-digit regression request returns 200 (not 500)",
        st == 200 and "Internal Server Error" not in txt,
        f"status={st} text={txt[:120]}",
    )
    check(
        "4301-digit timestamp preserved digit-for-digit",
        st == 200
        and body4301["steps"][0]["action"] == "right_gap"
        and body4301["steps"][0]["cost"] == body4301["total_cost"] == 2000
        and str(body4301["steps"][0]["left"]["time"]) == over
        and over in txt,
        f"status={st} text={txt[:120]}",
    )

    # 9c. Arbitrary precision means no hidden ceiling just past the default.
    huge = "7" * 10_000
    st, txt = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":' + huge + ',"text":"x"}],"right":[]}',
    )
    check(
        "10000-digit timestamp also aligns (no hidden ceiling)",
        st == 200
        and str(json.loads(txt)["steps"][0]["left"]["time"]) == huge,
        f"status={st} text={txt[:120]}",
    )

    # 9d. Anchor path with over-threshold timestamps: the pinned row's cost
    # (|Δt| on huge ints) and the JSON serialization of every huge value
    # must stay exact.
    big = int(over)
    st, txt = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":%d,"text":"a"},{"time":%d,"text":"b"}],'
        '"right":[{"time":%d,"text":"a"},{"time":%d,"text":"b"}],'
        '"anchors":[{"left":1,"right":1}]}'
        % (big, big + 5000, big + 120, big + 4800),
    )
    anchored_big = json.loads(txt) if st == 200 else {}
    pinned = anchored_big.get("steps", [{}, {}])[1]
    check(
        "anchored alignment with 4301-digit timestamps stays exact",
        st == 200
        and pinned.get("anchor") is True
        and pinned.get("cost") == 200
        and str(pinned.get("left", {}).get("time")) == str(big + 5000)
        and str(pinned.get("right", {}).get("time")) == str(big + 4800)
        and anchored_big.get("total_cost")
        == sum(s["cost"] for s in anchored_big["steps"]),
        f"status={st} text={txt[:120]}",
    )

    # 9e. Invalid huge input: duplicate 4301-digit timestamps must fail ONCE
    # with a structured 4xx locating left[0].time's successor — the error
    # message itself embeds the huge value, exercising the formatting path.
    st, txt = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":' + over + ',"text":"a"},'
        '{"time":' + over + ',"text":"b"}],"right":[]}',
    )
    err = json.loads(txt) if st != 500 else {}
    check(
        "duplicate 4301-digit timestamps: single structured 4xx at left[1].time",
        st == 422
        and set(err.keys()) == {"error", "path"}
        and err["path"] == "left[1].time"
        and over in err["error"],
        f"status={st} text={txt[:120]}",
    )

    # 9f. A 4301-digit anchor index is out of range and must fail ONCE with a
    # structured 4xx before any alignment work happens.
    st, txt = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":1,"text":"a"}],"right":[{"time":2,"text":"b"}],'
        '"anchors":[{"left":' + over + ',"right":0}]}',
    )
    err = json.loads(txt) if st != 500 else {}
    check(
        "huge anchor index: single structured 4xx at anchors[0].left",
        st == 422
        and set(err.keys()) == {"error", "path"}
        and err["path"] == "anchors[0].left"
        and over in err["error"],
        f"status={st} text={txt[:120]}",
    )

    # 9g. Neither the success nor the failure path may ever answer with the
    # unstructured 500 body seen before the fix.
    st_ok, txt_ok = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":' + over + ',"text":"x"}],"right":[]}',
    )
    st_bad, txt_bad = http_raw(
        f"{API_URL}/api/align",
        '{"left":[{"time":' + over + ',"text":"a"},'
        '{"time":' + over + ',"text":"b"}],"right":[]}',
    )
    check(
        "no huge-timestamp response is HTTP 500 'Internal Server Error'",
        st_ok == 200
        and st_bad == 422
        and "Internal Server Error" not in txt_ok
        and "Internal Server Error" not in txt_bad,
        f"ok={st_ok} bad={st_bad}",
    )

    print(f"\n{checks - len(failures)}/{checks} checks passed.")
    if failures:
        print("FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("ACCEPTANCE VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

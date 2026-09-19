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
    for requests without anchors.

Uses only the Python standard library so it can run in the slim API image.
Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# This acceptance harness legitimately builds and parses responses carrying
# arbitrary-precision integer timestamps (the product contract), so the PEP
682
# digit cap is lifted for the harness itself.  The API process keeps its
# default 4300-digit safety threshold and lifts it only around JSON
# parse/serialize; these checks prove that contract end to end.
sys.set_int_max_str_digits(0)

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
    return http_raw(method, url, data)


def http_raw(method: str, url: str, data: bytes | None):
    """Send a pre-encoded body so huge integer digits stay byte-for-byte."""
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
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"__unparseable__": raw}


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read().decode()


def browser_roundtrip_checks() -> None:
    """Drive a real Chromium through the built SPA for the BigInt contract."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - image should provide it
        check("browser BigInt round trip (playwright import)", False, str(exc))
        return

    huge = "9" * 4301
    left_one = f'[{{"time":{huge},"text":"超长时间戳"}}]'
    captured: dict[str, object] = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = browser.new_page()

            page.on(
                "request",
                lambda req: captured.update(req_body=req.post_data)
                if "/api/align" in req.url and req.method == "POST"
                else None,
            )
            page.on(
                "response",
                lambda resp: captured.update(
                    resp_status=resp.status, resp_url=resp.url
                )
                if "/api/align" in resp.url and resp.request.method == "POST"
                else None,
            )

            page.goto(WEB_URL, wait_until="networkidle")
            page.get_by_test_id("input-left").fill(left_one)
            page.get_by_test_id("input-right").fill("[]")
            page.get_by_test_id("submit").click()

            # Success path: the timeline (not the error banner) appears.
            try:
                page.get_by_test_id("result-panel").wait_for(timeout=15000)
                panel_ok = True
            except Exception:
                panel_ok = False
            check("browser: 4301-digit submit shows a result (no error banner)", panel_ok)
            check(
                "browser: no error banner for the 4301-digit input",
                page.get_by_test_id("error-banner").count() == 0,
            )
            check(
                "browser: API call answered 200",
                captured.get("resp_status") == 200,
                f"status={captured.get('resp_status')}",
            )
            # The wire request body carried the exact digits (raw text, never
            # a re-serialized Number).
            req_body = captured.get("req_body") or ""
            check(
                "browser: request body carried all 4301 digits verbatim",
                huge in req_body,
                f"len={len(req_body)}",
            )

            # Rendered result read back INSIDE the JS engine: BigInt equality
            # and an exact string prove no Number truncation on result read.
            result = page.evaluate(
                """(digits) => {
                    const el = document.querySelector(
                        '[data-testid="timeline-row"] .time');
                    if (!el) return {found: false};
                    const text = el.textContent.replace(/\\s*ms$/, '').trim();
                    let bigOk = false;
                    try { bigOk = BigInt(text) === BigInt(digits); }
                    catch (e) { bigOk = false; }
                    // Demonstrate the Number hazard this path must avoid:
                    // Number rewrites these digits, BigInt does not.
                    const numberRewrites = String(Number(digits)) !== digits;
                    return {
                        found: true,
                        exact: text === digits,
                        lenOk: text.length === digits.length,
                        bigOk,
                        numberRewrites,
                    };
                }""",
                huge,
            )
            check(
                "browser: rendered timestamp matches input digit-for-digit",
                result.get("found") and result.get("exact") and result.get("lenOk"),
                str(result),
            )
            check(
                "browser: BigInt survives while Number would rewrite it",
                result.get("bigOk") and result.get("numberRewrites"),
                str(result),
            )
            check(
                "browser: one right_gap row (single left note, empty right)",
                page.get_by_test_id("timeline-row").count() == 1
                and page.get_by_test_id("timeline-row")
                .first.get_attribute("data-action") == "right_gap",
            )

            # Rejected-input UX: a duplicate over-threshold timestamp must
            # surface the SAME single located field error in the page (the UI
            # mirrors the server validation and may short-circuit before the
            # request) — never a generic service exception / 500.
            page.get_by_test_id("input-left").fill(
                f'[{{"time":{huge},"text":"a"}},{{"time":{huge},"text":"b"}}]'
            )
            page.get_by_test_id("submit").click()
            try:
                page.get_by_test_id("error-banner").wait_for(timeout=15000)
                banner = page.get_by_test_id("error-banner")
                banner_text = banner.text_content() or ""
                path_text = page.get_by_test_id("error-path").text_content() or ""
                rejected_ok = True
            except Exception:
                banner_text, path_text, rejected_ok = "", "", False
            check(
                "browser: rejected huge input shows located field error left[1].time",
                rejected_ok and "left[1].time" in path_text,
                f"path={path_text!r}",
            )
            check(
                "browser: rejection shows no timeline and no generic server error",
                rejected_ok
                and page.get_by_test_id("result-panel").count() == 0
                and "Internal Server Error" not in banner_text,
            )

            browser.close()
    except Exception as exc:
        check("browser BigInt round trip ran against the SPA", False, repr(exc))


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

    # 5c-quater. Python 3.12's PEP 682 integer digit cap (4300 decimal
    # digits by default) used to make json.loads raise a plain ValueError on
    # a 4301-digit timestamp, which escaped the JSONDecodeError-only handler
    # and surfaced as an unstructured HTTP 500.  The public contract is
    # arbitrary precision, so boundary AND over-threshold values must both
    # align over real HTTP with the digits unchanged.
    def post_bytes(body: bytes):
        """POST raw bytes, returning (status, parsed_json, raw_text)."""
        req = urllib.request.Request(
            f"{API_URL}/api/align",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(text), text
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return e.code, parsed, text

    def single_side(digits: str) -> bytes:
        return (
            b'{"left":[{"time":' + digits.encode() + b',"text":"x"}],"right":[]}'
        )

    # Exactly at the boundary (4300 digits): must be 200, not 500.
    boundary_digits = "7" * 4300
    status, body, text = post_bytes(single_side(boundary_digits))
    check(
        "4300-digit boundary timestamp aligns (200, exact digits)",
        status == 200
        and body is not None
        and body["steps"][0]["left"]["time"] == int(boundary_digits)
        and boundary_digits in text
        and "Internal Server Error" not in text,
        f"status={status} text={text[:120]}",
    )

    # One digit over the threshold (the reported 4301-digit regression):
    # single left record, empty right -> one right_gap row, total 2000, and
    # the returned timestamp decimal string matches the input digit-for-digit.
    report_digits = "9" * 4301
    status, body, text = post_bytes(single_side(report_digits))
    check(
        "4301-digit reported timestamp returns 200 (regression), not 500",
        status == 200 and "Internal Server Error" not in text,
        f"status={status} text={text[:120]}",
    )
    check(
        "4301-digit response keeps exact value, shape, action and cost",
        body is not None
        and len(body["steps"]) == 1
        and body["steps"][0]["action"] == "right_gap"
        and body["steps"][0]["right"] is None
        and body["steps"][0]["left"]["time"] == int(report_digits)
        and isinstance(body["steps"][0]["left"]["time"], int)
        and body["total_cost"] == 2000
        and report_digits in text,
        f"body={str(body)[:160]}",
    )

    # Far over the threshold (10000 digits): still exact arbitrary precision.
    far_digits = "1" + "234567890" * 1111
    assert len(far_digits) == 10000
    status, body, text = post_bytes(single_side(far_digits))
    check(
        "10000-digit timestamp aligns and round-trips exactly",
        status == 200
        and body is not None
        and body["steps"][0]["left"]["time"] == int(far_digits)
        and far_digits in text
        and "Internal Server Error" not in text,
        f"status={status}",
    )

    # An over-threshold timestamp must actually traverse the anchor cost
    # computation AND JSON response serialization: force one anchor between
    # two huge records differing by exactly 3; texts differ, so the pinned
    # match row costs |3| + 3000 = 3003 and both timestamps stay exact.
    left_big = "9" * 4301
    right_big = "9" * 4300 + "6"  # ...9996 vs ...9999 -> |diff| = 3
    assert int(left_big) - int(right_big) == 3
    anchor_body = (
        b'{"left":[{"time":' + left_big.encode() + b',"text":"x"}],'
        b'"right":[{"time":' + right_big.encode() + b',"text":"y"}],'
        b'"anchors":[{"left":0,"right":0}]}'
    )
    status, body, text = post_bytes(anchor_body)
    check(
        "huge timestamp through anchor cost + serialization returns 200",
        status == 200 and "Internal Server Error" not in text,
        f"status={status} text={text[:120]}",
    )
    check(
        "anchored huge row is a flagged exact match costing 3003",
        body is not None
        and len(body["steps"]) == 1
        and body["steps"][0]["anchor"] is True
        and body["steps"][0]["action"] == "match"
        and body["steps"][0]["cost"] == 3003
        and body["total_cost"] == 3003
        and body["steps"][0]["left"]["time"] == int(left_big)
        and body["steps"][0]["right"]["time"] == int(right_big)
        and left_big in text
        and right_big in text,
        f"body={str(body)[:200]}",
    )

    # A huge integer that violates a rule must still be a single structured
    # 4xx located at the offending field — never a 500.
    dup_digits = "5" * 5000
    dup_body = (
        b'{"left":[{"time":' + dup_digits.encode() + b',"text":"a"},'
        b'{"time":' + dup_digits.encode() + b',"text":"b"}],"right":[]}'
    )
    status, body, text = post_bytes(dup_body)
    check(
        "duplicate over-threshold time -> single structured 422 at left[1].time",
        status == 422
        and isinstance(body, dict)
        and set(body.keys()) == {"error", "path"}
        and body["path"] == "left[1].time"
        and "Internal Server Error" not in text,
        f"status={status} body={body}",
    )

    # A 4301-digit anchor index is a syntactically valid integer but can never
    # be an in-range index: same one-error, located 4xx contract.
    huge_index_body = (
        b'{"left":[{"time":1,"text":"x"}],"right":[{"time":2,"text":"y"}],'
        b'"anchors":[{"left":' + b"9" * 4301 + b',"right":0}]}'
    )
    status, body, text = post_bytes(huge_index_body)
    check(
        "over-threshold anchor index -> single structured 422 at anchors[0].left",
        status == 422
        and isinstance(body, dict)
        and set(body.keys()) == {"error", "path"}
        and body["path"] == "anchors[0].left"
        and "Internal Server Error" not in text,
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

    # 9. Real-browser BigInt round trip for the reported 4301-digit value.
    browser_roundtrip_checks()

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

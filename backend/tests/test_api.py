"""End-to-end API tests through FastAPI's ASGI stack (real request cycle)."""

import sys

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(payload, raw: bytes | None = None):
    if raw is not None:
        return client.post(
            "/api/align",
            content=raw,
            headers={"content-type": "application/json"},
        )
    return client.post("/api/align", json=payload)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_valid_alignment_end_to_end():
    payload = {
        "left": [
            {"time": 0, "text": "开场"},
            {"time": 5000, "text": "交接点"},
        ],
        "right": [
            {"time": 120, "text": "开场"},
            {"time": 4800, "text": "交接点"},
        ],
    }
    resp = post(payload)
    assert resp.status_code == 200
    data = resp.json()
    assert [s["action"] for s in data["steps"]] == ["match", "match"]
    assert data["steps"][0]["cost"] == 120
    assert data["steps"][1]["cost"] == 200
    assert data["total_cost"] == 320
    assert data["counts"]["match"] == 2


def test_malformed_json_is_single_failure():
    resp = post(None, raw=b"{not json")
    assert resp.status_code == 400
    body = resp.json()
    assert body["path"] == ""
    assert len(body["error"]) > 0


def test_root_not_object():
    resp = post([1, 2])
    assert resp.status_code == 422
    assert resp.json()["path"] == ""


def test_missing_side_reports_side_path():
    resp = post({"left": []})
    assert resp.status_code == 422
    assert resp.json()["path"] == "right"


def test_side_not_array():
    resp = post({"left": {}, "right": []})
    assert resp.status_code == 422
    assert resp.json()["path"] == "left"


def test_duplicate_time_single_error_with_path():
    payload = {
        "left": [{"time": 1, "text": "a"}, {"time": 1, "text": "b"}],
        "right": [],
    }
    resp = post(payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["path"] == "left[1].time"
    assert "递增" in body["error"]


def test_too_many_items_single_error():
    payload = {
        "left": [{"time": i, "text": "x"} for i in range(201)],
        "right": [],
    }
    resp = post(payload)
    assert resp.status_code == 422
    assert resp.json()["path"] == "left[200]"


def test_extra_field_single_error():
    payload = {
        "left": [{"time": 1, "text": "a", "who": "interpreter-1"}],
        "right": [],
    }
    resp = post(payload)
    assert resp.status_code == 422
    assert resp.json()["path"] == "left[0].who"


def test_empty_text_single_error():
    payload = {"left": [{"time": 1, "text": ""}], "right": []}
    resp = post(payload)
    assert resp.status_code == 422
    assert resp.json()["path"] == "left[0].text"


def test_left_error_takes_precedence_over_right():
    payload = {
        "left": [{"time": 2, "text": "a"}, {"time": 1, "text": "b"}],
        "right": [{"time": "x", "text": "y"}],
    }
    resp = post(payload)
    assert resp.status_code == 422
    assert resp.json()["path"] == "left[1].time"


def test_each_failure_is_one_error_object_only():
    resp = post(
        {"left": [{"time": "bad", "text": ""}], "right": "also bad"}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert set(body.keys()) == {"error", "path"}
    assert body["path"] == "left[0].time"


def test_empty_arrays_are_valid():
    resp = post({"left": [], "right": []})
    assert resp.status_code == 200
    assert resp.json()["total_cost"] == 0
    assert resp.json()["steps"] == []


def test_response_shape_contains_replay_fields():
    resp = post(
        {
            "left": [{"time": 0, "text": "a"}],
            "right": [{"time": 30, "text": "a"}],
        }
    )
    data = resp.json()
    step = data["steps"][0]
    assert set(step.keys()) == {
        "action",
        "left",
        "right",
        "cost",
        "cumulative_cost",
    }
    assert step["cumulative_cost"] == step["cost"] == data["total_cost"]
    assert data["costs"] == {"gap": 2000, "mismatch_penalty": 3000}


GOLDEN_LEFT = [
    {"time": 0, "text": "各位媒体朋友下午好"},
    {"time": 4200, "text": "新产品将于下月上市"},
    {"time": 9000, "text": "感谢各位的提问"},
]
GOLDEN_RIGHT = [
    {"time": 150, "text": "各位媒体朋友下午好"},
    {"time": 4100, "text": "新产品将于下月上市"},
    {"time": 12000, "text": "交接后的补充记录"},
]


class TestAnchorsApi:
    def test_request_without_anchors_keeps_legacy_response_exactly(self):
        resp = post({"left": GOLDEN_LEFT, "right": GOLDEN_RIGHT})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == 4250
        assert [s["action"] for s in data["steps"]] == [
            "match",
            "match",
            "right_gap",
            "left_gap",
        ]
        # No anchor key leaks into the legacy shape.
        for step in data["steps"]:
            assert set(step.keys()) == {
                "action",
                "left",
                "right",
                "cost",
                "cumulative_cost",
            }

    def test_empty_anchors_array_behaves_like_no_anchors(self):
        with_empty = post(
            {"left": GOLDEN_LEFT, "right": GOLDEN_RIGHT, "anchors": []}
        )
        without = post({"left": GOLDEN_LEFT, "right": GOLDEN_RIGHT})
        assert with_empty.status_code == 200
        assert with_empty.json() == without.json()

    def test_legal_anchor_is_pinned_and_segments_stay_optimal(self):
        resp = post(
            {
                "left": GOLDEN_LEFT,
                "right": GOLDEN_RIGHT,
                "anchors": [{"left": 1, "right": 1}],
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        # The golden optimum already pairs these two, so the total is
        # unchanged; the pinned row is now flagged as human-confirmed.
        assert data["total_cost"] == 4250
        assert [s["anchor"] for s in data["steps"]] == [False, True, False, False]
        pinned = data["steps"][1]
        assert pinned["action"] == "match"
        assert pinned["left"] == {"time": 4200, "text": "新产品将于下月上市"}
        assert pinned["right"] == {"time": 4100, "text": "新产品将于下月上市"}
        assert pinned["cost"] == 100
        # Replay still lands on the same total.
        assert data["steps"][-1]["cumulative_cost"] == data["total_cost"]
        assert sum(s["cost"] for s in data["steps"]) == data["total_cost"]

    def test_anchor_overrides_the_free_optimum(self):
        left = [{"time": 0, "text": "a"}, {"time": 5000, "text": "b"}]
        right = [{"time": 120, "text": "a"}, {"time": 4800, "text": "b"}]
        free = post({"left": left, "right": right}).json()
        assert free["total_cost"] == 320

        resp = post(
            {"left": left, "right": right, "anchors": [{"left": 1, "right": 0}]}
        )
        data = resp.json()
        assert [s["action"] for s in data["steps"]] == [
            "right_gap",
            "match",
            "left_gap",
        ]
        assert data["steps"][1]["anchor"] is True
        assert data["steps"][1]["cost"] == 4880 + 3000
        assert data["total_cost"] == 2000 + 7880 + 2000
        # Counts treat the pinned row as a normal match.
        assert data["counts"] == {"match": 1, "left_gap": 1, "right_gap": 1}

    def test_removing_anchors_restores_the_original_result(self):
        payload = {"left": GOLDEN_LEFT, "right": GOLDEN_RIGHT}
        original = post(payload).json()
        post({**payload, "anchors": [{"left": 0, "right": 0}]})
        restored = post(payload).json()
        assert restored == original

    def test_out_of_range_anchor_single_error(self):
        resp = post(
            {
                "left": GOLDEN_LEFT,
                "right": GOLDEN_RIGHT,
                "anchors": [{"left": 3, "right": 0}],
            }
        )
        assert resp.status_code == 422
        body = resp.json()
        assert set(body.keys()) == {"error", "path"}
        assert body["path"] == "anchors[0].left"
        assert "超出" in body["error"]

    def test_duplicate_anchor_index_single_error(self):
        resp = post(
            {
                "left": GOLDEN_LEFT,
                "right": GOLDEN_RIGHT,
                "anchors": [{"left": 0, "right": 0}, {"left": 0, "right": 1}],
            }
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["path"] == "anchors[1].left"
        assert "重复" in body["error"]

    def test_crossing_anchors_single_error(self):
        resp = post(
            {
                "left": GOLDEN_LEFT,
                "right": GOLDEN_RIGHT,
                "anchors": [{"left": 1, "right": 0}, {"left": 0, "right": 1}],
            }
        )
        assert resp.status_code == 422
        body = resp.json()
        assert set(body.keys()) == {"error", "path"}
        assert body["path"] == "anchors[1].left"
        assert "交叉" in body["error"]

    def test_anchor_shape_errors(self):
        cases = [
            ({"anchors": "yes"}, "anchors"),
            ({"anchors": [1]}, "anchors[0]"),
            ({"anchors": [{"left": 0}]}, "anchors[0].right"),
            ({"anchors": [{"left": 0, "right": 0, "x": 1}]}, "anchors[0].x"),
            ({"anchors": [{"left": 0, "right": True}]}, "anchors[0].right"),
        ]
        for extra, expected_path in cases:
            resp = post(
                {"left": GOLDEN_LEFT, "right": GOLDEN_RIGHT, **extra}
            )
            assert resp.status_code == 422
            body = resp.json()
            assert set(body.keys()) == {"error", "path"}
            assert body["path"] == expected_path

    def test_sequence_error_still_precedes_anchor_validation(self):
        resp = post(
            {
                "left": [{"time": 1, "text": "a"}, {"time": 1, "text": "b"}],
                "right": [],
                "anchors": [{"left": 99, "right": 99}],
            }
        )
        assert resp.status_code == 422
        assert resp.json()["path"] == "left[1].time"


class TestHugeTimestamps:
    """Arbitrary-precision ``time`` at and beyond CPython's default limit.

    Stock Python 3.12 caps int<->str conversions at 4300 digits; the app
    disables that cap (see ``app/__init__.py``) because the public contract
    is arbitrary precision.  Values at the boundary and far beyond it must
    align successfully with their decimal digits preserved exactly — and
    invalid huge values must still produce ONE structured 4xx, never an
    unstructured 500.
    """

    @staticmethod
    def raw_post(body: bytes):
        return client.post(
            "/api/align",
            content=body,
            headers={"content-type": "application/json"},
        )

    @staticmethod
    def single_left_body(digits: str) -> bytes:
        return (
            '{"left":[{"time":' + digits + ',"text":"x"}],"right":[]}'
        ).encode()

    def test_importing_the_app_disables_the_int_str_limit(self):
        # The mechanism behind the contract: no digit cap in this process.
        assert sys.get_int_max_str_digits() == 0

    def test_boundary_4300_digit_timestamp_accepted(self):
        digits = "8" * 4300  # exactly CPython's default limit
        resp = self.raw_post(self.single_left_body(digits))
        assert resp.status_code == 200
        assert resp.text != "Internal Server Error"
        step = resp.json()["steps"][0]
        assert step["action"] == "right_gap"
        assert step["left"]["time"] == int(digits)

    def test_over_threshold_4301_digit_timestamp_accepted(self):
        # The reported regression: 4301 digits used to crash json.loads.
        digits = "9" * 4301
        resp = self.raw_post(self.single_left_body(digits))
        assert resp.status_code == 200
        assert resp.text != "Internal Server Error"
        data = resp.json()
        assert data["steps"][0]["action"] == "right_gap"
        assert data["steps"][0]["cost"] == data["total_cost"] == 2000
        # Digit-for-digit identical in the parsed body AND on the wire.
        assert str(data["steps"][0]["left"]["time"]) == digits
        assert digits in resp.text

    def test_far_over_threshold_timestamp_has_no_hidden_ceiling(self):
        digits = "7" * 10_000
        resp = self.raw_post(self.single_left_body(digits))
        assert resp.status_code == 200
        assert str(resp.json()["steps"][0]["left"]["time"]) == digits

    def test_non_uniform_digits_preserved_exactly(self):
        digits = "1234567890" * 431  # 4310 digits, not a repeated digit
        resp = self.raw_post(self.single_left_body(digits))
        assert resp.status_code == 200
        assert str(resp.json()["steps"][0]["left"]["time"]) == digits

    def test_anchor_path_with_over_threshold_timestamps(self):
        # Anchor cost computation (|Δt| on huge ints) and serialization of
        # the huge values must both stay exact.
        big = int("9" * 4301)
        body = (
            '{"left":[{"time":%d,"text":"a"},{"time":%d,"text":"b"}],'
            '"right":[{"time":%d,"text":"a"},{"time":%d,"text":"b"}],'
            '"anchors":[{"left":1,"right":1}]}'
            % (big, big + 5000, big + 120, big + 4800)
        ).encode()
        resp = self.raw_post(body)
        assert resp.status_code == 200
        assert resp.text != "Internal Server Error"
        data = resp.json()
        pinned = data["steps"][1]
        assert pinned["anchor"] is True
        assert pinned["cost"] == 200  # |(big+5000) − (big+4800)|
        assert str(pinned["left"]["time"]) == str(big + 5000)
        assert str(pinned["right"]["time"]) == str(big + 4800)
        assert data["total_cost"] == sum(s["cost"] for s in data["steps"])

    def test_duplicate_huge_timestamps_fail_once_not_500(self):
        # _describe() formats the offending huge int into the message.
        digits = "9" * 4301
        body = (
            '{"left":[{"time":' + digits + ',"text":"a"},'
            '{"time":' + digits + ',"text":"b"}],"right":[]}'
        ).encode()
        resp = self.raw_post(body)
        assert resp.status_code == 422
        assert resp.text != "Internal Server Error"
        data = resp.json()
        assert set(data.keys()) == {"error", "path"}
        assert data["path"] == "left[1].time"
        assert digits in data["error"]

    def test_huge_anchor_index_fails_once_not_500(self):
        # validate_anchors() formats the offending huge index into the message.
        digits = "9" * 4301
        body = (
            '{"left":[{"time":1,"text":"a"}],"right":[{"time":2,"text":"b"}],'
            '"anchors":[{"left":' + digits + ',"right":0}]}'
        ).encode()
        resp = self.raw_post(body)
        assert resp.status_code == 422
        assert resp.text != "Internal Server Error"
        data = resp.json()
        assert set(data.keys()) == {"error", "path"}
        assert data["path"] == "anchors[0].left"
        assert digits in data["error"]

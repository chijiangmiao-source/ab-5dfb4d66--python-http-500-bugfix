"""Tests for structural validation and the single-error contract."""

from app.validation import MAX_ITEMS, validate_anchors, validate_sequence


def seq(*items):
    return list(items)


def n(t, text="x"):
    return {"time": t, "text": text}


def test_valid_sequences():
    assert validate_sequence([], "left") is None
    assert validate_sequence([n(1), n(2, "y"), n(10**9, "中文")], "left") is None


def test_not_an_array():
    assert validate_sequence({"time": 1}, "left") == "left"
    assert validate_sequence("nope", "right") == "right"


def test_too_many_items_points_at_first_over_limit():
    big = [n(i) for i in range(MAX_ITEMS + 1)]
    assert validate_sequence(big, "left") == f"left[{MAX_ITEMS}]"


def test_boundary_200_items_ok():
    assert validate_sequence([n(i) for i in range(MAX_ITEMS)], "left") is None


def test_item_not_object():
    assert validate_sequence([1], "left") == "left[0]"
    assert validate_sequence([n(1), "x"], "right") == "right[1]"


def test_missing_time():
    assert validate_sequence([{"text": "x"}], "left") == "left[0].time"


def test_time_must_be_integer():
    assert validate_sequence([n("1")], "left") == "left[0].time"
    assert validate_sequence([{"time": 1.5, "text": "x"}], "left") == "left[0].time"
    # bool is not a timestamp
    assert validate_sequence([{"time": True, "text": "x"}], "left") == "left[0].time"
    assert validate_sequence([{"time": None, "text": "x"}], "left") == "left[0].time"


def test_missing_or_empty_text():
    assert validate_sequence([{"time": 1}], "right") == "right[0].text"
    assert validate_sequence([{"time": 1, "text": ""}], "right") == "right[0].text"
    assert validate_sequence([{"time": 1, "text": 3}], "right") == "right[0].text"


def test_whitespace_only_text_is_non_empty_and_valid():
    assert validate_sequence([{"time": 1, "text": " "}], "left") is None


def test_duplicate_time_fails():
    assert validate_sequence([n(5), n(5)], "left") == "left[1].time"


def test_decreasing_time_fails_at_first_offender():
    assert validate_sequence([n(1), n(5), n(4), n(3)], "left") == "left[2].time"


def test_extra_field_rejected():
    item = {"time": 1, "text": "x", "source": "A"}
    assert validate_sequence([item], "left") == "left[0].source"


def test_only_first_error_is_reported():
    # Two errors at once (bad time AND empty text): time is checked first.
    bad = {"time": "no", "text": ""}
    assert validate_sequence([bad], "left") == "left[0].time"

    # Error at index 0 and 2: index 0 wins.
    data = [{"time": "x", "text": "y"}, n(1), n(1)]
    assert validate_sequence(data, "right") == "right[0].time"


class TestValidateAnchors:
    def test_valid_anchors(self):
        assert validate_anchors([], 3, 3) is None
        assert validate_anchors([{"left": 0, "right": 0}], 3, 3) is None
        assert (
            validate_anchors(
                [{"left": 0, "right": 1}, {"left": 2, "right": 2}], 3, 3
            )
            is None
        )

    def test_not_an_array(self):
        path, msg = validate_anchors({"left": 0}, 3, 3)
        assert path == "anchors"
        assert "数组" in msg

    def test_item_not_object(self):
        path, _ = validate_anchors([1], 3, 3)
        assert path == "anchors[0]"

    def test_missing_or_non_integer_index(self):
        path, _ = validate_anchors([{"left": 0}], 3, 3)
        assert path == "anchors[0].right"
        path, _ = validate_anchors([{"left": 0.5, "right": 0}], 3, 3)
        assert path == "anchors[0].left"
        # bool is not an index
        path, _ = validate_anchors([{"left": True, "right": 0}], 3, 3)
        assert path == "anchors[0].left"

    def test_extra_field_rejected(self):
        path, msg = validate_anchors([{"left": 0, "right": 0, "note": "x"}], 3, 3)
        assert path == "anchors[0].note"
        assert "多余字段" in msg

    def test_out_of_range_indices(self):
        path, msg = validate_anchors([{"left": 3, "right": 0}], 3, 3)
        assert path == "anchors[0].left"
        assert "超出" in msg
        path, _ = validate_anchors([{"left": 0, "right": -1}], 3, 3)
        assert path == "anchors[0].right"
        # Empty side: no anchor can reference it.
        path, _ = validate_anchors([{"left": 0, "right": 0}], 0, 3)
        assert path == "anchors[0].left"

    def test_reused_index_rejected_on_either_side(self):
        path, msg = validate_anchors(
            [{"left": 0, "right": 0}, {"left": 0, "right": 1}], 3, 3
        )
        assert path == "anchors[1].left"
        assert "重复" in msg and "anchors[0].left" in msg
        path, msg = validate_anchors(
            [{"left": 0, "right": 1}, {"left": 1, "right": 1}], 3, 3
        )
        assert path == "anchors[1].right"
        assert "重复" in msg

    def test_crossing_anchors_rejected(self):
        path, msg = validate_anchors(
            [{"left": 1, "right": 0}, {"left": 0, "right": 1}], 3, 3
        )
        assert path == "anchors[1].left"
        assert "交叉" in msg
        path, msg = validate_anchors(
            [{"left": 0, "right": 2}, {"left": 1, "right": 1}], 3, 3
        )
        assert path == "anchors[1].right"
        assert "交叉" in msg

    def test_only_first_anchor_error_is_reported(self):
        # anchors[1] is out of range AND anchors[2] crosses: anchors[1] wins.
        path, _ = validate_anchors(
            [
                {"left": 0, "right": 0},
                {"left": 9, "right": 9},
                {"left": 0, "right": 0},
            ],
            3,
            3,
        )
        assert path == "anchors[1].left"

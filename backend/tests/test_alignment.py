"""Unit tests for the DP alignment algorithm and its tie-breaking."""

import itertools
import random
from functools import lru_cache

from app.alignment import (
    GAP_COST,
    MISMATCH_PENALTY,
    align,
    align_with_anchors,
)


def note(time: int, text: str = "x"):
    return {"time": time, "text": text}


def test_empty_sequences_cost_zero():
    result = align([], [])
    assert result["total_cost"] == 0
    assert result["steps"] == []
    assert result["counts"] == {"match": 0, "left_gap": 0, "right_gap": 0}


def test_one_side_empty_all_gaps():
    # Only a left note: the RIGHT side is blank on that row -> right_gap.
    result = align([note(100, "a")], [])
    assert result["steps"][0]["action"] == "right_gap"
    assert result["steps"][0]["cost"] == GAP_COST
    assert result["steps"][0]["left"] == note(100, "a")
    assert result["steps"][0]["right"] is None
    assert result["total_cost"] == GAP_COST

    # Only a right note: the LEFT side is blank -> left_gap.
    result = align([], [note(100, "a")])
    assert result["steps"][0]["action"] == "left_gap"
    assert result["steps"][0]["left"] is None
    assert result["steps"][0]["right"] == note(100, "a")
    assert result["total_cost"] == GAP_COST


def test_identical_single_notes_match_with_time_diff():
    result = align([note(1000, "hello")], [note(1250, "hello")])
    assert result["steps"][0]["action"] == "match"
    assert result["steps"][0]["cost"] == 250
    assert result["total_cost"] == 250


def test_different_texts_add_penalty():
    result = align([note(1000, "hello")], [note(1000, "world")])
    step = result["steps"][0]
    assert step["action"] == "match"
    assert step["cost"] == MISMATCH_PENALTY
    assert result["total_cost"] == MISMATCH_PENALTY


def test_two_gaps_cheaper_than_big_time_difference():
    # |9000 - 0| = 9000 match > 2000 + 2000 = 4000 for a gap pair.
    result = align([note(0, "same")], [note(9000, "same")])
    actions = [s["action"] for s in result["steps"]]
    # The left note comes first chronologically; its row has the right side
    # blank (right_gap), then the right note sits on a left-blank row.
    assert actions == ["right_gap", "left_gap"]
    assert result["steps"][0]["left"] == note(0, "same")
    assert result["steps"][0]["right"] is None
    assert result["steps"][1]["left"] is None
    assert result["steps"][1]["right"] == note(9000, "same")
    assert result["total_cost"] == 2 * GAP_COST


def test_tie_match_vs_two_gaps_prefers_match():
    # Match 4000 ties with one left-gap + one right-gap (also 4000);
    # pairing wins the three-way tie.
    result = align([note(0, "same")], [note(4000, "same")])
    assert [s["action"] for s in result["steps"]] == ["match"]
    assert result["total_cost"] == 4000


def test_tie_left_gap_vs_right_gap_prefers_left_gap():
    # At cell (1,2) the left-blank and right-blank routes both cost 6000;
    # "left gap" wins per the tie-break order.
    left = [note(0, "a")]
    right = [note(4000, "a"), note(4100, "b")]
    result = align(left, right)
    # (1,1) is a triple tie at 4000 -> match; (1,2) is a gap tie at 6000
    # -> left_gap (left blank, carrying right note 4100).
    assert result["total_cost"] == 6000
    assert [s["action"] for s in result["steps"]] == ["match", "left_gap"]
    final = result["steps"][1]
    assert final["left"] is None
    assert final["right"] == note(4100, "b")


def test_gap_action_name_matches_actually_blank_side():
    # Invariant for every row: a left_gap row has no left note, and vice
    # versa, regardless of which side the whole sequence lives on.
    for lseq, rseq in [
        ([note(1, "a"), note(2, "b")], []),
        ([], [note(1, "a"), note(2, "b")]),
        ([note(0, "a"), note(9000, "b")], [note(100, "b"), note(8999, "a")]),
    ]:
        result = align(lseq, rseq)
        for step in result["steps"]:
            if step["action"] == "left_gap":
                assert step["left"] is None
                assert step["right"] is not None
            elif step["action"] == "right_gap":
                assert step["right"] is None
                assert step["left"] is not None
            else:
                assert step["left"] is not None and step["right"] is not None


def test_chronological_order_and_cumulative_cost():
    left = [note(0, "a"), note(5000, "b")]
    right = [note(100, "a"), note(6000, "b")]
    result = align(left, right)
    assert len(result["steps"]) == 2
    assert [s["left"]["time"] for s in result["steps"]] == [0, 5000]
    assert result["steps"][0]["cumulative_cost"] == 100
    assert result["steps"][1]["cumulative_cost"] == 1100
    assert result["total_cost"] == 1100


def test_steps_consume_each_note_once_without_crossing():
    left = [note(0, "a"), note(10000, "b")]
    right = [note(100, "b"), note(9999, "a")]
    result = align(left, right)

    matched_left = [s["left"]["time"] for s in result["steps"] if s["left"]]
    matched_right = [s["right"]["time"] for s in result["steps"] if s["right"]]
    assert matched_left == [0, 10000]  # every left note appears, in order
    assert matched_right == [100, 9999]
    # match + right_gap rows are exactly the rows that carry a left note;
    # match + left_gap rows are exactly those carrying a right note.
    assert result["counts"]["match"] + result["counts"]["right_gap"] == 2
    assert result["counts"]["match"] + result["counts"]["left_gap"] == 2
    assert sum(s["cost"] for s in result["steps"]) == result["total_cost"]


def test_large_inputs_200_items():
    left = [note(i * 1000, f"t{i}") for i in range(200)]
    right = [note(i * 1000 + 5, f"t{i}") for i in range(200)]
    result = align(left, right)
    assert result["counts"]["match"] == 200
    assert result["total_cost"] == 200 * 5


def test_constants():
    assert GAP_COST == 2000
    assert MISMATCH_PENALTY == 3000


def test_deterministic_unique_output():
    # Same input must always yield the same step sequence (uniqueness rule).
    left = [note(0, "a"), note(5000, "b"), note(9000, "c")]
    right = [note(10, "a"), note(4000, "x"), note(5200, "b")]
    first = align(left, right)
    for _ in range(5):
        again = align(left, right)
        assert again["steps"] == first["steps"]
        assert again["total_cost"] == first["total_cost"]


def test_optimal_cost_against_brute_force():
    """Exhaustive small-case comparison with an independent recursion."""

    def brute(left, right):
        m, n = len(left), len(right)

        @lru_cache(maxsize=None)
        def opt(i, j):
            if i == m and j == n:
                return 0
            best = float("inf")
            if i < m and j < n:
                l, r = left[i], right[j]
                c = abs(l["time"] - r["time"]) + (
                    0 if l["text"] == r["text"] else MISMATCH_PENALTY
                )
                best = min(best, c + opt(i + 1, j + 1))
            if i < m:
                best = min(best, GAP_COST + opt(i + 1, j))
            if j < n:
                best = min(best, GAP_COST + opt(i, j + 1))
            return best

        return opt(0, 0)

    cases = 0
    for m in range(0, 4):
        for n in range(0, 4):
            # Strictly increasing base spacing 5000; deltas in {0, 4000}
            # keep every side strictly increasing while creating ties.
            for dl in itertools.product((0, 4000), repeat=m):
                for dr in itertools.product((0, 4000), repeat=n):
                    for tl in itertools.product(("a", "b"), repeat=m):
                        for tr in itertools.product(("a", "b"), repeat=n):
                            left = [
                                note(i * 5000 + dl[i], tl[i]) for i in range(m)
                            ]
                            right = [
                                note(i * 5000 + dr[i], tr[i]) for i in range(n)
                            ]
                            result = align(left, right)
                            assert result["total_cost"] == brute(left, right)
                            cases += 1
    assert cases > 1000


def _brute_cost(left, right):
    """Independent recursion: unconstrained optimum of one segment."""

    @lru_cache(maxsize=None)
    def opt(i, j):
        if i == len(left) and j == len(right):
            return 0
        best = float("inf")
        if i < len(left) and j < len(right):
            l, r = left[i], right[j]
            c = abs(l["time"] - r["time"]) + (
                0 if l["text"] == r["text"] else MISMATCH_PENALTY
            )
            best = min(best, c + opt(i + 1, j + 1))
        if i < len(left):
            best = min(best, GAP_COST + opt(i + 1, j))
        if j < len(right):
            best = min(best, GAP_COST + opt(i, j + 1))
        return best

    return opt(0, 0)


def _anchor_cost(l, r):
    return abs(l["time"] - r["time"]) + (
        0 if l["text"] == r["text"] else MISMATCH_PENALTY
    )


class TestAlignWithAnchors:
    def test_empty_anchor_list_matches_plain_align(self):
        left = [note(0, "a"), note(5000, "b"), note(9000, "c")]
        right = [note(10, "a"), note(4000, "x"), note(5200, "b")]
        anchored = align_with_anchors(left, right, [])
        plain = align(left, right)
        assert anchored["total_cost"] == plain["total_cost"]
        assert [s["action"] for s in anchored["steps"]] == [
            s["action"] for s in plain["steps"]
        ]
        # ...but anchored responses always flag every row's provenance.
        assert all(s["anchor"] is False for s in anchored["steps"])

    def test_anchor_row_is_pinned_with_its_own_pairing_cost(self):
        # The free optimum pairs both notes (cost 120 + 200 = 320); pinning
        # left[1] to right[0] forces a mismatch match plus two gap rows.
        left = [note(0, "a"), note(5000, "b")]
        right = [note(120, "a"), note(4800, "b")]
        assert align(left, right)["total_cost"] == 320

        result = align_with_anchors(left, right, [{"left": 1, "right": 0}])
        assert [s["action"] for s in result["steps"]] == [
            "right_gap",
            "match",
            "left_gap",
        ]
        pinned = result["steps"][1]
        assert pinned["anchor"] is True
        assert pinned["left"] == note(5000, "b")
        assert pinned["right"] == note(120, "a")
        # Different texts: |5000 − 120| + 3000.
        assert pinned["cost"] == 4880 + MISMATCH_PENALTY
        assert result["steps"][0]["anchor"] is False
        assert result["steps"][2]["anchor"] is False
        assert result["total_cost"] == GAP_COST + 4880 + MISMATCH_PENALTY + GAP_COST

    def test_anchor_mismatch_pairing_still_adds_penalty(self):
        left = [note(1000, "hello")]
        right = [note(1000, "world")]
        result = align_with_anchors(left, right, [{"left": 0, "right": 0}])
        assert result["steps"][0]["cost"] == MISMATCH_PENALTY
        assert result["total_cost"] == MISMATCH_PENALTY

    def test_multiple_anchors_split_into_independent_segments(self):
        left = [note(0, "a"), note(4200, "b"), note(9000, "c")]
        right = [note(150, "a"), note(4100, "b"), note(12000, "d")]
        result = align_with_anchors(
            left, right, [{"left": 0, "right": 0}, {"left": 2, "right": 2}]
        )
        actions = [s["action"] for s in result["steps"]]
        assert actions == ["match", "match", "match"]
        assert [s["anchor"] for s in result["steps"]] == [True, False, True]
        # Middle segment is exactly the plain alignment of the middles.
        middle = align([note(4200, "b")], [note(4100, "b")])
        assert result["steps"][1]["cost"] == middle["steps"][0]["cost"] == 100
        assert result["total_cost"] == 150 + 100 + 3000 + MISMATCH_PENALTY

    def test_cumulative_cost_replays_to_total(self):
        left = [note(0, "a"), note(5000, "b"), note(9000, "c")]
        right = [note(10, "a"), note(4000, "x"), note(5200, "b")]
        result = align_with_anchors(left, right, [{"left": 2, "right": 1}])
        running = 0
        for step in result["steps"]:
            running += step["cost"]
            assert step["cumulative_cost"] == running
        assert running == result["total_cost"]
        assert result["counts"]["match"] == sum(
            1 for s in result["steps"] if s["action"] == "match"
        )

    def test_every_note_consumed_once_in_order(self):
        left = [note(i * 1000, f"l{i}") for i in range(6)]
        right = [note(i * 1000 + 3, f"r{i}") for i in range(5)]
        anchors = [{"left": 1, "right": 0}, {"left": 4, "right": 3}]
        result = align_with_anchors(left, right, anchors)
        assert [s["left"]["time"] for s in result["steps"] if s["left"]] == [
            n["time"] for n in left
        ]
        assert [s["right"]["time"] for s in result["steps"] if s["right"]] == [
            n["time"] for n in right
        ]
        anchor_rows = [s for s in result["steps"] if s["anchor"]]
        assert [(s["left"]["time"], s["right"]["time"]) for s in anchor_rows] == [
            (1000, 3),
            (4000, 3003),
        ]

    def test_anchored_cost_against_brute_force_segments(self):
        """Total must equal the sum of segment optima plus anchor costs."""
        rng = random.Random(20260917)
        for _ in range(300):
            m, n = rng.randint(0, 5), rng.randint(0, 5)
            left = [note(i * 5000 + rng.randint(0, 4000), rng.choice("ab"))
                    for i in range(m)]
            right = [note(j * 5000 + rng.randint(0, 4000), rng.choice("ab"))
                     for j in range(n)]
            # Random non-crossing anchors: equal-size subsets, both sorted.
            k = rng.randint(0, min(m, n))
            ls = sorted(rng.sample(range(m), k))
            rs = sorted(rng.sample(range(n), k))
            anchors = [{"left": l, "right": r} for l, r in zip(ls, rs)]

            expected = 0
            pl = pr = 0
            for l, r in zip(ls, rs):
                expected += _brute_cost(left[pl:l], right[pr:r])
                expected += _anchor_cost(left[l], right[r])
                pl, pr = l + 1, r + 1
            expected += _brute_cost(left[pl:], right[pr:])

            result = align_with_anchors(left, right, anchors)
            assert result["total_cost"] == expected
            assert sum(s["cost"] for s in result["steps"]) == expected
            assert [s["anchor"] for s in result["steps"]].count(True) == k

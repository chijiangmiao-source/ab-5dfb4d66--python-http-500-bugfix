"""Global sequence alignment by dynamic programming.

Given two interpreter note sequences::

    left:  [{"time": int, "text": str}, ...]   (m items)
    right: [{"time": int, "text": str}, ...]   (n items)

the three edit operations are:

* ``match``     pair left i-1 with right j-1.
                cost = |tL - tR|               when texts are equal
                cost = |tL - tR| + MISMATCH    when texts differ
* ``left_gap``  the LEFT side is blank at this row: left contributes
                nothing and right j-1 is kept (cost GAP)
* ``right_gap`` the RIGHT side is blank at this row: right contributes
                nothing and left i-1 is kept (cost GAP)

``align`` returns the unique, tie-broken minimum-cost path.  Where two or
more predecessors share the optimum they are ranked

    1. match      2. left_gap (left blank)      3. right_gap (right blank)

and if actions themselves tie (impossible between distinct actions, but kept
explicit) the predecessor coordinate that is lexicographically smallest
(``(i, j)``) wins.  Because every cell resolves ties deterministically, the
returned timeline is unique for any valid input.

No third-party matching/alignment library is used: this is plain DP over an
``(m+1) x (n+1)`` cost matrix with O(m*n) time and memory (m, n <= 200).

``align_with_anchors`` pins human-confirmed ``(left, right)`` index pairs as
forced match rows and reuses the same DP on the independent segments between
consecutive anchors.
"""

from __future__ import annotations

from typing import Any

GAP_COST = 2000
MISMATCH_PENALTY = 3000

ACTION_MATCH = "match"
ACTION_LEFT_GAP = "left_gap"
ACTION_RIGHT_GAP = "right_gap"

# Tie-break priority among the three actions (lower wins).
ACTION_PRIORITY = {
    ACTION_MATCH: 0,
    ACTION_LEFT_GAP: 1,
    ACTION_RIGHT_GAP: 2,
}


def _candidate_rank(total: int, action: str, pi: int, pj: int) -> tuple:
    """Sort key for predecessor candidates.

    Smaller total first, then the action priority (match, left gap, right
    gap), and finally the lexicographically smaller predecessor coordinate.
    """
    return (total, ACTION_PRIORITY[action], pi, pj)


def align(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    m, n = len(left), len(right)

    # dp[i][j] = minimum total cost aligning the first i left / j right notes.
    dp: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    # The action chosen to arrive at each cell (None for the start cell).
    chosen: list[list[str | None]] = [[None] * (n + 1) for _ in range(m + 1)]

    dp[0][0] = 0
    for i in range(1, m + 1):
        # Right side is empty along this border -> right_gap.
        dp[i][0] = dp[i - 1][0] + GAP_COST
        chosen[i][0] = ACTION_RIGHT_GAP
    for j in range(1, n + 1):
        # Left side is empty along this border -> left_gap.
        dp[0][j] = dp[0][j - 1] + GAP_COST
        chosen[0][j] = ACTION_LEFT_GAP

    for i in range(1, m + 1):
        li = left[i - 1]
        for j in range(1, n + 1):
            rj = right[j - 1]
            time_diff = abs(li["time"] - rj["time"])
            match_cost = time_diff + (
                0 if li["text"] == rj["text"] else MISMATCH_PENALTY
            )

            # Predecessors, already in tie-break priority order
            # (match, left-side gap, right-side gap). A move from (i, j-1)
            # consumes a right note, so the LEFT side is blank there.
            candidates = [
                (dp[i - 1][j - 1] + match_cost, ACTION_MATCH, i - 1, j - 1),
                (dp[i][j - 1] + GAP_COST, ACTION_LEFT_GAP, i, j - 1),
                (dp[i - 1][j] + GAP_COST, ACTION_RIGHT_GAP, i - 1, j),
            ]
            best = min(candidates, key=lambda c: _candidate_rank(c[0], c[1], c[2], c[3]))
            dp[i][j] = best[0]
            chosen[i][j] = best[1]

    # Trace back from (m, n) to (0, 0), then reverse to chronological order.
    steps_rev: list[dict[str, Any]] = []
    i, j = m, n
    while i > 0 or j > 0:
        action = chosen[i][j]
        if action == ACTION_MATCH:
            l, r = left[i - 1], right[j - 1]
            cost = abs(l["time"] - r["time"]) + (
                0 if l["text"] == r["text"] else MISMATCH_PENALTY
            )
            steps_rev.append(
                {
                    "action": ACTION_MATCH,
                    "left": {"time": l["time"], "text": l["text"]},
                    "right": {"time": r["time"], "text": r["text"]},
                    "cost": cost,
                }
            )
            i, j = i - 1, j - 1
        elif action == ACTION_LEFT_GAP:
            # Left side blank: the row carries the right-side note.
            r = right[j - 1]
            steps_rev.append(
                {
                    "action": ACTION_LEFT_GAP,
                    "left": None,
                    "right": {"time": r["time"], "text": r["text"]},
                    "cost": GAP_COST,
                }
            )
            j -= 1
        else:  # ACTION_RIGHT_GAP — right side blank, row carries left note
            l = left[i - 1]
            steps_rev.append(
                {
                    "action": ACTION_RIGHT_GAP,
                    "left": {"time": l["time"], "text": l["text"]},
                    "right": None,
                    "cost": GAP_COST,
                }
            )
            i -= 1

    steps = list(reversed(steps_rev))

    # Cumulative cost lets the UI replay the computation row by row.
    cumulative = 0
    for step in steps:
        cumulative += step["cost"]
        step["cumulative_cost"] = cumulative

    return {
        "steps": steps,
        "total_cost": dp[m][n],
        "counts": {
            "match": sum(1 for s in steps if s["action"] == ACTION_MATCH),
            "left_gap": sum(1 for s in steps if s["action"] == ACTION_LEFT_GAP),
            "right_gap": sum(1 for s in steps if s["action"] == ACTION_RIGHT_GAP),
        },
        "costs": {
            "gap": GAP_COST,
            "mismatch_penalty": MISMATCH_PENALTY,
        },
    }


def align_with_anchors(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    anchors: list[dict[str, int]],
) -> dict[str, Any]:
    """Align with human-confirmed anchor pairs pinned into the timeline.

    ``anchors`` must already be validated (see
    ``validation.validate_anchors``): each ``{"left": i, "right": j}`` forces
    a match row between those two records.  Because an alignment path is
    monotone, pinning a match splits both sequences into independent
    segments; each segment is aligned with the same DP as ``align``, so the
    result is optimal *subject to* the pinned pairs.  Every anchor row keeps
    its ordinary pairing cost (``|Δt|`` plus the mismatch penalty when the
    texts differ), so the returned ``total_cost`` is exactly the sum of the
    segment optima and the anchor costs, and replaying the steps row by row
    still lands on that total.

    Every step carries an ``anchor`` flag — ``True`` on the human-confirmed
    rows, ``False`` on the algorithm-generated ones — so the UI can tell the
    two apart.  (Requests without anchors keep the legacy response shape
    with no ``anchor`` key at all; see ``main.align_notes``.)
    """
    steps: list[dict[str, Any]] = []
    prev_l = prev_r = 0
    for anchor in anchors:
        li, ri = anchor["left"], anchor["right"]
        # Segment strictly before this anchor, aligned by the plain DP.
        for step in align(left[prev_l:li], right[prev_r:ri])["steps"]:
            step["anchor"] = False
            steps.append(step)
        # The pinned pair itself, charged its normal pairing cost.
        l, r = left[li], right[ri]
        cost = abs(l["time"] - r["time"]) + (
            0 if l["text"] == r["text"] else MISMATCH_PENALTY
        )
        steps.append(
            {
                "action": ACTION_MATCH,
                "left": {"time": l["time"], "text": l["text"]},
                "right": {"time": r["time"], "text": r["text"]},
                "cost": cost,
                "anchor": True,
            }
        )
        prev_l, prev_r = li + 1, ri + 1
    # Trailing segment after the last anchor.
    for step in align(left[prev_l:], right[prev_r:])["steps"]:
        step["anchor"] = False
        steps.append(step)

    # Cumulative cost lets the UI replay the computation row by row; the
    # segment-local values from ``align`` are recomputed across the whole
    # concatenated timeline.
    cumulative = 0
    for step in steps:
        cumulative += step["cost"]
        step["cumulative_cost"] = cumulative

    return {
        "steps": steps,
        "total_cost": cumulative,
        "counts": {
            "match": sum(1 for s in steps if s["action"] == ACTION_MATCH),
            "left_gap": sum(1 for s in steps if s["action"] == ACTION_LEFT_GAP),
            "right_gap": sum(1 for s in steps if s["action"] == ACTION_RIGHT_GAP),
        },
        "costs": {
            "gap": GAP_COST,
            "mismatch_penalty": MISMATCH_PENALTY,
        },
    }

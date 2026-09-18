/**
 * Helpers for human-confirmed pairing anchors (配对锚点).
 *
 * An anchor pins one left record to one right record by their indices; the
 * server then keeps those pairs fixed and re-aligns only the segments in
 * between.  The timeline rows do not carry record indices, so they are
 * derived here by walking the step list: `match`/`right_gap` rows consume
 * one left note, `match`/`left_gap` rows consume one right note.
 */

import type { AlignStep, AnchorPair } from "./types";

/** Record indices consumed by one timeline row (null when a side is blank). */
export interface RowIndices {
  left: number | null;
  right: number | null;
}

export function rowIndices(steps: AlignStep[]): RowIndices[] {
  let li = 0;
  let ri = 0;
  return steps.map((s) => ({
    left: s.left !== null ? li++ : null,
    right: s.right !== null ? ri++ : null,
  }));
}

export function isAnchorPair(
  anchors: AnchorPair[],
  left: number,
  right: number,
): boolean {
  return anchors.some((a) => a.left === left && a.right === right);
}

/**
 * Add or remove a pair.  The list is always kept sorted by (left, right) —
 * the order it is sent to the API — so a valid selection stays non-crossing
 * and the server's `anchors[k]` error paths line up with the on-page list.
 */
export function toggleAnchor(
  anchors: AnchorPair[],
  pair: AnchorPair,
): AnchorPair[] {
  const next = isAnchorPair(anchors, pair.left, pair.right)
    ? anchors.filter((a) => !(a.left === pair.left && a.right === pair.right))
    : [...anchors, pair];
  return next.sort((a, b) => a.left - b.left || a.right - b.right);
}

/**
 * `anchors[2].left` -> 2; null when the path does not point at a specific
 * anchor (e.g. the bare `anchors` path).
 */
export function anchorIndexFromPath(path: string): number | null {
  const m = /^anchors\[(\d+)\]/.exec(path);
  return m ? Number(m[1]) : null;
}

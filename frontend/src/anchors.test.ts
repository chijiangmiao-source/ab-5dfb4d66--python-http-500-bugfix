import { describe, expect, it } from "vitest";
import {
  anchorIndexFromPath,
  isAnchorPair,
  rowIndices,
  toggleAnchor,
} from "./anchors";
import type { AlignStep } from "./types";

function step(action: AlignStep["action"]): AlignStep {
  return {
    action,
    left: action === "left_gap" ? null : { time: 0, text: "x" },
    right: action === "right_gap" ? null : { time: 0, text: "x" },
    cost: 0,
    cumulative_cost: 0,
  };
}

describe("rowIndices", () => {
  it("assigns sequential record indices to each side independently", () => {
    const steps = [
      step("match"), // left 0, right 0
      step("right_gap"), // left 1
      step("left_gap"), // right 1
      step("match"), // left 2, right 2
    ];
    expect(rowIndices(steps)).toEqual([
      { left: 0, right: 0 },
      { left: 1, right: null },
      { left: null, right: 1 },
      { left: 2, right: 2 },
    ]);
  });

  it("handles empty timelines", () => {
    expect(rowIndices([])).toEqual([]);
  });
});

describe("toggleAnchor", () => {
  it("inserts new pairs sorted by (left, right)", () => {
    let anchors = toggleAnchor([], { left: 2, right: 2 });
    anchors = toggleAnchor(anchors, { left: 0, right: 1 });
    anchors = toggleAnchor(anchors, { left: 1, right: 0 });
    expect(anchors).toEqual([
      { left: 0, right: 1 },
      { left: 1, right: 0 },
      { left: 2, right: 2 },
    ]);
  });

  it("removes an existing pair", () => {
    const anchors = [
      { left: 0, right: 0 },
      { left: 1, right: 1 },
    ];
    expect(toggleAnchor(anchors, { left: 0, right: 0 })).toEqual([
      { left: 1, right: 1 },
    ]);
  });

  it("does not duplicate an existing pair", () => {
    const anchors = toggleAnchor([{ left: 0, right: 0 }], {
      left: 0,
      right: 0,
    });
    expect(anchors).toEqual([]);
  });
});

describe("isAnchorPair", () => {
  it("matches on both indices", () => {
    const anchors = [{ left: 1, right: 2 }];
    expect(isAnchorPair(anchors, 1, 2)).toBe(true);
    expect(isAnchorPair(anchors, 2, 1)).toBe(false);
    expect(isAnchorPair(anchors, 1, 1)).toBe(false);
  });
});

describe("anchorIndexFromPath", () => {
  it("parses the anchor position out of an API error path", () => {
    expect(anchorIndexFromPath("anchors[2].left")).toBe(2);
    expect(anchorIndexFromPath("anchors[0].right")).toBe(0);
    expect(anchorIndexFromPath("anchors[12]")).toBe(12);
  });

  it("returns null for whole-array or non-anchor paths", () => {
    expect(anchorIndexFromPath("anchors")).toBeNull();
    expect(anchorIndexFromPath("left[1].time")).toBeNull();
    expect(anchorIndexFromPath("")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import { MAX_ITEMS, validateSequence } from "./validation";

const n = (time: unknown, text: unknown = "x") => ({ time, text });

describe("validateSequence", () => {
  it("accepts empty array and normal data", () => {
    expect(validateSequence([])).toBeNull();
    expect(
      validateSequence([
        { time: 0, text: "a" },
        { time: 5, text: "中文" },
        { time: 9_000_000, text: " " },
      ]),
    ).toBeNull();
  });

  it("rejects non-arrays at root", () => {
    expect(validateSequence({})).toEqual({ path: "", message: expect.any(String) });
    expect(validateSequence("x")?.path).toBe("");
  });

  it("flags the first item past the 200 limit", () => {
    const ok = Array.from({ length: MAX_ITEMS }, (_, i) => n(i));
    expect(validateSequence(ok)).toBeNull();
    const tooMany = [...ok, n(200)];
    expect(validateSequence(tooMany)?.path).toBe(`[${MAX_ITEMS}]`);
  });

  it("rejects non-object items", () => {
    expect(validateSequence([1])?.path).toBe("[0]");
    expect(validateSequence([n(0), null])?.path).toBe("[1]");
    expect(validateSequence([n(0), []])?.path).toBe("[1]");
  });

  it("requires integer time", () => {
    expect(validateSequence([n("1")])?.path).toBe("[0].time");
    expect(validateSequence([n(1.5)])?.path).toBe("[0].time");
    expect(validateSequence([n(true)])?.path).toBe("[0].time");
    expect(validateSequence([{ text: "x" }])?.path).toBe("[0].time");
  });

  it("requires non-empty string text", () => {
    expect(validateSequence([{ time: 1 }])?.path).toBe("[0].text");
    expect(validateSequence([n(1, "")])?.path).toBe("[0].text");
    expect(validateSequence([n(1, 2)])?.path).toBe("[0].text");
  });

  it("rejects duplicate and decreasing times at first offender", () => {
    expect(validateSequence([n(5), n(5)])?.path).toBe("[1].time");
    expect(validateSequence([n(1), n(9), n(8)])?.path).toBe("[2].time");
  });

  it("accepts huge strictly increasing integers without precision loss", () => {
    // 2^53+1 and +3: ordinary JSON.parse rounds both to the same double.
    const a = 9007199254740993n;
    const b = 9007199254740995n;
    expect(validateSequence([n(a), n(b)])).toBeNull();
    // Two adjacent values that collide in double precision are still
    // distinct bigints and must NOT be reported as duplicates.
    expect(JSON.parse("[9007199254740993, 9007199254740995]")).toEqual([
      9007199254740992,
      9007199254740996,
    ]);
  });

  it("still flags duplicate huge integers", () => {
    const t = 9007199254740993n;
    expect(validateSequence([n(t), n(t)])?.path).toBe("[1].time");
  });

  it("rejects float times even though they are numbers", () => {
    expect(validateSequence([n(1.0), n(2.5)])?.path).toBe("[1].time");
  });

  it("rejects unknown fields at item level", () => {
    expect(
      validateSequence([{ time: 1, text: "a", source: "A" }])?.path,
    ).toBe("[0].source");
  });

  it("reports only one failure, the earliest one", () => {
    const issue = validateSequence([
      { time: "bad", text: "" },
      n(1),
      n(1),
    ]);
    expect(issue?.path).toBe("[0].time");
  });
});

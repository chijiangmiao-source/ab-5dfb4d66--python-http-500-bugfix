import { describe, expect, it, vi } from "vitest";
import { alignNotes, AlignRequestError, rootRawText } from "./api";

const alignedBody = {
  steps: [
    {
      action: "match",
      left: { time: 1, text: "a" },
      right: { time: 2, text: "a" },
      cost: 1,
      cumulative_cost: 1,
    },
  ],
  total_cost: 1,
  counts: { match: 1, left_gap: 0, right_gap: 0 },
  costs: { gap: 2000, mismatch_penalty: 3000 },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("rootRawText", () => {
  it("extracts the root value without surrounding whitespace", () => {
    expect(rootRawText(`  [1, 2]  `)).toBe("[1, 2]");
  });

  it("keeps large integer digits verbatim", () => {
    const raw = `[{"time": 9007199254740993, "text": "a"}]`;
    expect(rootRawText(raw)).toContain("9007199254740993");
  });
});

describe("alignNotes", () => {
  it("posts the raw array texts and returns the parsed result", async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) => jsonResponse(alignedBody),
    );
    const result = await alignNotes(
      `[{"time":1,"text":"a"}]`,
      `[{"time":2,"text":"a"}]`,
      [],
      fetchMock as unknown as typeof fetch,
    );
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/align");
    expect(init!.method).toBe("POST");
    // Body embeds the exact raw digits (no re-serialization/rounding).
    expect(init!.body).toBe(
      `{"left":[{"time":1,"text":"a"}],"right":[{"time":2,"text":"a"}]}`,
    );
    expect(result.total_cost).toBe(1n);
    expect(result.steps[0].cumulative_cost).toBe(1n);
  });

  it("forwards huge integer literals without rounding", async () => {
    let sentBody = "";
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      sentBody = init!.body as string;
      return jsonResponse({
        steps: [
          {
            action: "match",
            left: { time: 9007199254740993, text: "a" },
            right: { time: 9007199254740995, text: "a" },
            cost: 2,
            cumulative_cost: 2,
          },
        ],
        total_cost: 2,
        counts: { match: 1, left_gap: 0, right_gap: 0 },
        costs: { gap: 2000, mismatch_penalty: 3000 },
      });
    });
    await alignNotes(
      rootRawText(`[{"time": 9007199254740993, "text": "a"}]`),
      rootRawText(`[{"time": 9007199254740995, "text": "a"}]`),
      [],
      fetchMock as unknown as typeof fetch,
    );
    expect(sentBody).toContain("9007199254740993");
    expect(sentBody).toContain("9007199254740995");
  });

  it("surfaces a single error path on 422", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ error: "未严格递增", path: "left[2].time" }, 422),
    );
    await expect(
      alignNotes("[]", "[]", [], fetchMock as unknown as typeof fetch),
    ).rejects.toMatchObject({
      name: "AlignRequestError",
      path: "left[2].time",
      status: 422,
    });
  });

  it("turns network failure into an empty-path error", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    try {
      await alignNotes("[]", "[]", [], fetchMock as unknown as typeof fetch);
      throw new Error("should reject");
    } catch (e) {
      expect(e).toBeInstanceOf(AlignRequestError);
      expect((e as AlignRequestError).path).toBe("");
    }
  });

  it("wraps non-JSON responses", async () => {
    const fetchMock = vi.fn(
      async () => new Response("oops", { status: 502 }),
    );
    await expect(
      alignNotes("[]", "[]", [], fetchMock as unknown as typeof fetch),
    ).rejects.toBeInstanceOf(AlignRequestError);
  });

  it("parses a 4301-digit response integer as an exact bigint (no Number)", async () => {
    const digits = "9".repeat(4301);
    const raw =
      `{"steps":[{"action":"right_gap","left":{"time":${digits},"text":"x"},` +
      `"right":null,"cost":2000,"cumulative_cost":2000}],"total_cost":2000,` +
      `"counts":{"match":0,"left_gap":0,"right_gap":1},` +
      `"costs":{"gap":2000,"mismatch_penalty":3000}}`;
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(raw, { headers: { "Content-Type": "application/json" } }),
    );
    const result = await alignNotes(
      `[{"time":${digits},"text":"x"}]`,
      "[]",
      [],
      fetchMock as unknown as typeof fetch,
    );
    const time = result.steps[0].left!.time;
    expect(typeof time).toBe("bigint");
    expect(time.toString()).toBe(digits);
    // The request body kept the raw digits too.
    const [, sentInit] = fetchMock.mock.calls[0];
    expect(sentInit!.body as string).toContain(digits);
  });

  it("appends anchors to the request body only when non-empty", async () => {
    const bodies: string[] = [];
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(init!.body as string);
      return jsonResponse(alignedBody);
    });
    const f = fetchMock as unknown as typeof fetch;

    await alignNotes("[]", "[]", [{ left: 0, right: 1 }], f);
    expect(bodies[0]).toBe(
      `{"left":[],"right":[],"anchors":[{"left":0,"right":1}]}`,
    );

    // Empty selection -> byte-for-byte the legacy body (no anchors key).
    await alignNotes("[]", "[]", [], f);
    expect(bodies[1]).toBe(`{"left":[],"right":[]}`);
  });
});

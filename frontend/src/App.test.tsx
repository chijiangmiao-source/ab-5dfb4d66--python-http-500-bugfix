import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

afterEach(() => cleanup());

const okBody = {
  steps: [
    {
      action: "match",
      left: { time: 0, text: "各位媒体朋友下午好" },
      right: { time: 150, text: "各位媒体朋友下午好" },
      cost: 150,
      cumulative_cost: 150,
    },
    {
      action: "match",
      left: { time: 4200, text: "新产品将于下月上市" },
      right: { time: 4100, text: "新产品将于下月上市" },
      cost: 100,
      cumulative_cost: 250,
    },
    {
      action: "right_gap",
      left: { time: 9000, text: "感谢各位的提问" },
      right: null,
      cost: 2000,
      cumulative_cost: 2250,
    },
    {
      action: "left_gap",
      left: null,
      right: { time: 12000, text: "交接后的补充记录" },
      cost: 2000,
      cumulative_cost: 4250,
    },
  ],
  total_cost: 4250,
  counts: { match: 2, left_gap: 1, right_gap: 1 },
  costs: { gap: 2000, mismatch_penalty: 3000 },
};

/** Same timeline as okBody but with the first match pinned as an anchor. */
const anchoredBody = {
  ...okBody,
  steps: okBody.steps.map((s, i) => ({ ...s, anchor: i === 0 })),
};

function mockFetchOnce(body: unknown, status = 200) {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

describe("App", () => {
  it("renders both JSON inputs and sample data on load", () => {
    render(<App />);
    const left = screen.getByTestId("input-left") as HTMLTextAreaElement;
    const right = screen.getByTestId("input-right") as HTMLTextAreaElement;
    expect(left.value).toContain("各位媒体朋友下午好");
    expect(right.value).toContain("交接后的补充记录");
  });

  it("renders the timeline row by row with costs after a valid run", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(okBody));
    render(<App />);
    fireEvent.click(screen.getByTestId("submit"));

    await waitFor(() =>
      expect(screen.getByTestId("result-panel")).toBeInTheDocument(),
    );
    const rows = screen.getAllByTestId("timeline-row");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveAttribute("data-action", "match");
    // Row 2 keeps the left 9000 note with the right side blank -> right_gap;
    // row 3 keeps the right 12000 note with the left side blank -> left_gap.
    expect(rows[2]).toHaveAttribute("data-action", "right_gap");
    expect(rows[3]).toHaveAttribute("data-action", "left_gap");
    expect(screen.getByTestId("total-cost")).toHaveTextContent("4250");

    const costs = screen
      .getAllByTestId("step-cost")
      .map((el) => el.textContent);
    expect(costs).toEqual(["150", "100", "2000", "2000"]);
    const cumulative = screen
      .getAllByTestId("step-cumulative")
      .map((el) => el.textContent);
    expect(cumulative).toEqual(["150", "250", "2250", "4250"]);

    vi.unstubAllGlobals();
  });

  it("keeps the raw input and marks exactly the first error path from API", async () => {
    const fetchMock = mockFetchOnce(
      { error: "未严格递增", path: "left[1].time" },
      422,
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const left = screen.getByTestId("input-left") as HTMLTextAreaElement;
    const before = left.value;
    fireEvent.click(screen.getByTestId("submit"));

    await waitFor(() =>
      expect(screen.getByTestId("error-banner")).toBeInTheDocument(),
    );
    // Input preserved verbatim.
    expect((screen.getByTestId("input-left") as HTMLTextAreaElement).value).toBe(
      before,
    );
    // Exactly one error banner / path.
    expect(screen.getAllByTestId("error-path")).toHaveLength(1);
    expect(screen.getByTestId("error-path").textContent).toContain("left[1].time");
    // The mark is rendered inside the left textarea backdrop only.
    expect(screen.getByTestId("input-left-mark")).toBeInTheDocument();
    expect(screen.queryByTestId("input-right-mark")).toBeNull();
    expect(screen.queryByTestId("result-panel")).toBeNull();

    vi.unstubAllGlobals();
  });

  it("highlights malformed JSON locally without calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    render(<App />);
    fireEvent.change(screen.getByTestId("input-left"), {
      target: { value: `[{"time": 1, "text": "a"} ,]` },
    });
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getByTestId("error-banner")).toBeInTheDocument(),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("input-left-mark")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("rejects duplicate times locally with the first-offender path", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    render(<App />);
    fireEvent.change(screen.getByTestId("input-left"), {
      target: {
        value: JSON.stringify([
          { time: 1, text: "a" },
          { time: 1, text: "b" },
        ]),
      },
    });
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getByTestId("error-banner")).toBeInTheDocument(),
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("error-path").textContent).toContain("left[1].time");
    vi.unstubAllGlobals();
  });

  it("supports step-by-step replay of the timeline", async () => {
    vi.stubGlobal("fetch", mockFetchOnce(okBody));
    render(<App />);
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getAllByTestId("timeline-row")).toHaveLength(4),
    );

    // Walk back to the first step: one row, running total 150.
    fireEvent.click(screen.getByTestId("step-back"));
    fireEvent.click(screen.getByTestId("step-back"));
    fireEvent.click(screen.getByTestId("step-back"));
    expect(screen.getAllByTestId("timeline-row")).toHaveLength(1);
    expect(screen.getByTestId("replay-count").textContent).toContain("复算 1 / 4");
    expect(screen.getByTestId("total-cost").textContent).toBe("150");

    // Advance one step at a time.
    fireEvent.click(screen.getByTestId("step-next"));
    expect(screen.getAllByTestId("timeline-row")).toHaveLength(2);
    expect(screen.getByTestId("total-cost").textContent).toBe("250");
    fireEvent.click(screen.getByTestId("step-next"));
    expect(screen.getByTestId("total-cost").textContent).toBe("2250");
    vi.unstubAllGlobals();
  });

  it("clear button resets both inputs", () => {
    render(<App />);
    fireEvent.click(screen.getByTestId("clear"));
    expect((screen.getByTestId("input-left") as HTMLTextAreaElement).value).toBe("[]");
    expect((screen.getByTestId("input-right") as HTMLTextAreaElement).value).toBe("[]");
  });

  it("pins an anchor from a match row and re-computes with it", async () => {
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        const body = init!.body as string;
        bodies.push(body);
        const anchored = body.includes('"anchors"');
        return new Response(JSON.stringify(anchored ? anchoredBody : okBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    render(<App />);

    // First run: plain timeline, every row is algorithm-generated.
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getAllByTestId("timeline-row")).toHaveLength(4),
    );
    expect(bodies[0]).not.toContain("anchors");
    // Two match rows -> two anchor toggles; every row is algorithm-generated.
    expect(screen.getAllByTestId("anchor-toggle")).toHaveLength(2);
    expect(screen.getAllByTestId("origin-tag")[0]).toHaveTextContent("算法生成");

    // Pin the first match row (left[0] ↔ right[0]) as an anchor.
    fireEvent.click(screen.getAllByTestId("anchor-toggle")[0]);
    expect(screen.getByTestId("anchor-list")).toHaveTextContent("左[0] ↔ 右[0]");
    expect(screen.getByTestId("anchor-count")).toHaveTextContent("1");

    // Re-submit: the request carries the anchor, the confirmed row is
    // flagged ★ 人工确认 and the rest stay 算法生成.
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(
        screen.getByTestId("result-panel").querySelector("[data-anchor='true']"),
      ).not.toBeNull(),
    );
    expect(bodies[1]).toContain(`"anchors":[{"left":0,"right":0}]`);
    const rows = screen.getAllByTestId("timeline-row");
    expect(rows[0]).toHaveAttribute("data-anchor", "true");
    expect(rows[0]).toHaveTextContent("★ 人工确认");
    expect(rows[1]).not.toHaveAttribute("data-anchor");
    expect(rows[1]).toHaveTextContent("算法生成");
    expect(screen.getByTestId("total-cost")).toHaveTextContent("4250");
    vi.unstubAllGlobals();
  });

  it("keeps inputs and marks on an anchor error, shown next to the anchor", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = init!.body as string;
      if (body.includes('"anchors"')) {
        return new Response(
          JSON.stringify({
            error: "anchors[0].right 为 0，超出右侧记录索引范围（共 0 条）。",
            path: "anchors[0].right",
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify(okBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
    render(<App />);

    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getAllByTestId("timeline-row")).toHaveLength(4),
    );
    fireEvent.click(screen.getAllByTestId("anchor-toggle")[0]);

    // The user then empties the right side, making the anchor out of range.
    const leftBefore = (screen.getByTestId("input-left") as HTMLTextAreaElement).value;
    fireEvent.change(screen.getByTestId("input-right"), { target: { value: "[]" } });
    fireEvent.click(screen.getByTestId("submit"));

    await waitFor(() =>
      expect(screen.getByTestId("anchor-error")).toBeInTheDocument(),
    );
    // The error sits next to the offending anchor inside the panel...
    const item = screen.getByTestId("anchor-item");
    expect(item).toHaveTextContent("左[0] ↔ 右[0]");
    expect(item).toHaveTextContent("超出右侧记录索引范围");
    // ...the generic banner stays hidden, inputs and marks are preserved,
    // and no new (possibly misread-as-valid) timeline is shown.
    expect(screen.queryByTestId("error-banner")).toBeNull();
    expect(screen.queryByTestId("result-panel")).toBeNull();
    expect((screen.getByTestId("input-left") as HTMLTextAreaElement).value).toBe(
      leftBefore,
    );
    expect((screen.getByTestId("input-right") as HTMLTextAreaElement).value).toBe(
      "[]",
    );
    expect(screen.getByTestId("anchor-list")).toHaveTextContent("左[0] ↔ 右[0]");
    vi.unstubAllGlobals();
  });

  it("unmarking the anchor restores the anchorless request and result", async () => {
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        const body = init!.body as string;
        bodies.push(body);
        const anchored = body.includes('"anchors"');
        return new Response(JSON.stringify(anchored ? anchoredBody : okBody), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    render(<App />);

    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getAllByTestId("timeline-row")).toHaveLength(4),
    );
    fireEvent.click(screen.getAllByTestId("anchor-toggle")[0]);
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getAllByTestId("timeline-row")[0]).toHaveAttribute(
        "data-anchor",
        "true",
      ),
    );

    // Unmark via the panel's 取消 button, then recompute.
    fireEvent.click(screen.getByTestId("anchor-remove"));
    expect(screen.getByTestId("anchors-empty")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("submit"));
    await waitFor(() =>
      expect(screen.getAllByTestId("timeline-row")).toHaveLength(4),
    );
    expect(bodies[2]).not.toContain("anchors");
    expect(screen.queryByText("★ 人工确认")).toBeNull();
    expect(screen.getByTestId("total-cost")).toHaveTextContent("4250");
    vi.unstubAllGlobals();
  });

  it("handles huge increasing timestamps (beyond safe integers) without a false duplicate", async () => {
    let sentBody = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        sentBody = init!.body as string;
        // Response timestamps are small here; this case only checks the
        // request forwarding and that local validation does not flag the
        // two huge, double-colliding input times as duplicates.
        return new Response(
          JSON.stringify({
            steps: [
              {
                action: "right_gap",
                left: { time: 9007199254740992, text: "a" },
                right: null,
                cost: 2000,
                cumulative_cost: 2000,
              },
              {
                action: "right_gap",
                left: { time: 9007199254740996, text: "b" },
                right: null,
                cost: 2000,
                cumulative_cost: 4000,
              },
            ],
            total_cost: 4000,
            counts: { match: 0, left_gap: 0, right_gap: 2 },
            costs: { gap: 2000, mismatch_penalty: 3000 },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    render(<App />);
    fireEvent.change(screen.getByTestId("input-left"), {
      target: {
        value: `[\n  {"time": 9007199254740993, "text": "a"},\n  {"time": 9007199254740995, "text": "b"}\n]`,
      },
    });
    fireEvent.change(screen.getByTestId("input-right"), {
      target: { value: "[]" },
    });
    fireEvent.click(screen.getByTestId("submit"));

    await waitFor(() =>
      expect(screen.getByTestId("result-panel")).toBeInTheDocument(),
    );
    // No validation banner despite the double-precision collision.
    expect(screen.queryByTestId("error-banner")).toBeNull();
    // Exact digits were forwarded verbatim to the API.
    expect(sentBody).toContain("9007199254740993");
    expect(sentBody).toContain("9007199254740995");
    vi.unstubAllGlobals();
  });

  it("renders a 4301-digit timestamp exactly after a full submit round trip", async () => {
    // Beyond CPython's default 4300-digit int<->str limit: input, request
    // forwarding, response parsing and rendering must never route the value
    // through a JavaScript Number.
    const digits = "9".repeat(4301);
    let sentBody = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        sentBody = init!.body as string;
        return new Response(
          `{"steps":[{"action":"right_gap","left":{"time":${digits},"text":"x"},` +
            `"right":null,"cost":2000,"cumulative_cost":2000}],` +
            `"total_cost":2000,"counts":{"match":0,"left_gap":0,"right_gap":1},` +
            `"costs":{"gap":2000,"mismatch_penalty":3000}}`,
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    render(<App />);
    fireEvent.change(screen.getByTestId("input-left"), {
      target: { value: `[{"time": ${digits}, "text": "x"}]` },
    });
    fireEvent.change(screen.getByTestId("input-right"), {
      target: { value: "[]" },
    });
    fireEvent.click(screen.getByTestId("submit"));

    await waitFor(() =>
      expect(screen.getByTestId("result-panel")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("error-banner")).toBeNull();
    // The exact digits left the browser verbatim...
    expect(sentBody).toContain(digits);
    // ...and every one of the 4301 digits is rendered back, not a rounded
    // double (which would show "1e+4301"-style or altered trailing digits).
    const row = screen.getByTestId("timeline-row");
    expect(row.textContent).toContain(`${digits} ms`);
    expect(screen.getByTestId("total-cost")).toHaveTextContent("2000");
    vi.unstubAllGlobals();
  });
});

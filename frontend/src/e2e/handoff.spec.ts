import { expect, test } from "@playwright/test";

import { parseLocated } from "../jsonLocations";

/**
 * Real full-stack integration: these tests drive a browser against the built
 * frontend talking to the live FastAPI process (same-origin via the preview
 * proxy, just like the Docker Compose deployment).
 */

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("sample handoff produces the unique optimal timeline", async ({ page }) => {
  await expect(page.getByTestId("input-left")).toContainText("各位媒体朋友下午好");

  await page.getByTestId("submit").click();

  await expect(page.getByTestId("result-panel")).toBeVisible();
  const rows = page.getByTestId("timeline-row");
  await expect(rows).toHaveCount(4);

  await expect(rows.nth(0)).toHaveAttribute("data-action", "match");
  await expect(rows.nth(1)).toHaveAttribute("data-action", "match");
  // At the tail, left_gap and right_gap routes tie at 4250; the tie-break
  // (left gap before right gap during traceback) fixes this exact order.
  await expect(rows.nth(2)).toHaveAttribute("data-action", "right_gap");
  await expect(rows.nth(3)).toHaveAttribute("data-action", "left_gap");

  await expect(page.getByTestId("step-cost").nth(0)).toHaveText("150");
  await expect(page.getByTestId("step-cost").nth(1)).toHaveText("100");
  await expect(page.getByTestId("step-cost").nth(2)).toHaveText("2000");
  await expect(page.getByTestId("step-cumulative").nth(3)).toHaveText("4250");
  await expect(page.getByTestId("total-cost")).toHaveText("4250");

  // The per-step costs really do add up to the advertised total.
  const costs = await page.getByTestId("step-cost").allInnerTexts();
  expect(costs.map(Number).reduce((a, b) => a + b, 0)).toBe(4250);
});

test("timeline can be replayed one step at a time", async ({ page }) => {
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("result-panel")).toBeVisible();

  await page.getByTestId("step-back").click();
  await page.getByTestId("step-back").click();
  await page.getByTestId("step-back").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(1);
  await expect(page.getByTestId("replay-count")).toContainText("复算 1 / 4 步");
  await expect(page.getByTestId("total-cost")).toHaveText("150");

  await page.getByTestId("step-next").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(2);
  await expect(page.getByTestId("total-cost")).toHaveText("250");
});

test("duplicate time yields one failure, keeps input, marks first path", async ({
  page,
}) => {
  const bad = JSON.stringify([
    { time: 100, text: "第一段" },
    { time: 100, text: "重复时间" },
  ]);
  await page.getByTestId("input-left").fill(bad);
  await page.getByTestId("input-right").fill("[]");

  await page.getByTestId("submit").click();

  const banner = page.getByTestId("error-banner");
  await expect(banner).toBeVisible();
  await expect(page.getByTestId("error-path")).toHaveText("left[1].time ");
  // Exactly one failure is displayed.
  await expect(page.getByTestId("error-banner")).toHaveCount(1);

  // Original input preserved verbatim.
  await expect(page.getByTestId("input-left")).toHaveValue(bad);
  // The offending member is highlighted in the source textarea.
  await expect(page.getByTestId("input-left-mark")).toBeVisible();
  // No result timeline for an invalid run.
  await expect(page.getByTestId("result-panel")).toHaveCount(0);
});

test("non-increasing time and over-limit arrays each fail once with a path", async ({
  request,
}) => {
  // Verify the live API contract directly as part of the e2e stack.
  const resp = await request.post("/api/align", {
    data: {
      left: [
        { time: 5, text: "a" },
        { time: 4, text: "b" },
      ],
      right: [],
    },
  });
  expect(resp.status()).toBe(422);
  expect(await resp.json()).toEqual({
    error: expect.stringContaining("递增"),
    path: "left[1].time",
  });

  const many = Array.from({ length: 201 }, (_, i) => ({ time: i, text: "x" }));
  const resp2 = await request.post("/api/align", {
    data: { left: many, right: [] },
  });
  expect(resp2.status()).toBe(422);
  expect((await resp2.json()).path).toBe("left[200]");
});

test("malformed JSON is reported with line and column and highlighted", async ({
  page,
}) => {
  await page
    .getByTestId("input-right")
    .fill('[\n  {"time": 1, "text": "a"},\n  ,\n]');
  await page.getByTestId("submit").click();
  const banner = page.getByTestId("error-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("第 3 行");
  await expect(page.getByTestId("input-right-mark")).toBeVisible();
  // Raw input stays intact for the user to fix.
  await expect(page.getByTestId("input-right")).toContainText(",");
});

test("empty arrays are a valid zero-cost handoff", async ({ page }) => {
  await page.getByTestId("clear").click();
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("result-panel")).toBeVisible();
  await expect(page.getByTestId("timeline-row")).toHaveCount(0);
  await expect(page.getByTestId("total-cost")).toHaveText("0");
});

test("huge increasing timestamps (past safe-integer range) are not false duplicates", async ({
  page,
}) => {
  // 2^53+1 and +3 collide when rounded to a JS double; the fill strings keep
  // the exact digits verbatim (a numeric literal here would itself round).
  await page.getByTestId("input-left").fill(
    `[{"time":9007199254740993,"text":"交接点"},{"time":9007199254740995,"text":"结束语"}]`,
  );
  await page.getByTestId("input-right").fill(
    `[{"time":9007199254740994,"text":"交接点"}]`,
  );
  await page.getByTestId("submit").click();

  await expect(page.getByTestId("result-panel")).toBeVisible();
  await expect(page.getByTestId("error-banner")).toHaveCount(0);
  const rows = page.getByTestId("timeline-row");
  await expect(rows).toHaveCount(2);
  // Exact large digits are rendered, not double-rounded 9007199254740992.
  await expect(rows.nth(0)).toContainText("9007199254740993 ms");
  await expect(rows.nth(0)).toContainText("9007199254740994 ms");
  // Same text, |1ms| difference -> single-step cost exactly 1.
  await expect(page.getByTestId("step-cost").nth(0)).toHaveText("1");
});

test("only-left notes label the right side as blank and carry content on the left", async ({
  page,
}) => {
  await page.getByTestId("input-left").fill(
    JSON.stringify([{ time: 100, text: "仅左侧记录" }]),
  );
  await page.getByTestId("input-right").fill("[]");
  await page.getByTestId("submit").click();

  await expect(page.getByTestId("result-panel")).toBeVisible();
  const row = page.getByTestId("timeline-row");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-action", "right_gap");
  // Left cell shows the note, right cell shows the empty marker.
  const cells = row.locator("td");
  await expect(cells.nth(1)).toContainText("仅左侧记录");
  await expect(cells.nth(3)).toContainText("∅");
  await expect(page.getByTestId("step-cost")).toHaveText("2000");
});

test("a 4301-digit timestamp (past Python's int digit cap) round-trips exactly", async ({
  page,
  request,
}) => {
  // The reported HTTP 500 input: one left record whose time has 4301 decimal
  // digits, empty right. It must align (200) and come back digit-for-digit.
  const digits = "9".repeat(4301);

  // --- Real HTTP contract through the same-origin proxy ---
  // Send the raw digits as the request body: Playwright's object-form `data`
  // would re-serialize through JS Number and lose the precision.
  const rawResp = await request.post("/api/align", {
    headers: { "Content-Type": "application/json" },
    data: `{"left":[{"time":${digits},"text":"x"}],"right":[]}`,
  });
  expect(rawResp.status()).toBe(200);
  const rawText = await rawResp.text();
  expect(rawText).not.toContain("Internal Server Error");
  expect(rawText).toContain(digits);
  // Parsed with the BigInt-aware parser, the value is exactly unchanged.
  const parsed = parseLocated(rawText).value as {
    steps: Array<{ left: { time: bigint } }>;
    total_cost: bigint;
  };
  expect(parsed.steps[0].left.time.toString()).toBe(digits);
  expect(parsed.total_cost).toBe(2000n);

  // --- Browser input -> submit -> result read round trip ---
  await page.getByTestId("input-left").fill(`[{"time":${digits},"text":"x"}]`);
  await page.getByTestId("input-right").fill("[]");
  await page.getByTestId("submit").click();

  await expect(page.getByTestId("result-panel")).toBeVisible();
  await expect(page.getByTestId("error-banner")).toHaveCount(0);
  const row = page.getByTestId("timeline-row");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-action", "right_gap");
  // All 4301 digits rendered, not a Number-rounded/rewritten value.
  await expect(row.locator(".time")).toContainText(digits);
  const rendered = await row.locator(".time").innerText();
  expect(rendered.replace(/\s*ms$/, "").trim()).toBe(digits);
  // Number would rewrite these digits — the app must not have.
  expect(String(Number(digits))).not.toBe(digits);
});

test("a rejected 4301-digit duplicate shows the located field error, not a 500", async ({
  page,
}) => {
  const digits = "5".repeat(5000);
  await page
    .getByTestId("input-left")
    .fill(`[{"time":${digits},"text":"a"},{"time":${digits},"text":"b"}]`);
  await page.getByTestId("input-right").fill("[]");
  await page.getByTestId("submit").click();

  const banner = page.getByTestId("error-banner");
  await expect(banner).toBeVisible();
  await expect(page.getByTestId("error-path")).toHaveText("left[1].time ");
  await expect(banner).not.toContainText("Internal Server Error");
  await expect(page.getByTestId("result-panel")).toHaveCount(0);
});

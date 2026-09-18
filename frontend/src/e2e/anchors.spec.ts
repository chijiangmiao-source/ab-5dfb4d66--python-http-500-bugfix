import { expect, test } from "@playwright/test";

/**
 * Full-stack coverage for human-confirmed pairing anchors (配对锚点):
 * marking/unmarking in the timeline, recompute with pinned pairs, the
 * per-anchor error contract, and the legacy no-anchor compatibility.
 */

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("marking an anchor pins the row and keeps the same total on replay", async ({
  page,
}) => {
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(4);
  // No anchor is pinned initially: every row is algorithm-generated.
  await expect(page.getByTestId("origin-tag").nth(0)).toHaveText("算法生成");
  await expect(page.getByTestId("anchors-empty")).toBeVisible();

  // Pin the first match row (left[0] ↔ right[0]).
  await page.getByTestId("anchor-toggle").nth(0).click();
  await expect(page.getByTestId("anchor-item")).toHaveCount(1);
  await expect(page.getByTestId("anchor-list")).toContainText("左[0] ↔ 右[0]");

  await page.getByTestId("submit").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(4);

  // The pinned row is clearly marked as human-confirmed; the rest are not.
  const rows = page.getByTestId("timeline-row");
  await expect(rows.nth(0)).toHaveAttribute("data-anchor", "true");
  await expect(rows.nth(0)).toContainText("★ 人工确认");
  await expect(rows.nth(1)).not.toHaveAttribute("data-anchor");
  await expect(rows.nth(1)).toContainText("算法生成");
  await expect(rows.nth(0).getByTestId("anchor-toggle")).toHaveText("取消锚点");

  // This anchor matches the free optimum, so the total is unchanged and the
  // step-by-step replay still lands on it.
  await expect(page.getByTestId("total-cost")).toHaveText("4250");
  await page.getByTestId("step-back").click();
  await expect(page.getByTestId("total-cost")).toHaveText("2250");
  await page.getByTestId("step-next").click();
  await expect(page.getByTestId("total-cost")).toHaveText("4250");
});

test("a pinned anchor survives a time drift that would undo it", async ({
  page,
}) => {
  // Free alignment pairs the two notes (cost 50).
  await page.getByTestId("input-left").fill(
    JSON.stringify([{ time: 0, text: "交接点" }]),
  );
  await page.getByTestId("input-right").fill(
    JSON.stringify([{ time: 50, text: "交接点" }]),
  );
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("total-cost")).toHaveText("50");

  // The leader confirms the pair as an anchor.
  await page.getByTestId("anchor-toggle").nth(0).click();
  await expect(page.getByTestId("anchor-list")).toContainText("左[0] ↔ 右[0]");

  // A later correction shifts the right note far away; the free optimum
  // would now split the pair into two gap rows (4000 < 9000)...
  await page.getByTestId("input-right").fill(
    JSON.stringify([{ time: 9000, text: "交接点" }]),
  );
  await page.getByTestId("submit").click();

  // ...but the human-confirmed anchor stays pinned as a ★ match row.
  const rows = page.getByTestId("timeline-row");
  await expect(rows).toHaveCount(1);
  await expect(rows.nth(0)).toHaveAttribute("data-action", "match");
  await expect(rows.nth(0)).toHaveAttribute("data-anchor", "true");
  await expect(rows.nth(0)).toContainText("★ 人工确认");
  await expect(page.getByTestId("step-cost").nth(0)).toHaveText("9000");
  await expect(page.getByTestId("total-cost")).toHaveText("9000");

  // Unmarking and recomputing restores the algorithm's cheaper split.
  await page.getByTestId("anchor-toggle").nth(0).click();
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(2);
  await expect(page.getByTestId("total-cost")).toHaveText("4000");
});

test("unmarking the anchor restores the original timeline", async ({ page }) => {
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(4);
  await page.getByTestId("anchor-toggle").nth(0).click();
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("timeline-row").nth(0)).toHaveAttribute(
    "data-anchor",
    "true",
  );

  // Unmark from the timeline row itself and recompute.
  await page.getByTestId("anchor-toggle").nth(0).click();
  await expect(page.getByTestId("anchors-empty")).toBeVisible();
  await page.getByTestId("submit").click();

  const rows = page.getByTestId("timeline-row");
  await expect(rows).toHaveCount(4);
  await expect(page.getByText("★ 人工确认")).toHaveCount(0);
  await expect(rows.nth(0)).toHaveAttribute("data-action", "match");
  await expect(rows.nth(2)).toHaveAttribute("data-action", "right_gap");
  await expect(rows.nth(3)).toHaveAttribute("data-action", "left_gap");
  await expect(page.getByTestId("total-cost")).toHaveText("4250");
});

test("out-of-range anchor keeps inputs and marks, error shown by the anchor", async ({
  page,
}) => {
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("timeline-row")).toHaveCount(4);
  await page.getByTestId("anchor-toggle").nth(0).click();
  await expect(page.getByTestId("anchor-item")).toHaveCount(1);

  // Emptying the right side makes the pinned right index invalid.
  const leftBefore = await page.getByTestId("input-left").inputValue();
  await page.getByTestId("input-right").fill("[]");
  await page.getByTestId("submit").click();

  // The first definite error appears next to the offending anchor.
  const item = page.getByTestId("anchor-item");
  await expect(item.getByTestId("anchor-error")).toBeVisible();
  await expect(item.getByTestId("anchor-error")).toContainText(
    "anchors[0].right",
  );
  // No generic banner, no new timeline; inputs and marks are preserved.
  await expect(page.getByTestId("error-banner")).toHaveCount(0);
  await expect(page.getByTestId("result-panel")).toHaveCount(0);
  await expect(page.getByTestId("input-left")).toHaveValue(leftBefore);
  await expect(page.getByTestId("input-right")).toHaveValue("[]");
  await expect(page.getByTestId("anchor-item")).toHaveCount(1);

  // Removing the bad anchor makes the submission succeed again.
  await page.getByTestId("anchor-remove").click();
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("result-panel")).toBeVisible();
  await expect(page.getByTestId("timeline-row")).toHaveCount(3);
});

test("anchor API contract: crossing/duplicate fail once, legacy shape unchanged", async ({
  request,
}) => {
  const left = [
    { time: 0, text: "a" },
    { time: 4200, text: "b" },
    { time: 9000, text: "c" },
  ];
  const right = [
    { time: 150, text: "a" },
    { time: 4100, text: "b" },
    { time: 12000, text: "d" },
  ];

  // Crossing anchors -> exactly one 422 at the first offending anchor.
  const crossing = await request.post("/api/align", {
    data: {
      left,
      right,
      anchors: [
        { left: 1, right: 0 },
        { left: 0, right: 1 },
      ],
    },
  });
  expect(crossing.status()).toBe(422);
  const crossingBody = await crossing.json();
  expect(Object.keys(crossingBody).sort()).toEqual(["error", "path"]);
  expect(crossingBody.path).toBe("anchors[1].left");
  expect(crossingBody.error).toContain("交叉");

  // Reused left index -> single 422 as well.
  const dup = await request.post("/api/align", {
    data: {
      left,
      right,
      anchors: [
        { left: 0, right: 0 },
        { left: 0, right: 1 },
      ],
    },
  });
  expect(dup.status()).toBe(422);
  expect((await dup.json()).path).toBe("anchors[1].left");

  // No anchors -> the legacy response shape: no `anchor` key anywhere.
  const plain = await request.post("/api/align", { data: { left, right } });
  expect(plain.status()).toBe(200);
  const plainBody = await plain.json();
  for (const step of plainBody.steps) {
    expect(step).not.toHaveProperty("anchor");
  }

  // Empty anchors array behaves exactly like no anchors.
  const emptyAnchors = await request.post("/api/align", {
    data: { left, right, anchors: [] },
  });
  expect(await emptyAnchors.json()).toEqual(plainBody);

  // A legal anchor is pinned and flagged; segments stay optimal (the golden
  // total is unchanged for this anchor) and replay reaches the same total.
  const anchored = await request.post("/api/align", {
    data: { left, right, anchors: [{ left: 1, right: 1 }] },
  });
  const anchoredBody = await anchored.json();
  expect(anchoredBody.total_cost).toBe(plainBody.total_cost);
  expect(anchoredBody.steps.map((s: { anchor: boolean }) => s.anchor)).toEqual([
    false,
    true,
    false,
    false,
  ]);
  const cumulative = anchoredBody.steps.map(
    (s: { cumulative_cost: number }) => s.cumulative_cost,
  );
  expect(cumulative[cumulative.length - 1]).toBe(anchoredBody.total_cost);
});

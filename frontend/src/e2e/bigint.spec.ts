import { expect, test } from "@playwright/test";

/**
 * Frontend BigInt round trip for timestamps beyond CPython's default
 * 4300-digit int<->str limit: textarea input, request submission and result
 * rendering must keep every decimal digit — the value must never be routed
 * through a JavaScript Number (which cannot even hold 4301 digits and would
 * render an exponential/rounded form). Runs against the real full stack.
 */

// 4301 digits: one past CPython's default limit — the exact regression input.
const DIGITS = "9".repeat(4301);
// Two 4301-digit timestamps one millisecond apart; as IEEE doubles they are
// indistinguishable, so any Number coercion collapses them.
const BIG_A = "8".repeat(4301);
const BIG_B = `${"8".repeat(4300)}9`;

test("4301-digit timestamp survives input -> submit -> render exactly", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("input-left").fill(`[{"time":${DIGITS},"text":"x"}]`);
  await page.getByTestId("input-right").fill("[]");

  const requestPromise = page.waitForRequest("/api/align");
  await page.getByTestId("submit").click();

  // The exact digits leave the browser (raw text, no re-serialization).
  const request = await requestPromise;
  expect(request.postData()).toContain(DIGITS);

  // No generic failure: the arbitrary-precision contract returns a timeline.
  await expect(page.getByTestId("result-panel")).toBeVisible();
  await expect(page.getByTestId("error-banner")).toHaveCount(0);

  const row = page.getByTestId("timeline-row");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-action", "right_gap");
  // Every one of the 4301 digits is rendered back verbatim.
  await expect(row.locator(".time").first()).toHaveText(`${DIGITS} ms`);
  await expect(page.getByTestId("step-cost").nth(0)).toHaveText("2000");
  await expect(page.getByTestId("total-cost")).toHaveText("2000");
});

test("4301-digit timestamps 1ms apart are not collapsed by Number rounding", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByTestId("input-left")
    .fill(`[{"time":${BIG_A},"text":"交接点"}]`);
  await page
    .getByTestId("input-right")
    .fill(`[{"time":${BIG_B},"text":"交接点"}]`);
  await page.getByTestId("submit").click();

  await expect(page.getByTestId("result-panel")).toBeVisible();
  await expect(page.getByTestId("error-banner")).toHaveCount(0);
  const row = page.getByTestId("timeline-row");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-action", "match");
  // Both exact timestamps are shown and the exact 1ms difference is the cost;
  // rounded to doubles the pair would display identically and cost 0.
  await expect(row.locator(".time").nth(0)).toHaveText(`${BIG_A} ms`);
  await expect(row.locator(".time").nth(1)).toHaveText(`${BIG_B} ms`);
  await expect(page.getByTestId("step-cost").nth(0)).toHaveText("1");
  await expect(page.getByTestId("total-cost")).toHaveText("1");
});

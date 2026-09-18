import { isAnchorPair, rowIndices } from "./anchors";
import type { AlignResponse, AlignStep, AnchorPair, Int } from "./types";

const ACTION_LABEL: Record<AlignStep["action"], string> = {
  match: "配对",
  left_gap: "左侧留空",
  right_gap: "右侧留空",
};

function n(v: Int): string {
  return typeof v === "bigint" ? v.toString() : String(v);
}

function absDiff(a: Int, b: Int): string {
  if (typeof a === "bigint" || typeof b === "bigint") {
    const x = BigInt(a);
    const y = BigInt(b);
    return n(x > y ? x - y : y - x);
  }
  return String(Math.abs(a - b));
}

function fmtTime(t: Int | null | undefined): string {
  return t === null || t === undefined ? "—" : `${n(t)} ms`;
}

/** Human-readable recomputation of the single-step cost, row by row. */
function costExplanation(step: AlignStep): string {
  if (step.action === "left_gap" || step.action === "right_gap") {
    return "单侧留空 = 2000";
  }
  const lt = step.left!.time;
  const rt = step.right!.time;
  const diff = absDiff(lt, rt);
  const same = step.left!.text === step.right!.text;
  if (same) {
    return `相同文本：|${n(lt)} − ${n(rt)}| = ${diff}`;
  }
  return `不同文本：|${n(lt)} − ${n(rt)}| + 3000 = ${diff} + 3000 = ${n(step.cost)}`;
}

export default function ResultTimeline({
  result,
  runningTotal,
  anchors = [],
  onToggleAnchor,
}: {
  result: AlignResponse;
  runningTotal?: Int;
  /** Currently selected human-confirmed pairs (may include unsubmitted ones). */
  anchors?: AnchorPair[];
  onToggleAnchor?: (pair: AnchorPair) => void;
}) {
  const shownTotal: Int = runningTotal ?? result.total_cost;
  const sumOfStepCosts = result.steps.reduce<Int>(
    (acc, s) => (typeof acc === "bigint" || typeof s.cost === "bigint"
      ? BigInt(acc) + BigInt(s.cost)
      : acc + (s.cost as number)),
    0,
  );
  // Record indices consumed by each row, so a match row can be pinned as
  // the anchor pair (left[i], right[j]).
  const indices = rowIndices(result.steps);

  return (
    <section className="result" data-testid="result-panel">
      <h2>唯一最优时间轴</h2>
      <p className="legend" data-testid="legend">
        代价规则：相同文本配对 = 时间差绝对值；不同文本配对 = 时间差 + 3000；
        任一侧留空 = 2000。平局时优先配对，其次左侧留空，再次右侧留空。
        带 ★ 的行为人工确认锚点（重新计算时保持固定），其余行为算法生成。
      </p>
      <div className="summary" data-testid="summary">
        <span className="badge match">配对 {result.counts.match}</span>
        <span className="badge left-gap">左侧留空 {result.counts.left_gap}</span>
        <span className="badge right-gap">右侧留空 {result.counts.right_gap}</span>
        <span className="badge total">
          {runningTotal !== undefined &&
          n(runningTotal) !== n(result.total_cost)
            ? "复算累计 "
            : "总代价 "}
          <strong data-testid="total-cost">{n(shownTotal)}</strong>
          {runningTotal !== undefined && n(runningTotal) !== n(result.total_cost)
            ? `（最终 ${n(result.total_cost)}）`
            : ""}
        </span>
      </div>

      <div className="table-scroll">
        <table className="timeline">
          <thead>
            <tr>
              <th>#</th>
              <th>左侧口译员</th>
              <th>动作</th>
              <th>右侧口译员</th>
              <th>单步代价</th>
              <th>累计代价</th>
              <th>复算</th>
              <th>来源 / 锚点</th>
            </tr>
          </thead>
          <tbody>
            {result.steps.map((step, idx) => {
              const rowIdx = indices[idx];
              const pair: AnchorPair | null =
                step.action === "match" &&
                rowIdx.left !== null &&
                rowIdx.right !== null
                  ? { left: rowIdx.left, right: rowIdx.right }
                  : null;
              const selected =
                pair !== null && isAnchorPair(anchors, pair.left, pair.right);
              const confirmed = step.anchor === true;
              return (
                <tr
                  key={idx}
                  className={`row-${step.action}${confirmed ? " row-anchor" : ""}`}
                  data-testid="timeline-row"
                  data-action={step.action}
                  data-anchor={confirmed ? "true" : undefined}
                >
                  <td className="idx">{idx + 1}</td>
                  <td className="note-cell">
                    {step.left ? (
                      <>
                        <span className="time">{fmtTime(step.left.time)}</span>
                        <span className="text">{step.left.text}</span>
                      </>
                    ) : (
                      <span className="empty">∅</span>
                    )}
                  </td>
                  <td className="action-cell">
                    <span className={`action-tag tag-${step.action}`}>
                      {ACTION_LABEL[step.action]}
                    </span>
                  </td>
                  <td className="note-cell">
                    {step.right ? (
                      <>
                        <span className="time">{fmtTime(step.right.time)}</span>
                        <span className="text">{step.right.text}</span>
                      </>
                    ) : (
                      <span className="empty">∅</span>
                    )}
                  </td>
                  <td className="cost" data-testid="step-cost">
                    {n(step.cost)}
                  </td>
                  <td className="cumulative" data-testid="step-cumulative">
                    {n(step.cumulative_cost)}
                  </td>
                  <td className="explain">{costExplanation(step)}</td>
                  <td className="anchor-cell">
                    {confirmed ? (
                      <span
                        className="origin-tag tag-human"
                        data-testid="origin-tag"
                      >
                        ★ 人工确认
                      </span>
                    ) : (
                      <span
                        className="origin-tag tag-algo"
                        data-testid="origin-tag"
                      >
                        算法生成
                      </span>
                    )}
                    {pair !== null && onToggleAnchor && (
                      <button
                        type="button"
                        className={`anchor-toggle${selected ? " selected" : ""}`}
                        data-testid="anchor-toggle"
                        aria-pressed={selected}
                        onClick={() => onToggleAnchor(pair)}
                      >
                        {selected ? "取消锚点" : "设为锚点"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={4} className="total-label">
                总成本最小
              </td>
              <td className="total-step">{n(sumOfStepCosts)}</td>
              <td className="total-final" data-testid="total-cost-foot">
                {n(result.total_cost)}
              </td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

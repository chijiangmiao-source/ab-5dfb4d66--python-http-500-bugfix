import { useMemo, useState } from "react";
import HighlightedTextarea from "./HighlightedTextarea";
import ResultTimeline from "./ResultTimeline";
import { alignNotes, rootRawText, AlignRequestError } from "./api";
import { anchorIndexFromPath, toggleAnchor } from "./anchors";
import {
  JsonSourceError,
  locateOffset,
  parseLocated,
  type Range,
} from "./jsonLocations";
import { validateSequence } from "./validation";
import type { AlignResponse, AnchorPair, Int } from "./types";

type Side = "left" | "right";

interface MarkedError {
  message: string;
  /** full API-style path such as `left[2].time`, or "" for a global failure */
  path: string;
  side: Side | null;
  /** character offset inside the offending textarea (malformed JSON) */
  offset?: number;
}

interface AnchorError {
  /** index into the submitted anchors list, or null for a whole-array error */
  index: number | null;
  message: string;
}

const SAMPLE_LEFT = `[
  {"time": 0, "text": "各位媒体朋友下午好"},
  {"time": 4200, "text": "新产品将于下月上市"},
  {"time": 9000, "text": "感谢各位的提问"}
]`;

const SAMPLE_RIGHT = `[
  {"time": 150, "text": "各位媒体朋友下午好"},
  {"time": 4100, "text": "新产品将于下月上市"},
  {"time": 12000, "text": "交接后的补充记录"}
]`;

export default function App() {
  const [leftText, setLeftText] = useState(SAMPLE_LEFT);
  const [rightText, setRightText] = useState(SAMPLE_RIGHT);
  const [error, setError] = useState<MarkedError | null>(null);
  const [result, setResult] = useState<AlignResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [revealed, setRevealed] = useState(0);
  // Human-confirmed pairs, kept sorted; they survive failed submissions so
  // the user can fix or unmark them without losing the selection.
  const [anchors, setAnchors] = useState<AnchorPair[]>([]);
  const [anchorError, setAnchorError] = useState<AnchorError | null>(null);

  const located = useMemo(() => {
    const parse = (text: string) => {
      try {
        return parseLocated(text);
      } catch {
        return null;
      }
    };
    return { left: parse(leftText), right: parse(rightText) };
  }, [leftText, rightText]);

  /**
   * Map a relative path ("", "[200]", "[2]", "[2].time") onto the source
   * range inside that textarea, whose own JSON root is the array.
   */
  function rangeForRelative(side: Side, rel: string): Range | null {
    const doc = located[side];
    if (!doc) return null;
    if (rel === "") return doc.ranges.get("") ?? null;
    return doc.memberRanges.get(rel) ?? doc.ranges.get(rel) ?? null;
  }

  function markerFor(side: Side): Range | null {
    if (!error || error.side !== side) return null;
    if (error.offset !== undefined) {
      const len = (side === "left" ? leftText : rightText).length;
      return { start: error.offset, end: Math.min(error.offset + 1, len) };
    }
    const prefix = side === "left" ? "left" : "right";
    if (!error.path.startsWith(prefix)) return null;
    return rangeForRelative(side, error.path.slice(prefix.length));
  }

  async function handleSubmit() {
    setError(null);
    setAnchorError(null);
    setResult(null);
    setLoading(true);
    try {
      // --- Phase 1: each textarea must itself parse as JSON (left first) ---
      let leftParsed: ReturnType<typeof parseLocated>;
      let rightParsed: ReturnType<typeof parseLocated>;
      try {
        leftParsed = parseLocated(leftText);
      } catch (e) {
        failJson("left", leftText, e);
        return;
      }
      try {
        rightParsed = parseLocated(rightText);
      } catch (e) {
        failJson("right", rightText, e);
        return;
      }

      // --- Phase 2: client-side structural validation (single failure) ----
      // This mirrors the server and still yields one precise failure when
      // the API is unreachable; the server remains the authority for cost.
      const localLeft = validateSequence(leftParsed.value);
      if (localLeft) {
        setError({
          message: localLeft.message,
          path: `left${localLeft.path}`,
          side: "left",
        });
        return;
      }
      const localRight = validateSequence(rightParsed.value);
      if (localRight) {
        setError({
          message: localRight.message,
          path: `right${localRight.path}`,
          side: "right",
        });
        return;
      }

      // --- Phase 3: the server performs the DP alignment ------------------
      // The raw array source is forwarded verbatim so integer literals
      // beyond Number.MAX_SAFE_INTEGER keep their exact digits.  The
      // original two inputs are re-sent together with the selected anchors,
      // so human-confirmed pairs stay fixed while the segments between them
      // are re-aligned.
      const leftRaw = rootRawText(leftText);
      const rightRaw = rootRawText(rightText);
      try {
        const aligned = await alignNotes(leftRaw, rightRaw, anchors);
        setResult(aligned);
        setRevealed(aligned.steps.length);
      } catch (e) {
        if (e instanceof AlignRequestError && e.path.startsWith("anchors")) {
          // Anchor problem: keep the inputs and the selected marks, show the
          // first definite error next to the offending anchor, and do not
          // show a new timeline that could be mistaken for a valid one.
          setAnchorError({
            index: anchorIndexFromPath(e.path),
            message: e.message,
          });
        } else if (e instanceof AlignRequestError && e.path) {
          const side: Side = e.path.startsWith("right") ? "right" : "left";
          setError({ message: e.message, path: e.path, side });
        } else if (e instanceof AlignRequestError) {
          setError({ message: e.message, path: "", side: null });
        } else {
          setError({
            message: "发生未知错误，请稍后重试。",
            path: "",
            side: null,
          });
        }
      }
    } finally {
      setLoading(false);
    }
  }

  function handleToggleAnchor(pair: AnchorPair) {
    setAnchors((prev) => toggleAnchor(prev, pair));
    setAnchorError(null);
  }

  function failJson(side: Side, text: string, e: unknown) {
    const pos = e instanceof JsonSourceError ? e.pos : 0;
    const { line, column } = locateOffset(text, pos);
    const reason = e instanceof Error ? e.message : "非法 JSON。";
    setError({
      message: `第 ${line} 行第 ${column} 列无法解析：${reason}`,
      path: "",
      side,
      offset: pos,
    });
  }

  function loadSample() {
    setLeftText(SAMPLE_LEFT);
    setRightText(SAMPLE_RIGHT);
    setError(null);
    setAnchorError(null);
    setResult(null);
    setRevealed(0);
    setAnchors([]);
  }

  function clearAll() {
    setLeftText("[]");
    setRightText("[]");
    setError(null);
    setAnchorError(null);
    setResult(null);
    setRevealed(0);
    setAnchors([]);
  }

  // Step-by-step replay: only the first `revealed` rows (and their running
  // total) are shown, letting the user re-add costs one action at a time.
  const visibleResult: AlignResponse | null = useMemo(() => {
    if (!result) return null;
    if (revealed >= result.steps.length) return result;
    return { ...result, steps: result.steps.slice(0, revealed) };
  }, [result, revealed]);

  const runningTotal: Int =
    visibleResult && visibleResult.steps.length > 0
      ? visibleResult.steps[visibleResult.steps.length - 1].cumulative_cost
      : 0;

  return (
    <main className="page">
      <header>
        <h1>口译交接时间轴对齐</h1>
        <p className="subtitle">
          两组递增毫秒笔记的全局最优对齐 · 动态规划实现，未使用任何外部匹配库
        </p>
      </header>

      <section className="inputs">
        <HighlightedTextarea
          value={leftText}
          onChange={(v) => {
            setLeftText(v);
            setError(null);
            setAnchorError(null);
            setResult(null);
          }}
          label="左侧口译员笔记（JSON 数组，最多 200 项）"
          marker={markerFor("left")}
          testId="input-left"
          invalid={error?.side === "left"}
        />
        <HighlightedTextarea
          value={rightText}
          onChange={(v) => {
            setRightText(v);
            setError(null);
            setAnchorError(null);
            setResult(null);
          }}
          label="右侧口译员笔记（JSON 数组，最多 200 项）"
          marker={markerFor("right")}
          testId="input-right"
          invalid={error?.side === "right"}
        />
      </section>

      <section className="controls">
        <button
          type="button"
          className="primary"
          data-testid="submit"
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading ? "对齐中…" : "生成对齐"}
        </button>
        <button type="button" onClick={loadSample} data-testid="sample">
          载入示例
        </button>
        <button type="button" onClick={clearAll} data-testid="clear">
          清空为 []
        </button>
        {result && (
          <span className="replay">
            <button
              type="button"
              data-testid="step-back"
              onClick={() => setRevealed((n) => Math.max(0, n - 1))}
              disabled={revealed === 0}
            >
              ◀ 上一步
            </button>
            <span data-testid="replay-count">
              复算 {revealed} / {result.steps.length} 步 · 当前累计 {String(runningTotal)}
            </span>
            <button
              type="button"
              data-testid="step-next"
              onClick={() =>
                setRevealed((n) => Math.min(result.steps.length, n + 1))
              }
              disabled={revealed >= result.steps.length}
            >
              下一步 ▶
            </button>
          </span>
        )}
      </section>

      {error && (
        <div className="error-banner" role="alert" data-testid="error-banner">
          <strong>仅有一处失败：</strong>
          {error.path && (
            <code data-testid="error-path">{error.path} </code>
          )}
          <span>{error.message}</span>
        </div>
      )}

      <section className="anchors" data-testid="anchors-panel">
        <h2>
          配对锚点（人工确认）
          {anchors.length > 0 && (
            <span className="anchor-count" data-testid="anchor-count">
              {anchors.length}
            </span>
          )}
        </h2>
        <p className="anchors-hint">
          在时间轴的配对行点击「设为锚点」即可固定该配对；点击「生成对齐」后，
          锚点配对保持不变，算法只对锚点区间内的其余记录重新自动对齐。
        </p>
        {anchors.length === 0 ? (
          <p className="anchors-empty" data-testid="anchors-empty">
            尚未设置锚点。
          </p>
        ) : (
          <ol className="anchor-list" data-testid="anchor-list">
            {anchors.map((a, k) => (
              <li key={`${a.left}-${a.right}`} data-testid="anchor-item">
                <span className="anchor-pair">
                  #{k + 1} 左[{a.left}] ↔ 右[{a.right}]
                </span>
                <button
                  type="button"
                  data-testid="anchor-remove"
                  onClick={() => handleToggleAnchor(a)}
                >
                  取消
                </button>
                {anchorError?.index === k && (
                  <span
                    className="anchor-error"
                    role="alert"
                    data-testid="anchor-error"
                  >
                    {anchorError.message}
                  </span>
                )}
              </li>
            ))}
          </ol>
        )}
        {anchorError !== null && anchorError.index === null && (
          <p className="anchor-error" role="alert" data-testid="anchor-error">
            {anchorError.message}
          </p>
        )}
      </section>

      {visibleResult && (
        <ResultTimeline
          result={visibleResult}
          runningTotal={runningTotal}
          anchors={anchors}
          onToggleAnchor={handleToggleAnchor}
        />
      )}
    </main>
  );
}

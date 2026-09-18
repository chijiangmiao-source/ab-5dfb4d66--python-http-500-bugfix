import { useLayoutEffect, useRef } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  label: string;
  marker: { start: number; end: number } | null;
  testId: string;
  invalid: boolean;
}

const SHARED_TEXT_STYLE: React.CSSProperties = {
  fontFamily: "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
  fontSize: "13px",
  lineHeight: "1.6",
  letterSpacing: "normal",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  margin: 0,
  padding: "12px",
  border: "1px solid transparent",
};

/**
 * Textarea with a <pre> backdrop painting a single highlighted range.
 * The textarea text itself is transparent (caret stays visible) so the
 * backdrop markup shows through; scroll positions are locked together.
 */
export default function HighlightedTextarea({
  value,
  onChange,
  label,
  marker,
  testId,
  invalid,
}: Props) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const backRef = useRef<HTMLPreElement>(null);

  useLayoutEffect(() => {
    const ta = taRef.current;
    const back = backRef.current;
    if (!ta || !back) return;
    const sync = () => {
      back.scrollTop = ta.scrollTop;
      back.scrollLeft = ta.scrollLeft;
    };
    ta.addEventListener("scroll", sync);
    sync();
    return () => ta.removeEventListener("scroll", sync);
  }, []);

  let before = value;
  let marked = "";
  let after = "";
  if (marker) {
    const s = Math.max(0, Math.min(marker.start, value.length));
    const e = Math.max(s, Math.min(marker.end, value.length));
    before = value.slice(0, s);
    marked = value.slice(s, e);
    after = value.slice(e);
  }

  return (
    <div>
      <label className="side-label" htmlFor={testId}>
        {label}
      </label>
      <div className={`textarea-wrap${invalid ? " invalid" : ""}`}>
        <pre ref={backRef} className="backdrop" style={SHARED_TEXT_STYLE} aria-hidden>
          {before}
          {marker && (
            <mark className="error-mark" data-testid={`${testId}-mark`}>
              {marked.length > 0 ? marked : "▌"}
            </mark>
          )}
          {after}
          {/* trailing newline spacer so backdrop matches textarea height */}
          {"\n"}
        </pre>
        <textarea
          ref={taRef}
          id={testId}
          data-testid={testId}
          className="json-input"
          style={SHARED_TEXT_STYLE}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          rows={12}
        />
      </div>
    </div>
  );
}

/**
 * Client-side mirror of backend/app/validation.py.
 *
 * Each side must be an array of at most MAX_ITEMS items; every item is an
 * object containing only an integer `time` (no booleans/floats) and a
 * non-empty string `text`; times must be strictly increasing.
 *
 * Timestamps come out of the located JSON parser as `bigint` for integer
 * literals (exact even beyond Number.MAX_SAFE_INTEGER) and as `number` for
 * floats; both paths are handled without any precision loss.
 *
 * The returned path is relative to the array itself ("[2].time", "" for the
 * root, "[200]" for the first item past the limit). Exactly one failure is
 * ever reported so the UI marks a single location.
 */

export const MAX_ITEMS = 200;

export interface ValidationIssue {
  path: string;
  message: string;
}

export interface NoteInput {
  time: unknown;
  text: unknown;
  [k: string]: unknown;
}

/** Any JSON integer token: safe numbers or exact bigints from the parser. */
function isIntToken(v: unknown): v is number | bigint {
  if (typeof v === "bigint") return true;
  return typeof v === "number" && Number.isInteger(v) && !Number.isNaN(v);
}

export function validateSequence(seq: unknown): ValidationIssue | null {
  if (!Array.isArray(seq)) {
    return { path: "", message: "必须是数组。" };
  }

  if (seq.length > MAX_ITEMS) {
    return { path: `[${MAX_ITEMS}]`, message: `最多包含 ${MAX_ITEMS} 项。` };
  }

  let prevTime: bigint | null = null;
  for (let i = 0; i < seq.length; i++) {
    const item = seq[i] as unknown;
    const itemPath = `[${i}]`;
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      return {
        path: itemPath,
        message: "必须是包含 time 与 text 的对象。",
      };
    }
    const obj = item as NoteInput;

    if (!("time" in obj)) {
      return { path: `${itemPath}.time`, message: "缺少整数字段 time。" };
    }
    if (typeof obj.time === "boolean" || !isIntToken(obj.time)) {
      return {
        path: `${itemPath}.time`,
        message: "必须是整数毫秒时间戳。",
      };
    }
    const timeValue = BigInt(obj.time as number | bigint);

    if (!("text" in obj)) {
      return {
        path: `${itemPath}.text`,
        message: "缺少非空字符串字段 text。",
      };
    }
    if (typeof obj.text !== "string" || obj.text.length === 0) {
      return { path: `${itemPath}.text`, message: "必须是非空字符串。" };
    }

    const extraKeys = Object.keys(obj).filter((k) => k !== "time" && k !== "text");
    if (extraKeys.length > 0) {
      return {
        path: `${itemPath}.${extraKeys[0]}`,
        message: "是多余字段，每项仅允许 time 与 text。",
      };
    }

    if (prevTime !== null && timeValue <= prevTime) {
      return {
        path: `${itemPath}.time`,
        message: `为 ${timeValue.toString()}，未严格递增（上一项时间为 ${prevTime.toString()}）。`,
      };
    }
    prevTime = timeValue;
  }

  return null;
}

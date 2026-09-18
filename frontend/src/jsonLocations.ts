/**
 * A small JSON parser that records source character ranges.
 *
 * We cannot use the built-in `JSON.parse` position information portably
 * (engine messages differ), and the UI must keep the user's raw text while
 * highlighting the FIRST error path returned by the API (e.g. `left[2].time`).
 * Parsing ourselves gives, for every value:
 *
 *   - its character range [start, end)
 *   - for object members, the range spanning the key too
 *
 * keyed by a path like "[2].time" (root key is "").
 *
 * This is plain recursive-descent JSON, not a third-party matching library.
 */

export interface Range {
  start: number;
  end: number;
}

export interface LocatedJson {
  value: unknown;
  /** path ("" === root) -> value character range */
  ranges: Map<string, Range>;
  /** object-member path ("[2].time") -> range including the key token */
  memberRanges: Map<string, Range>;
}

export class JsonSourceError extends Error {
  pos: number;
  constructor(message: string, pos: number) {
    super(message);
    this.name = "JsonSourceError";
    this.pos = pos;
  }
}

const ESCAPABLE = new Set(['"', "\\", "/", "b", "f", "n", "r", "t", "u"]);

export function parseLocated(src: string): LocatedJson {
  const ranges = new Map<string, Range>();
  const memberRanges = new Map<string, Range>();
  let i = 0;

  const ws = () => {
    while (i < src.length && " \t\n\r".includes(src[i])) i++;
  };

  const readValue: (path: string) => unknown = (path) => {
    ws();
    const start = i;
    let value: unknown;
    const ch = src[i];

    if (ch === "{") {
      value = readObject(path);
    } else if (ch === "[") {
      value = readArray(path);
    } else if (ch === '"') {
      value = readString();
    } else if (ch === "-" || (ch >= "0" && ch <= "9")) {
      value = readNumber();
    } else if (src.startsWith("true", i)) {
      i += 4;
      value = true;
    } else if (src.startsWith("false", i)) {
      i += 5;
      value = false;
    } else if (src.startsWith("null", i)) {
      i += 4;
      value = null;
    } else {
      throw new JsonSourceError(
        i >= src.length ? "JSON 提前结束。" : `意外的字符 “${src[i]}”。`,
        i,
      );
    }
    ws();
    ranges.set(path, { start, end: i });
    return value;
  };

  const readObject = (path: string): Record<string, unknown> => {
    const obj: Record<string, unknown> = {};
    i++; // {
    ws();
    if (src[i] === "}") {
      i++;
      return obj;
    }
    for (;;) {
      ws();
      const memberStart = i;
      if (src[i] !== '"') {
        throw new JsonSourceError("对象的键必须是双引号字符串。", i);
      }
      const key = readString();
      ws();
      if (src[i] !== ":") {
        throw new JsonSourceError("键与值之间缺少冒号 ':'。", i);
      }
      i++;
      const memberPath = `${path}.${key}`;
      obj[key] = readValue(memberPath);
      ws();
      const memberEnd = i;
      memberRanges.set(memberPath, { start: memberStart, end: memberEnd });
      if (src[i] === ",") {
        i++;
        continue;
      }
      if (src[i] === "}") {
        i++;
        return obj;
      }
      throw new JsonSourceError("对象成员后需要 ',' 或 '}'。", i);
    }
  };

  const readArray = (path: string): unknown[] => {
    const arr: unknown[] = [];
    i++; // [
    ws();
    if (src[i] === "]") {
      i++;
      return arr;
    }
    for (;;) {
      const idx = arr.length;
      arr.push(readValue(`${path}[${idx}]`));
      ws();
      if (src[i] === ",") {
        i++;
        ws();
        continue;
      }
      if (src[i] === "]") {
        i++;
        return arr;
      }
      throw new JsonSourceError("数组元素后需要 ',' 或 ']'。", i);
    }
  };

  const readString = (): string => {
    i++; // opening quote
    let out = "";
    while (i < src.length) {
      const ch = src[i];
      if (ch === '"') {
        i++;
        return out;
      }
      if (ch === "\\") {
        const esc = src[i + 1];
        if (!ESCAPABLE.has(esc)) {
          throw new JsonSourceError(`非法的转义序列 “\\${esc ?? ""}”。`, i);
        }
        if (esc === "u") {
          const hex = src.slice(i + 2, i + 6);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
            throw new JsonSourceError("非法的 \\u  Unicode 转义。", i);
          }
          out += String.fromCharCode(parseInt(hex, 16));
          i += 6;
        } else {
          const map: Record<string, string> = {
            b: "\b",
            f: "\f",
            n: "\n",
            r: "\r",
            t: "\t",
            '"': '"',
            "\\": "\\",
            "/": "/",
          };
          out += map[esc];
          i += 2;
        }
      } else {
        if (ch.charCodeAt(0) < 0x20) {
          throw new JsonSourceError("字符串中存在未转义的控制字符。", i);
        }
        out += ch;
        i++;
      }
    }
    throw new JsonSourceError("字符串没有结束引号。", i);
  };

  const readNumber = (): number | bigint => {
    const start = i;
    let isFloat = false;
    if (src[i] === "-") i++;
    if (src[i] === "0") {
      i++;
    } else if (src[i] >= "1" && src[i] <= "9") {
      while (src[i] >= "0" && src[i] <= "9") i++;
    } else {
      throw new JsonSourceError("非法数字。", i);
    }
    if (src[i] === ".") {
      isFloat = true;
      i++;
      if (!(src[i] >= "0" && src[i] <= "9")) {
        throw new JsonSourceError("小数点后至少需要一位数字。", i);
      }
      while (src[i] >= "0" && src[i] <= "9") i++;
    }
    if (src[i] === "e" || src[i] === "E") {
      isFloat = true;
      i++;
      if (src[i] === "+" || src[i] === "-") i++;
      if (!(src[i] >= "0" && src[i] <= "9")) {
        throw new JsonSourceError("指数部分至少需要一位数字。", i);
      }
      while (src[i] >= "0" && src[i] <= "9") i++;
    }
    const literal = src.slice(start, i);
    // Keep integer literals (timestamps may be far beyond Number.MAX_SAFE
    // INTEGER — millisecond times in far-future/epoch variants) as BigInt
    // with their exact digits; only floats become JS numbers.
    return isFloat ? Number(literal) : BigInt(literal);
  };

  ws();
  const value = readValue("");
  // readValue already consumed trailing whitespace while recording the root
  // range; anything left over is content after a complete JSON document.
  if (i < src.length) {
    throw new JsonSourceError(`JSON 结束后仍有多余字符 “${src[i]}”。`, i);
  }
  // Trim trailing whitespace off the recorded root range.
  const rootRange = ranges.get("");
  if (!rootRange) throw new JsonSourceError("空输入。", 0);
  let end = rootRange.end;
  while (end > rootRange.start && " \t\n\r".includes(src[end - 1])) end--;
  ranges.set("", { ...rootRange, end });
  return { value, ranges, memberRanges };
}

/** Convert an absolute character offset into a 1-based line/column pair. */
export function locateOffset(src: string, pos: number): { line: number; column: number } {
  let line = 1;
  let column = 1;
  for (let k = 0; k < pos && k < src.length; k++) {
    if (src[k] === "\n") {
      line++;
      column = 1;
    } else {
      column++;
    }
  }
  // A position sitting on a newline reads as the start of the following line.
  if (pos < src.length && src[pos] === "\n") {
    line++;
    column = 1;
  }
  return { line, column };
}

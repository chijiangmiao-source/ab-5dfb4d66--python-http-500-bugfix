import { parseLocated } from "./jsonLocations";
import type { AlignResponse, AnchorPair, ApiError } from "./types";

export class AlignRequestError extends Error {
  path: string;
  status: number;

  constructor(message: string, path: string, status: number) {
    super(message);
    this.name = "AlignRequestError";
    this.path = path;
    this.status = status;
  }
}

/**
 * Extract the exact source text of the root JSON value (the array),
 * trimming surrounding whitespace. Keeping the raw digits is what lets
 * timestamps above Number.MAX_SAFE_INTEGER reach the server unrounded;
 * re-serializing through `JSON.stringify` would either throw on bigint or
 * silently lose precision.
 */
export function rootRawText(text: string): string {
  const doc = parseLocated(text);
  const range = doc.ranges.get("");
  if (!range) throw new Error("empty JSON document");
  return text.slice(range.start, range.end);
}

/**
 * POST the two raw JSON array texts to the alignment API.
 *
 * - `anchors` (human-confirmed index pairs) is appended only when non-empty,
 *   so an anchorless request body stays byte-for-byte the legacy shape;
 * - network/non-JSON-HTTP failures become a single AlignRequestError with an
 *   empty path;
 * - API 4xx failures become AlignRequestError carrying exactly one error path
 *   (e.g. `left[2].time` or `anchors[1].left`) so the UI can keep the text
 *   and mark that spot.
 *
 * The response is parsed with the BigInt-aware parser so huge integer
 * timestamps survive the round trip without precision loss.
 */
export async function alignNotes(
  leftRawArray: string,
  rightRawArray: string,
  anchors: AnchorPair[] = [],
  fetchImpl: typeof fetch = fetch,
): Promise<AlignResponse> {
  const anchorsPart =
    anchors.length > 0 ? `,"anchors":${JSON.stringify(anchors)}` : "";
  const body = `{"left":${leftRawArray},"right":${rightRawArray}${anchorsPart}}`;

  let resp: Response;
  try {
    resp = await fetchImpl("/api/align", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch {
    throw new AlignRequestError(
      "无法连接对齐服务，请确认 API 已启动。",
      "",
      0,
    );
  }

  const text = await resp.text();
  let parsed: unknown;
  try {
    parsed = parseLocated(text).value;
  } catch {
    throw new AlignRequestError(
      `服务返回了无法解析的响应（HTTP ${resp.status}）。`,
      "",
      resp.status,
    );
  }

  if (!resp.ok) {
    const data = parsed as Partial<ApiError>;
    throw new AlignRequestError(
      typeof data?.error === "string"
        ? data.error
        : `请求失败（HTTP ${resp.status}）。`,
      typeof data?.path === "string" ? data.path : "",
      resp.status,
    );
  }

  return parsed as AlignResponse;
}

/** Numeric values may be exact BigInts (large integer literals) or numbers. */
export type Int = number | bigint;

export interface Note {
  time: Int;
  text: string;
}

export type Action = "match" | "left_gap" | "right_gap";

export interface AlignStep {
  action: Action;
  left: Note | null;
  right: Note | null;
  cost: Int;
  cumulative_cost: Int;
  /**
   * Present only when the request carried a non-empty `anchors` array:
   * true on the human-confirmed rows, false on algorithm-generated ones.
   */
  anchor?: boolean;
}

/** A human-confirmed pair of record indices, pinned on recompute. */
export interface AnchorPair {
  left: number;
  right: number;
}

export interface AlignResponse {
  steps: AlignStep[];
  total_cost: Int;
  counts: { match: number; left_gap: number; right_gap: number };
  costs: { gap: number; mismatch_penalty: number };
}

export interface ApiError {
  error: string;
  path: string;
}

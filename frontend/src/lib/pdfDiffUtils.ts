// Compute word-level text differences for PDF validation inspection.

export interface DiffPart {
  type: "same" | "added" | "removed";
  value: string;
}

export interface WordDiffResult {
  expectedParts: DiffPart[];
  actualParts: DiffPart[];
  unifiedParts: DiffPart[];
  hasDifferences: boolean;
  changesCount: number;
}

// Keep each word with its following whitespace so highlights preserve readable text.
function tokenize(text: string): string[] {
  return text.match(/\S+\s*|\s+/g) || [];
}

function comparable(token: string): string {
  return token.normalize("NFKC").trim().toLowerCase();
}

// Merge adjacent tokens with the same diff status.
function mergeParts(parts: DiffPart[]): DiffPart[] {
  const merged: DiffPart[] = [];
  for (const part of parts) {
    if (merged.length > 0 && merged[merged.length - 1].type === part.type) {
      merged[merged.length - 1].value += part.value;
    } else if (part.value.length > 0) {
      merged.push({ ...part });
    }
  }
  return merged;
}

// Compute word-level diff between expected text and actual text.
export function computeWordDiff(expected: string = "", actual: string = "", expectedChange?: [number, number] | null,
  actualChange?: [number, number] | null): WordDiffResult {
  const safeExpected = expected || "";
  const safeActual = actual || "";
  const valid = (text: string, range?: [number, number] | null): range is [number, number] => Boolean(range
    && range.every(Number.isInteger) && range[0] >= 0 && range[1] >= range[0] && range[1] <= Array.from(text).length);
  if (valid(safeExpected, expectedChange) && valid(safeActual, actualChange)) {
    const parts = (text: string, range: [number, number], type: "added" | "removed"): DiffPart[] => {
      const chars = Array.from(text);
      return [{type: "same", value: chars.slice(0, range[0]).join("")},
        {type, value: chars.slice(range[0], range[1]).join("")},
        {type: "same", value: chars.slice(range[1]).join("")}].filter(part => part.value) as DiffPart[];
    };
    const expectedParts = parts(safeExpected, expectedChange, "removed"), actualParts = parts(safeActual, actualChange, "added");
    const changes = [...expectedParts, ...actualParts].filter(part => part.type !== "same");
    const context = actualParts.length ? actualParts : expectedParts;
    const removed = expectedParts.filter(part => part.type === "removed");
    const unifiedParts = context.flatMap(part => part.type === "added" ? [...removed, part] : [part]);
    return {expectedParts, actualParts, unifiedParts, hasDifferences: changes.length > 0,
      changesCount: changes.reduce((count, part) => count + (part.value.match(/\S+/g) || []).length, 0)};
  }

  if (safeExpected === safeActual) {
    return {
      expectedParts: safeExpected ? [{ type: "same", value: safeExpected }] : [],
      actualParts: safeActual ? [{ type: "same", value: safeActual }] : [],
      unifiedParts: safeExpected ? [{ type: "same", value: safeExpected }] : [],
      hasDifferences: false,
      changesCount: 0,
    };
  }

  const expTokens = tokenize(safeExpected);
  const actTokens = tokenize(safeActual);

  if (expTokens.length === 0) {
    return {
      expectedParts: [],
      actualParts: [{ type: "added", value: safeActual }],
      unifiedParts: [{ type: "added", value: safeActual }],
      hasDifferences: true,
      changesCount: actTokens.length,
    };
  }

  if (actTokens.length === 0) {
    return {
      expectedParts: [{ type: "removed", value: safeExpected }],
      actualParts: [],
      unifiedParts: [{ type: "removed", value: safeExpected }],
      hasDifferences: true,
      changesCount: expTokens.length,
    };
  }

  // Guard against high matrix memory for very long texts.
  const maxTokens = 500;
  if (expTokens.length > maxTokens || actTokens.length > maxTokens) {
    return {
      expectedParts: [{ type: "removed", value: safeExpected }],
      actualParts: [{ type: "added", value: safeActual }],
      unifiedParts: [
        { type: "removed", value: safeExpected },
        { type: "added", value: safeActual },
      ],
      hasDifferences: true,
      changesCount: expTokens.length + actTokens.length,
    };
  }

  const n = expTokens.length;
  const m = actTokens.length;

  // LCS dynamic programming table.
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      if (comparable(expTokens[i - 1]) === comparable(actTokens[j - 1])) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  let i = n;
  let j = m;
  const rawExpected: DiffPart[] = [];
  const rawActual: DiffPart[] = [];
  const rawUnified: DiffPart[] = [];
  let changes = 0;

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && comparable(expTokens[i - 1]) === comparable(actTokens[j - 1])) {
      rawExpected.unshift({ type: "same", value: expTokens[i - 1] });
      rawActual.unshift({ type: "same", value: actTokens[j - 1] });
      rawUnified.unshift({ type: "same", value: expTokens[i - 1] });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      rawActual.unshift({ type: "added", value: actTokens[j - 1] });
      rawUnified.unshift({ type: "added", value: actTokens[j - 1] });
      changes++;
      j--;
    } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
      rawExpected.unshift({ type: "removed", value: expTokens[i - 1] });
      rawUnified.unshift({ type: "removed", value: expTokens[i - 1] });
      changes++;
      i--;
    }
  }

  return {
    expectedParts: mergeParts(rawExpected),
    actualParts: mergeParts(rawActual),
    unifiedParts: mergeParts(rawUnified),
    hasDifferences: changes > 0,
    changesCount: changes,
  };
}

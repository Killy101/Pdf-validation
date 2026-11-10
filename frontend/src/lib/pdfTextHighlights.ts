// Finds search matches in the text pieces pdf.js reports for a page, with the same rules as the backend
// search: case-insensitive, soft hyphens dropped, and any run of spaces or line breaks equal to one space.

export interface TextPiece { str: string; hasEOL?: boolean }
export interface PositionedPiece extends TextPiece { transform: number[]; width: number; fontName: string }
export interface HighlightBox { left: number; top: number; width: number; height: number; match: number }
interface Viewport { transform: number[]; scale: number }
type Transform = (first: number[], second: number[]) => number[];
// Characters [start, end) of piece `item` belong to match number `match`.
export interface PieceRange { item: number; start: number; end: number; match: number }

function flatten(text: string) {
  return text.replace(/\u00ad/g, "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
}

export function highlightRanges(pieces: TextPiece[], query: string): PieceRange[] {
  const needle = flatten(query);
  if (needle.length < 2) return [];
  // Flattened page text, and for every character the piece and offset it came from (-1 for an inserted space).
  let text = "";
  const origin: [number, number][] = [];
  const push = (char: string, item: number, offset: number) => {
    if (/\s/.test(char)) {
      if (!text || text.endsWith(" ")) return;
      char = " ";
    }
    text += char.toLowerCase().length === 1 ? char.toLowerCase() : char;
    origin.push([item, offset]);
  };
  pieces.forEach((piece, item) => {
    for (let offset = 0; offset < piece.str.length; offset++) {
      if (piece.str[offset] !== "\u00ad") push(piece.str[offset].replace("\u00a0", " "), item, offset);
    }
    if (piece.hasEOL) push(" ", -1, -1);
  });

  const ranges: PieceRange[] = [];
  let match = 0;
  for (let at = text.indexOf(needle); at !== -1; at = text.indexOf(needle, at + needle.length), match++) {
    for (let index = at; index < at + needle.length; index++) {
      const [item, offset] = origin[index];
      if (item < 0) continue;
      const last = ranges[ranges.length - 1];
      if (last && last.match === match && last.item === item && last.end === offset) last.end = offset + 1;
      else ranges.push({ item, start: offset, end: offset + 1, match });
    }
  }
  return ranges;
}

// Rectangles (in viewport pixels) covering each match; the share of a piece's width is estimated with the piece's font.
export function highlightBoxes(pieces: PositionedPiece[], styles: Record<string, { fontFamily?: string }>, query: string,
  viewport: Viewport, transform: Transform, measure: CanvasRenderingContext2D): HighlightBox[] {
  return highlightRanges(pieces, query).map(range => {
    const piece = pieces[range.item];
    const [, , c, d, x, y] = transform(viewport.transform, piece.transform);
    const height = Math.hypot(c, d);
    const width = piece.width * viewport.scale;
    measure.font = `${height}px ${styles[piece.fontName]?.fontFamily ?? "serif"}`;
    const full = measure.measureText(piece.str).width || 1;
    const before = measure.measureText(piece.str.slice(0, range.start)).width / full;
    const inside = measure.measureText(piece.str.slice(range.start, range.end)).width / full;
    return { left: x + before * width, top: y - height, width: Math.max(2, inside * width), height: height * 1.15, match: range.match };
  });
}

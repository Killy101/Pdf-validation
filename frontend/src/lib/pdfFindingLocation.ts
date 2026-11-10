import type { PdfFinding } from "./pdfValidation";

export function findingOnPdfPage(finding: PdfFinding, page: number): boolean {
  return finding.pdf_page != null && page >= finding.pdf_page && page <= (finding.pdf_page_end ?? finding.pdf_page);
}

export function findingPdfPages(finding: PdfFinding, totalPages = 2000): number[] {
  const first = finding.pdf_page;
  if (first == null || !Number.isInteger(first) || first < 1 || first > totalPages) return [];
  const last = Math.min(Math.max(first, finding.pdf_page_end ?? first), totalPages);
  return Array.from({ length: last - first + 1 }, (_, index) => first + index);
}

export function findingPageLabel(finding: PdfFinding): string {
  if (finding.pdf_page == null) return "Document-level finding";
  const first = finding.pdf_page, last = finding.pdf_page_end ?? first;
  if (finding.approximate_location) return `Near uploaded PDF page ${first}`;
  return last > first ? `Uploaded PDF pages ${first}-${last}` : `Uploaded PDF page ${first}`;
}

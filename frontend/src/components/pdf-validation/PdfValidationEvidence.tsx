import type { PdfLayoutEvidence, PdfValidationResult } from "@/lib/pdfValidation";
import { pdfLanguageName } from "@/lib/pdfLanguage";

function layoutLabel(layout?: PdfLayoutEvidence | null) {
  if (!layout) return "Not determined";
  const languages = layout.languages.map(pdfLanguageName).join(" + ");
  return `${layout.columns === 2 ? "Two main text columns" : layout.columns === 1 ? "Single main text column" : "Columns not determined"}; ${languages}${layout.parallel_bilingual ? " (parallel languages)" : ""}`;
}

function timestamp(value?: string | null) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : "Not recorded";
}

export function PdfValidationEvidence({result}: {result: PdfValidationResult}) {
  if (!result.pdf_layout && !result.pdf_dates && !result.website_modified_on) return null;
  return <section aria-label="Comparison scope and dates" className="space-y-3 rounded-xl border border-sky-200 bg-sky-50/50 p-3 text-sm dark:border-sky-900 dark:bg-sky-950/20">
    <h3 className="font-semibold">Comparison scope and dates</h3>
    <dl className="grid gap-3 sm:grid-cols-2">
      <div><dt className="font-medium">Uploaded PDF layout</dt><dd>{layoutLabel(result.pdf_layout)}</dd></div>
      <div><dt className="font-medium">Source document layout</dt><dd>{layoutLabel(result.source_layout)}</dd></div>
      <div><dt className="font-medium">Compared language</dt><dd>{result.language_alignment === "needs_review" ? "Language selection needs review" : result.comparison_language && result.comparison_language !== "all"
        ? `${pdfLanguageName(result.comparison_language)} only` : "All extracted text; no language column excluded"}</dd></div>
      <div><dt className="font-medium">Formatting handling</dt><dd>Whitespace and confirmed line-wrap hyphens are normalized. Meaningful punctuation is checked.</dd></div>
    </dl>
    {Boolean(result.scope_notes?.length) && <ul className="list-disc space-y-1 pl-5 text-xs leading-5">{result.scope_notes!.map(note => <li key={note}>{note}</li>)}</ul>}
    <dl className="grid gap-3 border-t border-sky-100 pt-3 text-xs sm:grid-cols-2 dark:border-sky-900">
      <div><dt className="font-medium">Uploaded document current to</dt><dd>{result.pdf_dates?.current_to || "Not stated"}</dd></div>
      <div><dt className="font-medium">Source document current to</dt><dd>{result.source_dates?.current_to || "Not stated"}</dd></div>
      <div><dt className="font-medium">Website page modified</dt><dd>{result.website_modified_on || "Not supplied by this source"}</dd></div>
      <div><dt className="font-medium">Original PDF download date</dt><dd>Not recorded reliably in PDF metadata</dd></div>
      <div><dt className="font-medium">Uploaded PDF created (metadata)</dt><dd>{timestamp(result.pdf_dates?.creation_date)}</dd></div>
      <div><dt className="font-medium">Uploaded PDF modified (metadata)</dt><dd>{timestamp(result.pdf_dates?.modification_date)}</dd></div>
      <div><dt className="font-medium">Source PDF created (metadata)</dt><dd>{timestamp(result.source_dates?.creation_date)}</dd></div>
      <div><dt className="font-medium">Source PDF modified (metadata)</dt><dd>{timestamp(result.source_dates?.modification_date)}</dd></div>
    </dl>
    <p className="text-xs leading-5 text-slate-600 dark:text-slate-400">Current-to dates describe the document edition. Website and PDF modification dates do not establish which wording changed or when this file was downloaded. Layout detection describes main text columns; tables may have additional columns.</p>
  </section>;
}

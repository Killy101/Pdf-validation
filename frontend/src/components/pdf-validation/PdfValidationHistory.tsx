"use client";

import { PDF_JURISDICTIONS, PdfHistoricalReference, PdfValidationResult } from "@/lib/pdfValidation";

const LABELS = { match: "Match", mismatch: "Mismatch", needs_review: "Needs review", unable: "Unable to validate" };

export function PdfHistoricalSources({ versions }: { versions: PdfHistoricalReference[] }) {
  return <ul aria-label="Historical reference versions" className="space-y-2 rounded-xl bg-sky-50 p-3 text-xs dark:bg-sky-950/30">
    {versions.map(item => <li key={`${item.url}-${item.valid_from}`} className="break-words">
      <a href={item.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-sky-700 underline dark:text-sky-300">{item.label}</a>
      <span className="ml-2 text-slate-600 dark:text-slate-300">{item.valid_from} to {item.valid_to ?? "present"}{!item.available ? " (source host unavailable)" : ""}</span>
    </li>)}
  </ul>;
}

export function PdfValidationHistory({ report, selected, onSelect }: {
  report: PdfValidationResult; selected: number; onSelect: (index: number) => void;
}) {
  const versions = report.versions ?? [];
  return <section aria-label="Historical date range results" className="space-y-3 rounded-2xl border border-sky-200 bg-sky-50/60 p-4 text-sm dark:border-sky-900 dark:bg-sky-950/30">
    <p className="font-bold text-slate-900 dark:text-slate-100">{PDF_JURISDICTIONS[report.jurisdiction ?? "other"]} | {report.date_start} to {report.date_end}</p>
    <p>{report.summary}</p>
    {!report.history_complete && <p role="status" className="font-semibold text-amber-800 dark:text-amber-300">Historical coverage is incomplete; this result does not establish a match for the whole date range.</p>}
    {report.limitations.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600 dark:text-slate-300">
      {report.limitations.map(item => <li key={item}>{item}</li>)}
    </ul>}
    {versions.length > 0 && <div>
      <label htmlFor="validation-historical-version" className="mb-1.5 block text-xs font-bold">Historical version to view</label>
      <select id="validation-historical-version" value={selected} onChange={event => onSelect(Number(event.target.value))}
        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900">
        {versions.map((item, index) => <option key={`${item.reference.url}-${index}`} value={index}>
          {item.reference.valid_from} to {item.reference.valid_to ?? "present"}: {LABELS[item.result.status]} - {item.reference.label}
        </option>)}
      </select>
    </div>}
  </section>;
}

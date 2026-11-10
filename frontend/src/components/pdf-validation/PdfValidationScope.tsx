"use client";

import { PdfValidationOptions } from "@/lib/pdfValidation";

const INPUT = "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20 disabled:opacity-50";
const LABEL = "mb-1.5 block text-xs font-bold text-slate-700 dark:text-slate-300";

export function PdfValidationScope({ value, onChange, disabled, maxVersions }: {
  value: PdfValidationOptions; onChange: (value: PdfValidationOptions) => void; disabled: boolean; maxVersions: number;
}) {
  const update = (changes: Partial<PdfValidationOptions>) => onChange({ ...value, ...changes });
  return <div className="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
    <div>
      <label htmlFor="validation-workflow" className={LABEL}>Workflow</label>
      <select id="validation-workflow" value={value.workflow ?? "current"} disabled={disabled} className={INPUT}
        onChange={event => update({ workflow: event.target.value as PdfValidationOptions["workflow"] })}>
        <option value="current">Current version or specific edition</option>
        <option value="date_range">Historical date range</option>
      </select>
    </div>
    <p className="text-xs text-slate-500">Accepts accessible public PDFs and supported document pages from any jurisdiction. The source is detected automatically.</p>
    {value.workflow === "date_range" && <>
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label htmlFor="validation-date-start" className={LABEL}>From date</label>
          <input id="validation-date-start" type="date" required disabled={disabled} value={value.date_start ?? ""}
            max={value.date_end || undefined} className={INPUT} onChange={event => update({ date_start: event.target.value })} /></div>
        <div><label htmlFor="validation-date-end" className={LABEL}>To date</label>
          <input id="validation-date-end" type="date" required disabled={disabled} value={value.date_end ?? ""}
            min={value.date_start || undefined} className={INPUT} onChange={event => update({ date_end: event.target.value })} /></div>
      </div>
      <p className="text-xs text-slate-500">Both dates are included. Compare each version that applied during this period, up to {maxVersions} versions per PDF. Historical availability depends on the publisher.</p>
      <details className="text-xs text-slate-600 dark:text-slate-300">
        <summary className="cursor-pointer font-semibold">Use a separate version history page</summary>
        <label htmlFor="validation-history-url" className={`${LABEL} mt-3`}>Version history URL (optional)</label>
        <input id="validation-history-url" type="url" maxLength={2048} disabled={disabled} value={value.history_url ?? ""}
          placeholder="https://publisher.example/document/versions" className={INPUT}
          onChange={event => update({ history_url: event.target.value })} />
        <p className="mt-1.5">Use a history page on the source website that lists version links and their effective date periods.</p>
      </details>
    </>}
  </div>;
}

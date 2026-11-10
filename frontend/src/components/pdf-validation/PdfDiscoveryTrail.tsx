import { ChevronRight, Compass } from "lucide-react";
import type { PdfDiscoveryItem, PdfDiscoveryStatus, PdfDiscoveryTrail } from "@/lib/pdfValidation";

const GROUPS: { statuses: PdfDiscoveryStatus[]; title: string; tone: string; open?: boolean }[] = [
  { statuses: ["selected", "verified"], title: "Discovered document", tone: "text-emerald-700 dark:text-emerald-300", open: true },
  { statuses: ["needs_verification"], title: "Still requires verification", tone: "text-amber-700 dark:text-amber-300" },
  { statuses: ["unavailable"], title: "Unavailable", tone: "text-rose-700 dark:text-rose-300", open: true },
  { statuses: ["inaccessible"], title: "Could not be accessed", tone: "text-rose-700 dark:text-rose-300", open: true },
  { statuses: ["rejected"], title: "Checked: a different document", tone: "text-slate-700 dark:text-slate-300" },
  { statuses: ["visited"], title: "Pages opened", tone: "text-slate-700 dark:text-slate-300" },
  { statuses: ["not_relevant"], title: "Not relevant to this PDF", tone: "text-slate-500 dark:text-slate-400" },
];

const STATUS_TEXT = {
  found: "Document found",
  needs_review: "Possible documents need review",
  not_found: "Document not found",
};

function Item({ item }: { item: PdfDiscoveryItem }) {
  return <li className="rounded-lg border border-slate-100 p-2 dark:border-slate-800">
    <a href={item.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-sky-700 underline break-all dark:text-sky-300">{item.label}</a>
    <span className="ml-1.5 rounded bg-slate-100 px-1 font-mono text-[10px] uppercase text-slate-500 dark:bg-slate-800">{item.kind}</span>
    {item.reason && <p className="mt-0.5 text-slate-600 dark:text-slate-300">{item.reason}</p>}
    {item.path.length > 2 && <p className="mt-0.5 text-[11px] text-slate-400">via {item.path.slice(1, -1).map(step => step.label).join(" › ")}</p>}
  </li>;
}

// How a Reference URL led (or did not lead) to the compared document.
export function PdfDiscoveryPath({ trail, compact = false }: { trail: PdfDiscoveryTrail; compact?: boolean }) {
  const steps = trail.path.length ? trail.path : [{ url: trail.start_url, label: "Reference URL" }];
  return <section aria-label="Reference URL discovery" className="space-y-2 rounded-xl border border-slate-200 p-3 text-xs dark:border-slate-700">
    <h3 className="flex items-center gap-1.5 text-sm font-semibold">
      <Compass className="h-4 w-4 text-sky-600" aria-hidden="true" />
      <span>{STATUS_TEXT[trail.status]}</span>
      {trail.document_identity && <span className="font-normal text-slate-500">for {trail.document_identity}</span>}
    </h3>
    <ol aria-label="Navigation path" className="flex flex-wrap items-center gap-1">
      {steps.map((step, index) => <li key={step.url + index} className="flex items-center gap-1">
        {index > 0 && <ChevronRight className="h-3 w-3 text-slate-400" aria-hidden="true" />}
        <a href={step.url} target="_blank" rel="noopener noreferrer" title={step.url}
          className={`rounded-md px-1.5 py-0.5 ${index === steps.length - 1 && trail.selected_url ? "bg-emerald-50 font-semibold text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200" : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"}`}>
          {step.label}
        </a>
      </li>)}
    </ol>
    <p className="text-slate-600 dark:text-slate-300">
      {trail.summary} Opened {trail.pages_visited} page{trail.pages_visited === 1 ? "" : "s"}{trail.browser_pages ? `, ${trail.browser_pages} with browser rendering for interactive menus` : ""}.
    </p>
    {!compact && <div className="space-y-1.5">
      {GROUPS.map(group => {
        const items = trail.items.filter(item => group.statuses.includes(item.status));
        if (!items.length) return null;
        return <details key={group.title} open={group.open && items.length <= 5}>
          <summary className={`cursor-pointer font-semibold ${group.tone}`}>{group.title} ({items.length})</summary>
          <ul className="mt-1.5 max-h-56 space-y-1.5 overflow-auto">{items.map(item => <Item key={item.url} item={item} />)}</ul>
        </details>;
      })}
    </div>}
    {trail.notes.map(note => <p key={note} className="text-[11px] text-slate-500">{note}</p>)}
  </section>;
}

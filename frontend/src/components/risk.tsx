// Risk-related display pieces shared by the dashboard, the report and the charts.
import { RISK_LEVELS, type RiskCounts, type RiskLevel, type Scan } from "../api/types";
import { timeAgo, fullDate } from "../format";
import { Spinner } from "./ui";

export const LEVEL_LABEL: Record<RiskLevel, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
/** Same colours as tailwind.config.js `risk.*`, for charts (Recharts needs hex values). */
export const LEVEL_HEX: Record<RiskLevel, string> = {
  critical: "#dc2626", high: "#ea580c", medium: "#ca8a04", low: "#16a34a",
};
export const LEVEL_BG: Record<RiskLevel, string> = {
  critical: "bg-risk-critical", high: "bg-risk-high", medium: "bg-risk-medium", low: "bg-risk-low",
};
const LEVEL_BADGE: Record<RiskLevel, string> = {
  critical: "bg-red-50 text-red-700 ring-red-600/20",
  high: "bg-orange-50 text-orange-700 ring-orange-600/20",
  medium: "bg-yellow-50 text-yellow-800 ring-yellow-600/20",
  low: "bg-green-50 text-green-700 ring-green-600/20",
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${LEVEL_BADGE[level]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${LEVEL_BG[level]}`} aria-hidden="true" />
      {LEVEL_LABEL[level]}
    </span>
  );
}

/** Stacked bar of files per risk level + legend. */
export function RiskBar({ counts }: { counts: RiskCounts }) {
  const total = RISK_LEVELS.reduce((n, l) => n + counts[l], 0);
  if (!total) return <p className="text-sm text-slate-500">No Python files found.</p>;
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100" role="img"
           aria-label={RISK_LEVELS.map((l) => `${counts[l]} ${l}`).join(", ")}>
        {RISK_LEVELS.map((l) => counts[l] > 0 && (
          <div key={l} className={LEVEL_BG[l]} style={{ width: `${(100 * counts[l]) / total}%` }} />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-4 gap-2">
        {RISK_LEVELS.map((l) => (
          <div key={l}>
            <dt className="flex items-center gap-1.5 text-xs text-slate-500">
              <span className={`h-2 w-2 rounded-full ${LEVEL_BG[l]}`} aria-hidden="true" />
              {LEVEL_LABEL[l]}
            </dt>
            <dd className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">{counts[l]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** What the latest scan is doing right now. `compact`: no "… ago" (when a date is shown next to it). */
export function ScanStatusBadge({ scan, compact = false }: { scan: Scan | null; compact?: boolean }) {
  const when = (iso: string | null) => (compact ? "" : ` ${timeAgo(iso)}`);
  if (!scan) return <span className="text-xs text-slate-500">Never scanned</span>;
  const base = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium";
  switch (scan.status) {
    case "pending":
      return <span className={`${base} bg-slate-100 text-slate-700`}><Spinner className="h-3 w-3" />Queued</span>;
    case "running":
      return <span className={`${base} bg-indigo-50 text-indigo-700`}><Spinner className="h-3 w-3" />Scanning…</span>;
    case "failed":
      return <span className={`${base} bg-red-50 text-red-700`} title={fullDate(scan.finished_at)}>Failed{when(scan.finished_at)}</span>;
    default:
      return (
        <span className={`${base} bg-emerald-50 text-emerald-700`} title={fullDate(scan.finished_at)}>
          <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor" aria-hidden="true">
            <path fillRule="evenodd" d="M16.7 5.3a1 1 0 0 1 0 1.4l-8 8a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.4L8 12.6l7.3-7.3a1 1 0 0 1 1.4 0Z" clipRule="evenodd" />
          </svg>
          {compact ? "Completed" : `Scanned${when(scan.finished_at)}`}
        </span>
      );
  }
}

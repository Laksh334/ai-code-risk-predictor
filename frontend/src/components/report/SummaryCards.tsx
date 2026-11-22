import type { ScanDetail } from "../../api/types";
import { fullDate, timeAgo } from "../../format";

function Card({ label, value, hint, accent }: { label: string; value: string; hint: string; accent?: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-2 text-3xl font-semibold tabular-nums ${accent ?? "text-slate-900"}`}>{value}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

export function SummaryCards({ scan }: { scan: ScanDetail }) {
  const urgent = scan.risk_counts.critical + scan.risk_counts.high;
  // Calibrated risk = probability, so the sum over files = expected number of files needing fixes.
  const expected = (scan.overall_risk ?? 0) * scan.total_files;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card label="Files analysed" value={String(scan.total_files)}
            hint={`Scanned ${timeAgo(scan.finished_at)} · ${scan.commit_sha?.slice(0, 8) ?? ""}`} />
      <Card label="Need attention" value={String(urgent)} accent={urgent ? "text-risk-critical" : "text-risk-low"}
            hint={`${scan.risk_counts.critical} critical + ${scan.risk_counts.high} high risk`} />
      <Card label="Expected bug-prone files" value={expected.toFixed(1)}
            hint="Files likely to need a bug fix in the next 6 months" />
      <Card label="Model" value={scan.model_version?.split("-")[0] ?? "–"}
            hint={`Version ${scan.model_version ?? "?"} · ${fullDate(scan.finished_at)}`} />
    </div>
  );
}

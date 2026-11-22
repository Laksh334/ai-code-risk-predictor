// The full risk report of one scan: summary, donut, quality, ranked table.
// Table filters live in the URL (?level=critical&q=app&sort=loc&page=2) so a view can be shared.
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../../api/client";
import { RISK_LEVELS, type FileSort, type RiskLevel, type ScanDetail } from "../../api/types";
import { DebtChart } from "../charts/DebtChart";
import { Alert, Spinner } from "../ui";
import { FileTable, type TableState } from "./FileTable";
import { QualityPanel } from "./QualityPanel";
import { RiskDonut } from "./RiskDonut";
import { SummaryCards } from "./SummaryCards";

const SORTS: FileSort[] = ["priority", "risk_score", "complexity", "churn", "bug_fix_count", "num_developers", "loc"];

function readState(p: URLSearchParams): TableState {
  const level = p.get("level") as RiskLevel | null;
  const sort = p.get("sort") as FileSort | null;
  return {
    level: level && RISK_LEVELS.includes(level) ? level : null,
    q: p.get("q") ?? "",
    sort: sort && SORTS.includes(sort) ? sort : "priority",
    page: Math.max(1, Number(p.get("page")) || 1),
  };
}

/** Grey placeholders in the shape of the report, so the page doesn't jump when data arrives. */
function ReportSkeleton() {
  const block = "animate-pulse motion-reduce:animate-none rounded-2xl bg-slate-200/60";
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading report">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <div key={i} className={`h-[118px] ${block}`} />)}
      </div>
      <div className={`h-80 ${block}`} />
      <div className="grid gap-6 lg:grid-cols-2">
        <div className={`h-64 ${block}`} />
        <div className={`h-64 ${block}`} />
      </div>
      <div className={`h-96 ${block}`} />
      <span className="sr-only"><Spinner /> Loading report…</span>
    </div>
  );
}

export function ScanReport({ scanId }: { scanId: number }) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const state = readState(params);

  useEffect(() => {
    setScan(null);
    api<ScanDetail>(`/api/scans/${scanId}`).then(setScan).catch((e) => setError((e as Error).message));
  }, [scanId]);

  const update = useCallback((change: Partial<TableState>) => {
    setParams((prev) => {
      const next = { ...readState(prev), ...change };
      const out = new URLSearchParams();
      if (next.level) out.set("level", next.level);
      if (next.q) out.set("q", next.q);
      if (next.sort !== "priority") out.set("sort", next.sort);
      if (next.page > 1) out.set("page", String(next.page));
      return out;
    }, { replace: true });
  }, [setParams]);

  if (error) return <Alert>{error}</Alert>;
  if (!scan) return <ReportSkeleton />;

  return (
    <div className="space-y-6">
      <SummaryCards scan={scan} />
      <DebtChart repoId={scan.repository_id} />
      <div className="grid gap-6 lg:grid-cols-2">
        <RiskDonut counts={scan.risk_counts} selected={state.level} onSelect={(level) => update({ level, page: 1 })} />
        <QualityPanel scan={scan} />
      </div>
      <FileTable repoId={scan.repository_id} scanId={scan.id} counts={scan.risk_counts} state={state} onChange={update} />
    </div>
  );
}

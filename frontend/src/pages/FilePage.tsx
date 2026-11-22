// One file of one scan: risk, why (SHAP), what to do, every metric, risk over time, recent commits.
import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { FileAnalysis, FileHistory, Repository, ScanDetail } from "../api/types";
import { RiskHistoryChart } from "../components/charts/RiskHistoryChart";
import { ShapChart } from "../components/charts/ShapChart";
import { RiskBadge } from "../components/risk";
import { Alert, Spinner } from "../components/ui";
import { fullDate, timeAgo } from "../format";
import { usePageTitle } from "../hooks";
import { METRIC_GROUPS, formatMetric, metricValue } from "../metrics";

function Card({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200 ${className}`}>
      <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function FilePage() {
  const { repoId, scanId, fileId } = useParams();
  const [repo, setRepo] = useState<Repository | null>(null);
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [file, setFile] = useState<FileAnalysis | null>(null);
  const [history, setHistory] = useState<FileHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  usePageTitle(file ? file.file_path.split("/").pop() : null);

  useEffect(() => {
    let cancelled = false;
    if (![repoId, scanId, fileId].every((x) => /^\d+$/.test(x ?? ""))) {
      setError("This file isn't part of that scan.");
      return;
    }
    (async () => {
      try {
        const [r, s, f] = await Promise.all([
          api<Repository>(`/api/repositories/${repoId}`),
          api<ScanDetail>(`/api/scans/${scanId}`),
          api<FileAnalysis>(`/api/scans/${scanId}/files/${fileId}`),
        ]);
        if (cancelled) return;
        setRepo(r); setScan(s); setFile(f);
        const h = await api<FileHistory>(`/api/repositories/${repoId}/file-history?path=${encodeURIComponent(f.file_path)}&commits=15`)
          .catch(() => null);
        if (!cancelled) setHistory(h);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError && e.status === 404 ? "This file isn't part of that scan." : (e as Error).message);
      }
    })();
    return () => { cancelled = true; };
  }, [repoId, scanId, fileId]);

  if (error) return <div className="py-16"><Alert>{error}</Alert></div>;
  if (!repo || !scan || !file) return <div className="grid place-items-center py-24 text-slate-400"><Spinner className="h-6 w-6" /></div>;

  const name = file.file_path.split("/").pop();
  const githubUrl = `${repo.url}/blob/${scan.commit_sha ?? repo.default_branch}/${file.file_path}`;
  const features = (file.explanation ?? []).map((e) => ({ label: e.label ?? e.feature, impact: e.impact, value: e.value }));
  const factors = (file.factors ?? []).map((f) => ({ label: f.label, impact: f.impact }));
  const isLatest = repo.report_scan_id === scan.id;

  return (
    <div className="space-y-6">
      <nav aria-label="Breadcrumb" className="flex flex-wrap gap-1 text-sm text-slate-500">
        <Link to="/" className="hover:text-slate-700">Repositories</Link><span aria-hidden="true">/</span>
        <Link to={`/repos/${repo.id}`} className="hover:text-slate-700">{repo.full_name}</Link><span aria-hidden="true">/</span>
        <span className="text-slate-900">{name}</span>
      </nav>

      {!isLatest && <Alert tone="info">You're viewing an older scan ({fullDate(scan.finished_at)}). <Link className="underline" to={`/repos/${repo.id}`}>See the latest report</Link></Alert>}

      <header className="flex flex-wrap items-start justify-between gap-6 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div className="min-w-0">
          <h1 className="break-all font-mono text-lg font-semibold text-slate-900">{file.file_path}</h1>
          <p className="mt-1 text-sm text-slate-500">
            Rank #{file.priority_rank} of {scan.total_files} files · scanned {timeAgo(scan.finished_at)} ·{" "}
            <a href={githubUrl} target="_blank" rel="noreferrer" className="text-indigo-600 hover:text-indigo-500">view on GitHub ↗</a>
          </p>
        </div>
        <div className="text-right">
          <div className="flex items-center justify-end gap-3">
            <span className="text-4xl font-semibold tabular-nums">{Math.round(file.risk_score * 100)}%</span>
            <RiskBadge level={file.risk_level} />
          </div>
          <p className="mt-1 text-xs text-slate-500">chance of needing a bug fix in the next 6 months</p>
        </div>
      </header>

      <section className="rounded-2xl bg-indigo-50 p-6 ring-1 ring-indigo-100">
        <h2 className="text-sm font-semibold text-indigo-900">What to do</h2>
        <p className="mt-2 text-sm leading-relaxed text-indigo-900/90">{file.recommendation}</p>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Why this score: main factors">
          <ShapChart items={factors} title="Factors" />
          <p className="mt-2 text-xs text-slate-500">Red pushes the risk up, green pulls it down (SHAP, compared with a typical file).</p>
        </Card>
        <Card title="Why this score: individual metrics">
          <ShapChart items={features} title="Metrics" />
          <p className="mt-2 text-xs text-slate-500">The 6 metrics with the biggest effect on this file's score, with their values.</p>
        </Card>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card title="Risk over time">
          {history ? <RiskHistoryChart points={history.risk_over_time} /> : <p className="text-sm text-slate-500">No history available.</p>}
        </Card>
        <Card title="Recent commits">
          {!history?.recent_commits.length ? (
            <p className="text-sm text-slate-500">No commits recorded for this file.</p>
          ) : (
            <ul className="-my-2 divide-y divide-slate-100">
              {history.recent_commits.map((c) => (
                <li key={c.commit_sha} className="flex gap-3 py-2.5">
                  <a href={`${repo.url}/commit/${c.commit_sha}`} target="_blank" rel="noreferrer"
                     className="shrink-0 font-mono text-xs text-indigo-600 hover:underline">{c.commit_sha.slice(0, 7)}</a>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-slate-800" title={c.commit_message ?? ""}>
                      {c.is_bug_fix && <span className="mr-1.5 rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">BUG FIX</span>}
                      {c.commit_message?.split("\n")[0]}
                    </p>
                    <p className="text-xs text-slate-500">
                      {c.author} · <span title={fullDate(c.commit_date)}>{timeAgo(c.commit_date)}</span> ·{" "}
                      <span className="text-emerald-700">+{c.lines_added}</span> <span className="text-red-600">−{c.lines_deleted}</span>
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="All measurements">
        <div className="grid gap-8 md:grid-cols-2 xl:grid-cols-4">
          {METRIC_GROUPS.map((g) => (
            <div key={g.title}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{g.title}</h3>
              <dl className="mt-2 space-y-1.5">
                {g.items.map((m) => (
                  <div key={m.key} className="flex justify-between gap-3 border-b border-slate-100 pb-1.5 text-sm">
                    <dt className="text-slate-600" title={m.help}>{m.label}</dt>
                    <dd className="shrink-0 font-medium tabular-nums text-slate-900">{formatMetric(metricValue(file, m.key), m.fmt)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

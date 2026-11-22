// One repository: header, the full risk report of the latest completed scan, scan history.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { isActive, type Page, type Repository, type Scan } from "../api/types";
import { HeatmapView } from "../components/heatmap/HeatmapView";
import { ScanReport } from "../components/report/ScanReport";
import { ScanStatusBadge } from "../components/risk";
import { Alert, Button, Spinner } from "../components/ui";
import { fullDate, timeAgo } from "../format";
import { usePageTitle, usePolling } from "../hooks";
import { useRepos } from "../store/repos";

const TABS = [
  { id: "report", label: "Risk report" },
  { id: "heatmap", label: "Codebase heatmap" },
] as const;

const TRIGGER_LABEL ={ manual: "Manual", push: "Push to main", pull_request: "Pull request", history: "History" };

export function RepoPage() {
  const id = Number(useParams().repoId);
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "heatmap" ? "heatmap" : "report";
  const validId = Number.isInteger(id) && id > 0;
  const startScan = useRepos((s) => s.startScan);
  const [repo, setRepo] = useState<Repository | null>(null);
  const [scans, setScans] = useState<Scan[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    if (!validId) { setNotFound(true); return; }
    try {
      const [r, s] = await Promise.all([
        api<Repository>(`/api/repositories/${id}`),
        api<Page<Scan>>(`/api/repositories/${id}/scans?limit=20`),
      ]);
      setRepo(r);
      setScans(s.items);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setNotFound(true);
      else setError((e as Error).message);
    }
  }, [id, validId]);

  useEffect(() => { load(); }, [load]);
  usePolling(load, isActive(repo?.latest_scan));
  usePageTitle(notFound ? "Repository not found" : repo?.full_name);

  async function rescan() {
    setStarting(true);
    try {
      await startScan(id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  if (notFound) {
    return (
      <div className="py-16 text-center">
        <h1 className="text-xl font-semibold">Repository not found</h1>
        <Link to="/" className="mt-3 inline-block text-sm font-medium text-indigo-600">Back to repositories</Link>
      </div>
    );
  }
  if (!repo) {
    return <div className="grid place-items-center py-24 text-slate-500">{error ? <Alert>{error}</Alert> : <Spinner className="h-6 w-6" />}</div>;
  }

  return (
    <div className="space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm text-slate-500">
        <Link to="/" className="hover:text-slate-700">Repositories</Link> <span aria-hidden="true">/</span>{" "}
        <span className="text-slate-900">{repo.full_name}</span>
      </nav>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{repo.full_name}</h1>
          <div className="mt-2 flex items-center gap-3">
            <ScanStatusBadge scan={repo.latest_scan} />
            <a href={repo.url} target="_blank" rel="noreferrer" className="text-sm text-slate-500 hover:text-slate-700">
              View on GitHub ↗
            </a>
          </div>
        </div>
        <Button onClick={rescan} loading={starting} disabled={isActive(repo.latest_scan)}>
          {isActive(repo.latest_scan) ? "Scan running…" : "Scan now"}
        </Button>
      </header>

      {error && <Alert>{error}</Alert>}
      {repo.latest_scan?.status === "failed" && <Alert>Last scan failed: {repo.latest_scan.error_message}</Alert>}

      {repo.report_scan_id ? (
        <>
          {isActive(repo.latest_scan) && (
            <Alert tone="info">A new scan is running. You're looking at the previous report until it finishes.</Alert>
          )}
          <div className="flex gap-1 border-b border-slate-200" role="tablist" aria-label="Report views">
            {TABS.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={view === t.id}
                      onClick={() => setParams(t.id === "heatmap" ? { view: "heatmap" } : {}, { replace: true })}
                      className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition
                        ${view === t.id ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <div role="tabpanel">
            {view === "heatmap"
              ? <HeatmapView repoId={repo.id} scanId={repo.report_scan_id} repoName={repo.full_name.split("/")[1]} />
              : <ScanReport scanId={repo.report_scan_id} />}
          </div>
        </>
      ) : (
        <section className="rounded-2xl bg-white p-10 text-center shadow-sm ring-1 ring-slate-200">
          {isActive(repo.latest_scan) ? (
            <p className="inline-flex items-center gap-2 text-sm text-slate-600">
              <Spinner /> The first scan is running. The report appears here when it's done (usually 1–2 minutes).
            </p>
          ) : (
            <p className="text-sm text-slate-600">No completed scan yet. Click <b>Scan now</b> to create the first report.</p>
          )}
        </section>
      )}

      <section className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
        <h2 className="border-b border-slate-100 px-6 py-4 text-sm font-semibold text-slate-900">Scan history</h2>
        {scans.length === 0 ? (
          <p className="px-6 py-8 text-sm text-slate-500">No scans yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-3 py-3 sm:px-6">Started</th>
                  <th scope="col" className="px-3 py-3 sm:px-6">Trigger</th>
                  <th scope="col" className="px-3 py-3 sm:px-6">Status</th>
                  <th scope="col" className="hidden px-6 py-3 sm:table-cell">Commit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {scans.map((s) => (
                  <tr key={s.id}>
                    <td className="whitespace-nowrap px-3 py-3 sm:px-6" title={fullDate(s.created_at)}>{timeAgo(s.created_at)}</td>
                    <td className="whitespace-nowrap px-3 py-3 sm:px-6">
                      {TRIGGER_LABEL[s.trigger]}{s.pr_number ? ` #${s.pr_number}` : ""}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 sm:px-6"><ScanStatusBadge scan={s} compact /></td>
                    <td className="hidden px-6 py-3 font-mono text-xs text-slate-500 sm:table-cell">{s.commit_sha?.slice(0, 8) ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

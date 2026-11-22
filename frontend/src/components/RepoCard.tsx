import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { isActive, type Repository } from "../api/types";
import { useRepos } from "../store/repos";
import { ConfirmDialog } from "./ConfirmDialog";
import { RiskBar, ScanStatusBadge } from "./risk";
import { Button } from "./ui";

export function RepoCard({ repo }: { repo: Repository }) {
  const startScan = useRepos((s) => s.startScan);
  const deleteRepo = useRepos((s) => s.deleteRepo);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<"scan" | "delete" | null>(null);
  const scan = repo.latest_scan;
  const active = isActive(scan);

  async function run(kind: "scan" | "delete", fn: () => Promise<unknown>) {
    setBusy(kind);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className="flex flex-col rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-slate-900">
            <Link to={`/repos/${repo.id}`} className="hover:text-indigo-600 focus:outline-none focus-visible:underline">
              {repo.full_name}
            </Link>
          </h3>
          <a href={repo.url} target="_blank" rel="noreferrer"
             className="mt-0.5 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700">
            github.com/{repo.full_name}
            <svg viewBox="0 0 20 20" className="h-3 w-3" fill="currentColor" aria-hidden="true">
              <path d="M11 3a1 1 0 1 0 0 2h2.59l-6.3 6.3a1 1 0 1 0 1.42 1.4L15 6.42V9a1 1 0 1 0 2 0V4a1 1 0 0 0-1-1h-5Z" />
              <path d="M5 5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-3a1 1 0 1 0-2 0v3H5V7h3a1 1 0 0 0 0-2H5Z" />
            </svg>
          </a>
        </div>
        <ScanStatusBadge scan={scan} />
      </header>

      <div className="mt-5 flex-1">
        {repo.risk_counts ? (
          <RiskBar counts={repo.risk_counts} />
        ) : active ? (
          <p className="text-sm text-slate-500">
            Analysing the code and its Git history… The first scan of a repository takes a minute or two.
          </p>
        ) : (
          <p className="text-sm text-slate-500">No report yet. Start a scan to see which files are risky.</p>
        )}
        {scan?.status === "failed" && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{scan.error_message}</p>
        )}
        {error && <p role="alert" className="mt-3 text-xs text-red-600">{error}</p>}
      </div>

      <footer className="mt-5 flex items-center gap-2 border-t border-slate-100 pt-4">
        {repo.report_scan_id ? (
          <Link to={`/repos/${repo.id}`}
                className="inline-flex items-center rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500">
            View report
          </Link>
        ) : null}
        <Button variant="secondary" className="!px-3 !py-2" disabled={active} loading={busy === "scan"}
                onClick={() => run("scan", () => startScan(repo.id))}>
          {active ? "Scan running" : repo.report_scan_id ? "Rescan" : "Scan now"}
        </Button>
        <Button variant="ghost" className="ml-auto !px-3 !py-2 hover:!text-red-600"
                onClick={() => setConfirming(true)} aria-label={`Delete ${repo.full_name}`}>
          Delete
        </Button>
      </footer>

      <ConfirmDialog
        open={confirming}
        title={`Delete ${repo.full_name}?`}
        confirmLabel="Delete repository"
        danger
        loading={busy === "delete"}
        onCancel={() => setConfirming(false)}
        onConfirm={() => run("delete", () => deleteRepo(repo.id))}
      >
        This removes the repository and all its scans, risk reports and history from your dashboard.
        It can't be undone. Nothing changes on GitHub.
      </ConfirmDialog>
    </article>
  );
}

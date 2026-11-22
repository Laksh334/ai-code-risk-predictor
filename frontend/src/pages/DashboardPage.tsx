// Dashboard home: the user's repositories, add a new one, start scans.
import { useEffect } from "react";

import { AddRepoForm } from "../components/AddRepoForm";
import { RepoCard } from "../components/RepoCard";
import { LEVEL_BG, LEVEL_LABEL } from "../components/risk";
import { Alert, Button, Spinner } from "../components/ui";
import { RISK_LEVELS } from "../api/types";
import { usePageTitle, usePolling } from "../hooks";
import { useRepos } from "../store/repos";

const LEVEL_TEXT = { critical: "≥ 35% chance of a bug fix in 6 months", high: "20–35%", medium: "10–20%", low: "< 10%" };

export function DashboardPage() {
  const { repos, loaded, error, fetchRepos } = useRepos();
  const scanning = useRepos((s) => s.anyScanActive());
  usePageTitle("Repositories");

  useEffect(() => { fetchRepos(); }, [fetchRepos]);
  usePolling(fetchRepos, scanning); // refresh while a scan is queued/running

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
          <p className="mt-1 text-sm text-slate-600">
            Which files are most likely to need bug fixes in the next 6 months.
          </p>
        </div>
        {scanning && (
          <p className="inline-flex items-center gap-2 text-sm text-indigo-700" role="status">
            <Spinner /> A scan is running, this page updates by itself.
          </p>
        )}
      </div>

      <AddRepoForm />

      {error && (
        <Alert>
          {error} <Button variant="ghost" className="!p-0 !underline" onClick={fetchRepos}>Try again</Button>
        </Alert>
      )}

      {!loaded ? (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => <div key={i} className="h-56 animate-pulse motion-reduce:animate-none rounded-2xl bg-slate-200/60" />)}
        </div>
      ) : repos.length === 0 && !error ? (
        <section className="rounded-2xl border-2 border-dashed border-slate-300 bg-white px-6 py-14 text-center">
          <h2 className="text-base font-semibold">No repositories yet</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-slate-600">
            Paste a GitHub link above, for example <code className="rounded bg-slate-100 px-1">https://github.com/pallets/flask</code>,
            to get a prioritised risk report for every Python file.
          </p>
        </section>
      ) : (
        <section aria-label="Your repositories" className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {repos.map((r) => <RepoCard key={r.id} repo={r} />)}
        </section>
      )}

      <section aria-labelledby="levels" className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <h2 id="levels" className="text-sm font-semibold text-slate-900">How to read risk levels</h2>
        <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {RISK_LEVELS.map((l) => (
            <div key={l} className="flex items-start gap-3">
              <span className={`mt-1 h-3 w-3 shrink-0 rounded-full ${LEVEL_BG[l]}`} aria-hidden="true" />
              <div>
                <dt className="text-sm font-medium">{LEVEL_LABEL[l]}</dt>
                <dd className="text-xs text-slate-500">{LEVEL_TEXT[l]}</dd>
              </div>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

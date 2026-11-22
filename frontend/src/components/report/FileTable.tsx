// The prioritised risk ranking: one row per file, riskiest first.
import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import { RISK_LEVELS, type FileAnalysis, type FileSort, type Page, type RiskCounts, type RiskLevel } from "../../api/types";
import { LEVEL_HEX, LEVEL_LABEL, RiskBadge } from "../risk";
import { Alert, Spinner } from "../ui";

export const PAGE_SIZE = 25;
const SORTS: { value: FileSort; label: string }[] = [
  { value: "priority", label: "Priority (riskiest first)" },
  { value: "complexity", label: "Most complex" },
  { value: "churn", label: "Most changed lines" },
  { value: "bug_fix_count", label: "Most bug fixes" },
  { value: "num_developers", label: "Most developers" },
  { value: "loc", label: "Largest" },
];

export interface TableState {
  level: RiskLevel | null;
  q: string;
  sort: FileSort;
  page: number;
}

const fmt = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString());

function PathCell({ path, to }: { path: string; to: string }) {
  const i = path.lastIndexOf("/");
  return (
    <Link to={to} className="group font-mono text-[13px] focus:outline-none focus-visible:underline" title={`${path}: open details`}>
      {/* phones: file name only (the folder is on the file page / in the tooltip) */}
      <span className="hidden text-slate-400 sm:inline">{i >= 0 ? path.slice(0, i + 1) : ""}</span>
      <span className="font-semibold text-slate-900 group-hover:text-indigo-600 group-hover:underline">{path.slice(i + 1)}</span>
    </Link>
  );
}

function ScoreCell({ f }: { f: FileAnalysis }) {
  return (
    <div className="flex items-center gap-3">
      <div className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-slate-100 sm:block" aria-hidden="true">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, f.risk_score * 200)}%`, background: LEVEL_HEX[f.risk_level] }} />
      </div>
      <span className="inline-flex w-12 items-center gap-1.5 tabular-nums font-semibold">
        {/* phones: a coloured dot instead of the badge, so the row fits without scrolling */}
        <span className="h-2 w-2 shrink-0 rounded-full sm:hidden" style={{ background: LEVEL_HEX[f.risk_level] }}
              aria-hidden="true" />
        {Math.round(f.risk_score * 100)}%
        <span className="sr-only sm:hidden">{LEVEL_LABEL[f.risk_level]}</span>
      </span>
      <span className="hidden sm:inline-flex"><RiskBadge level={f.risk_level} /></span>
    </div>
  );
}

/** Why: SHAP factors that push this file's risk up (red) or down (green). */
export function FactorBars({ factors }: { factors: FileAnalysis["factors"] }) {
  if (!factors?.length) return null;
  const max = Math.max(...factors.map((x) => Math.abs(x.impact)), 0.01);
  return (
    <ul className="space-y-1.5">
      {factors.slice(0, 6).map((x) => (
        <li key={x.factor} className="grid grid-cols-[9rem_1fr_3.5rem] items-center gap-3 text-xs">
          <span className="truncate text-slate-600">{x.label}</span>
          <div className="relative h-2 rounded-full bg-slate-100">
            <div className={`absolute top-0 h-2 rounded-full ${x.impact >= 0 ? "left-1/2 bg-red-400" : "right-1/2 bg-emerald-400"}`}
                 style={{ width: `${(50 * Math.abs(x.impact)) / max}%` }} />
            <div className="absolute left-1/2 top-[-2px] h-3 w-px bg-slate-300" />
          </div>
          <span className={`text-right tabular-nums ${x.impact >= 0 ? "text-red-600" : "text-emerald-600"}`}>
            {x.impact >= 0 ? "+" : ""}{x.impact.toFixed(2)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function FileTable({ repoId, scanId, counts, state, onChange }: {
  repoId: number;
  scanId: number;
  counts: RiskCounts;
  state: TableState;
  onChange: (s: Partial<TableState>) => void;
}) {
  const [data, setData] = useState<Page<FileAnalysis> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [search, setSearch] = useState(state.q);

  // Debounce typing: query the server 300 ms after the user stops.
  useEffect(() => {
    const t = setTimeout(() => search !== state.q && onChange({ q: search, page: 1 }), 300);
    return () => clearTimeout(t);
  }, [search, state.q, onChange]);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ sort: state.sort, limit: String(PAGE_SIZE), offset: String((state.page - 1) * PAGE_SIZE) });
    if (state.level) params.set("risk_level", state.level);
    if (state.q) params.set("q", state.q);
    setLoading(true);
    api<Page<FileAnalysis>>(`/api/scans/${scanId}/files?${params}`)
      .then((d) => { if (!cancelled) { setData(d); setError(null); } })
      .catch((e) => { if (!cancelled) setError((e as Error).message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [scanId, state.level, state.q, state.sort, state.page]);

  const total = RISK_LEVELS.reduce((n, l) => n + counts[l], 0);
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <section className="overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200" aria-labelledby="ranking-title">
      <div className="space-y-4 border-b border-slate-100 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="ranking-title" className="text-sm font-semibold text-slate-900">Prioritised risk ranking</h2>
          {loading && data && <Spinner className="h-4 w-4 text-slate-400" />}
        </div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by risk level">
          {[null, ...RISK_LEVELS].map((l) => (
            <button key={l ?? "all"} type="button" aria-pressed={state.level === l}
                    onClick={() => onChange({ level: l, page: 1 })}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition
                      ${state.level === l ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"}`}>
              {l && <span className="h-2 w-2 rounded-full" style={{ background: LEVEL_HEX[l] }} aria-hidden="true" />}
              {l ? LEVEL_LABEL[l] : "All"} <span className="opacity-60">{l ? counts[l] : total}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <label className="sr-only" htmlFor="file-search">Search files</label>
          <input id="file-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder="Search file paths…"
                 className="block w-full flex-1 rounded-lg border-0 px-3 py-2 text-sm shadow-sm ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-indigo-600" />
          <label className="sr-only" htmlFor="file-sort">Sort by</label>
          <select id="file-sort" value={state.sort} onChange={(e) => onChange({ sort: e.target.value as FileSort, page: 1 })}
                  className="rounded-lg border-0 py-2 pl-3 pr-8 text-sm shadow-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-indigo-600">
            {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
      </div>

      {error && <div className="p-5"><Alert>{error}</Alert></div>}
      {!data && loading ? (
        <div className="grid place-items-center py-16 text-slate-400"><Spinner className="h-6 w-6" /></div>
      ) : data && data.items.length === 0 ? (
        <p className="px-5 py-12 text-center text-sm text-slate-500">No files match these filters.</p>
      ) : data && (
        <div className={`overflow-x-auto transition-opacity ${loading ? "opacity-60" : ""}`}>
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="w-10 py-3 pl-4 pr-1 sm:w-12 sm:px-5">#</th>
                <th scope="col" className="px-3 py-3">File</th>
                <th scope="col" className="whitespace-nowrap px-3 py-3">Risk<span className="hidden sm:inline"> (6 months)</span></th>
                <th scope="col" className="hidden px-3 py-3 lg:table-cell">Main reasons</th>
                <th scope="col" className="hidden px-3 py-3 text-right md:table-cell">Complexity</th>
                <th scope="col" className="hidden px-3 py-3 text-right md:table-cell">Lines</th>
                <th scope="col" className="hidden px-3 py-3 text-right xl:table-cell">Commits</th>
                <th scope="col" className="hidden px-3 py-3 text-right xl:table-cell">Bug fixes</th>
                <th scope="col" className="px-5 py-3"><span className="sr-only">Details</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.items.map((f) => {
                const expanded = open === f.id;
                const reasons = (f.factors ?? []).filter((x) => x.impact > 0).slice(0, 2);
                return (
                  <Fragment key={f.id}>
                    <tr className={`align-middle ${expanded ? "bg-slate-50" : "hover:bg-slate-50/60"}`}>
                      <td className="py-3 pl-4 pr-1 tabular-nums text-slate-500 sm:px-5">{f.priority_rank}</td>
                      <td className="max-w-[9.5rem] truncate px-3 py-3 sm:max-w-[18rem]">
                        <PathCell path={f.file_path} to={`/repos/${repoId}/scans/${scanId}/files/${f.id}`} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-3"><ScoreCell f={f} /></td>
                      <td className="hidden px-3 py-3 lg:table-cell">
                        <div className="flex flex-wrap gap-1">
                          {reasons.map((x) => (
                            <span key={x.factor} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{x.label}</span>
                          ))}
                        </div>
                      </td>
                      <td className="hidden px-3 py-3 text-right tabular-nums md:table-cell">{fmt(f.complexity)}</td>
                      <td className="hidden px-3 py-3 text-right tabular-nums md:table-cell">{fmt(f.loc)}</td>
                      <td className="hidden px-3 py-3 text-right tabular-nums xl:table-cell">{fmt(f.commit_count)}</td>
                      <td className="hidden px-3 py-3 text-right tabular-nums xl:table-cell">{fmt(f.bug_fix_count)}</td>
                      <td className="py-3 pl-1 pr-3 text-right sm:px-5">
                        <button type="button" onClick={() => setOpen(expanded ? null : f.id)} aria-expanded={expanded}
                                aria-controls={`file-${f.id}`}
                                className="rounded-md px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50">
                          {expanded ? "Hide" : "Why?"}
                        </button>
                      </td>
                    </tr>
                    {expanded && (
                      <tr id={`file-${f.id}`} className="bg-slate-50">
                        <td colSpan={9} className="px-5 pb-5 pt-1">
                          <div className="grid gap-6 rounded-xl bg-white p-5 ring-1 ring-slate-200 md:grid-cols-2">
                            <div>
                              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">What to do</h3>
                              <p className="mt-2 text-sm leading-relaxed text-slate-700">{f.recommendation}</p>
                              <p className="mt-3 text-xs text-slate-500">
                                {fmt(f.loc)} lines · complexity {fmt(f.complexity)} · {fmt(f.commit_count)} commits ·{" "}
                                {fmt(f.bug_fix_count)} bug fixes · {fmt(f.num_developers)} developers
                              </p>
                              <Link to={`/repos/${repoId}/scans/${scanId}/files/${f.id}`}
                                    className="mt-3 inline-block text-sm font-medium text-indigo-600 hover:text-indigo-500">
                                Full details, history and commits →
                              </Link>
                            </div>
                            <div>
                              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                                Why this score <span className="font-normal normal-case text-slate-400">(SHAP: red raises, green lowers)</span>
                              </h3>
                              <div className="mt-3"><FactorBars factors={f.factors} /></div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > PAGE_SIZE && (
        <nav className="flex items-center justify-between border-t border-slate-100 px-5 py-3 text-sm" aria-label="Pages">
          <p className="text-slate-500">
            {(state.page - 1) * PAGE_SIZE + 1}–{Math.min(state.page * PAGE_SIZE, data.total)} of {data.total}
          </p>
          <div className="flex gap-2">
            <button type="button" disabled={state.page <= 1} onClick={() => onChange({ page: state.page - 1 })}
                    className="rounded-lg px-3 py-1.5 font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-40">
              Previous
            </button>
            <button type="button" disabled={state.page >= pages} onClick={() => onChange({ page: state.page + 1 })}
                    className="rounded-lg px-3 py-1.5 font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-40">
              Next
            </button>
          </div>
        </nav>
      )}
    </section>
  );
}

// Heatmap tab: loads every analysed file of the scan, shows the treemap, legend and a details
// panel for the file the user clicks. The zoomed folder is kept in the URL (?view=heatmap&folder=...).
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../../api/client";
import type { FileAnalysis, Page } from "../../api/types";
import { FactorBars } from "../report/FileTable";
import { RiskBadge } from "../risk";
import { Alert, Spinner } from "../ui";
import { Heatmap, type SizeBy } from "./Heatmap";
import { buildTree, LEGEND_GRADIENT } from "./tree";

const BATCH = 200; // API maximum per page
const MAX_FILES = 3000; // enough for large projects without freezing the browser

async function fetchAllFiles(scanId: number): Promise<{ files: FileAnalysis[]; truncated: boolean }> {
  const files: FileAnalysis[] = [];
  let total = Infinity;
  while (files.length < Math.min(total, MAX_FILES)) {
    const page = await api<Page<FileAnalysis>>(`/api/scans/${scanId}/files?limit=${BATCH}&offset=${files.length}`);
    total = page.total;
    files.push(...page.items);
    if (page.items.length === 0) break;
  }
  return { files, truncated: total > files.length };
}

function FileDetails({ file, href, onClose }: { file: FileAnalysis; href: string; onClose: () => void }) {
  const fmt = (n: number | null) => (n == null ? "–" : n.toLocaleString());
  return (
    <aside className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200" aria-label="Selected file">
      <div className="flex items-start justify-between gap-3">
        <p className="break-all font-mono text-sm font-semibold text-slate-900">{file.file_path}</p>
        <button type="button" onClick={onClose} aria-label="Close details"
                className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">✕</button>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <span className="text-3xl font-semibold tabular-nums">{Math.round(file.risk_score * 100)}%</span>
        <RiskBadge level={file.risk_level} />
      </div>
      <p className="text-xs text-slate-500">chance of needing a bug fix in the next 6 months · rank #{file.priority_rank}</p>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        {([["Lines", file.loc], ["Complexity", file.complexity], ["Commits", file.commit_count],
           ["Bug fixes", file.bug_fix_count], ["Developers", file.num_developers], ["Coupling", file.coupling]] as const).map(([k, v]) => (
          <div key={k} className="flex justify-between border-b border-slate-100 pb-1">
            <dt className="text-slate-500">{k}</dt><dd className="font-medium tabular-nums">{fmt(v)}</dd>
          </div>
        ))}
      </dl>
      <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">Why this score</h3>
      <div className="mt-2"><FactorBars factors={file.factors} /></div>
      <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">What to do</h3>
      <p className="mt-1 text-sm leading-relaxed text-slate-700">{file.recommendation}</p>
      <Link to={href} className="mt-4 inline-block text-sm font-medium text-indigo-600 hover:text-indigo-500">
        Full details, history and commits →
      </Link>
    </aside>
  );
}

export function HeatmapView({ repoId, scanId, repoName }: { repoId: number; scanId: number; repoName: string }) {
  const [params, setParams] = useSearchParams();
  const [files, setFiles] = useState<FileAnalysis[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sizeBy, setSizeBy] = useState<SizeBy>("loc");
  const [selected, setSelected] = useState<FileAnalysis | null>(null);
  const focusPath = params.get("folder") ?? "";

  useEffect(() => {
    setFiles(null);
    fetchAllFiles(scanId)
      .then(({ files, truncated }) => { setFiles(files); setTruncated(truncated); })
      .catch((e) => setError((e as Error).message));
  }, [scanId]);

  const tree = useMemo(() => (files ? buildTree(files, repoName) : null), [files, repoName]);
  const onFocus = useCallback((path: string) => {
    setParams((p) => {
      const out = new URLSearchParams(p);
      if (path) out.set("folder", path); else out.delete("folder");
      return out;
    }, { replace: true });
  }, [setParams]);

  if (error) return <Alert>{error}</Alert>;
  if (!tree) return <div className="grid place-items-center py-24 text-slate-400"><Spinner className="h-6 w-6" /></div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-white px-5 py-4 shadow-sm ring-1 ring-slate-200">
        <div className="flex items-center gap-3 text-xs text-slate-600">
          <span>Safe</span>
          <span className="h-2.5 w-40 rounded-full" style={{ background: LEGEND_GRADIENT }} aria-hidden="true" />
          <span>Critical (35%+)</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Box size:</span>
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5" role="group" aria-label="Box size">
            {(["loc", "commits"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={sizeBy === s} onClick={() => setSizeBy(s)}
                      className={`rounded-md px-2.5 py-1 font-medium ${sizeBy === s ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"}`}>
                {s === "loc" ? "Lines of code" : "Number of commits"}
              </button>
            ))}
          </div>
        </div>
      </div>
      {truncated && <Alert tone="info">Showing the first {MAX_FILES.toLocaleString()} files of this repository.</Alert>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200" aria-label="Codebase heatmap">
          <Heatmap tree={tree} focusPath={focusPath} onFocus={onFocus} sizeBy={sizeBy}
                   selected={selected?.id ?? null} onSelectFile={setSelected} />
          <p className="mt-3 text-xs text-slate-500">
            Each box is a file: its size is {sizeBy === "loc" ? "its lines of code" : "how often it was changed"},
            its colour the predicted risk. Big red boxes are where technical debt concentrates. Click a folder to zoom in.
          </p>
        </section>
        {selected ? (
          <FileDetails file={selected} href={`/repos/${repoId}/scans/${scanId}/files/${selected.id}`}
                       onClose={() => setSelected(null)} />
        ) : (
          <aside className="hidden rounded-2xl border-2 border-dashed border-slate-200 p-6 text-center text-sm text-slate-500 xl:block">
            Click a file to see why it is risky and what to do about it.
          </aside>
        )}
      </div>
    </div>
  );
}

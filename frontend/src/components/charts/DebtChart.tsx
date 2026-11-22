// "Projected Technical Debt Over Time": past scans (solid) + straight-line projection (dashed)
// with its 95% band, from GET /api/repositories/{id}/debt-forecast (Member 2's ml/forecast.py).
import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../../api/client";
import type { DebtForecast } from "../../api/types";
import { Spinner } from "../ui";

type Metric = "expected_bug_prone_files" | "risk_weighted_kloc";
const METRICS: { id: Metric; label: string; unit: string; help: string }[] = [
  { id: "expected_bug_prone_files", label: "Expected bug-prone files", unit: "files",
    help: "How many files the model expects to need a bug fix in the following 6 months (sum of risk scores)." },
  { id: "risk_weighted_kloc", label: "Risk-weighted code size", unit: "k lines",
    help: "Thousands of lines sitting in risky files (each file's lines × its risk): grows when big files get riskier." },
];

const ts = (iso: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
const monthYear = (t: number) => new Date(t).toLocaleDateString(undefined, { month: "short", year: "numeric" });

interface Row { t: number; actual?: number; projected?: number; band?: [number, number] }

export function DebtChart({ repoId }: { repoId: number }) {
  const [data, setData] = useState<DebtForecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>("expected_bug_prone_files");

  useEffect(() => {
    api<DebtForecast>(`/api/repositories/${repoId}/debt-forecast`).then(setData).catch((e) => setError((e as Error).message));
  }, [repoId]);

  const m = METRICS.find((x) => x.id === metric)!;
  let rows: Row[] = [];
  let now = 0;
  if (data) {
    rows = data.history.map((p) => ({ t: ts(p.date), actual: p[metric] }));
    const last = rows[rows.length - 1];
    now = last?.t ?? 0;
    if (last) { last.projected = last.actual; last.band = [last.actual!, last.actual!]; } // dashed line starts at "now"
    for (const p of data.projection) {
      rows.push({ t: ts(p.date), projected: p[metric],
                  band: [p[`${metric}_low`] ?? p[metric], p[`${metric}_high`] ?? p[metric]] });
    }
  }
  const trend = data?.trend[metric];
  const trendStyle = trend?.direction === "rising" ? "bg-red-50 text-red-700" : trend?.direction === "falling" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-700";
  const arrow = trend?.direction === "rising" ? "▲" : trend?.direction === "falling" ? "▼" : "▬";

  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200" aria-labelledby="debt-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="debt-title" className="text-sm font-semibold text-slate-900">Projected technical debt over time</h2>
          <p className="mt-0.5 max-w-xl text-xs text-slate-500">{m.help}</p>
        </div>
        <div className="flex items-center gap-2">
          {trend && (
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${trendStyle}`}>
              {arrow} {trend.direction} · {trend.per_year >= 0 ? "+" : ""}{trend.per_year.toFixed(2)} {m.unit}/year
            </span>
          )}
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5 text-xs" role="group" aria-label="Debt measure">
            {METRICS.map((x) => (
              <button key={x.id} type="button" aria-pressed={metric === x.id} onClick={() => setMetric(x.id)}
                      className={`rounded-md px-2.5 py-1 font-medium ${metric === x.id ? "bg-white text-slate-900 shadow-sm" : "text-slate-600"}`}>
                {x.id === "expected_bug_prone_files" ? "Bug-prone files" : "Risky code size"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error ? (
        <p className="mt-6 text-sm text-slate-500">No trend yet: {error}</p>
      ) : !data ? (
        <div className="grid h-64 place-items-center text-slate-400"><Spinner className="h-5 w-5" /></div>
      ) : (
        <div className="mt-4 h-64" role="img"
             aria-label={`${m.label}: ${rows.filter((r) => r.actual != null).map((r) => `${monthYear(r.t)} ${r.actual}`).join(", ")}. Projection: ${data.projection.map((p) => `${monthYear(ts(p.date))} ${p[metric]}`).join(", ")}.`}>
          <ResponsiveContainer>
            <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={monthYear}
                     tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={{ stroke: "#cbd5e1" }} minTickGap={40} />
              <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} allowDecimals />
              <Tooltip labelFormatter={(t) => monthYear(Number(t))}
                       formatter={(v: number | [number, number], name: string) =>
                         name === "band" ? [`${(v as number[])[0]}–${(v as number[])[1]}`, "95% range"] : [`${v} ${m.unit}`, name === "actual" ? "Measured" : "Projected"]} />
              <Area dataKey="band" stroke="none" fill="#6366f1" fillOpacity={0.12} isAnimationActive={false} />
              <ReferenceLine x={now} stroke="#94a3b8" strokeDasharray="4 4" label={{ value: "Today", fontSize: 11, fill: "#64748b", position: "insideTopLeft" }} />
              <Line dataKey="actual" stroke="#4f46e5" strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
              <Line dataKey="projected" stroke="#4f46e5" strokeWidth={2} strokeDasharray="6 5" dot={false} isAnimationActive={false} connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-400">
        Solid: measured at past scans. Dashed: straight-line projection with 95% range; a rough guide (in back-tests it
        beat "same as last time" by ~7%), not a precise forecast.
      </p>
    </section>
  );
}

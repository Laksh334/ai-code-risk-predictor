import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { RISK_LEVELS, type RiskCounts, type RiskLevel } from "../../api/types";
import { LEVEL_HEX, LEVEL_LABEL } from "../risk";

/** Donut of files per risk level. Clicking a slice (or legend row) filters the table. */
export function RiskDonut({ counts, onSelect, selected }: {
  counts: RiskCounts;
  onSelect: (level: RiskLevel | null) => void;
  selected: RiskLevel | null;
}) {
  const total = RISK_LEVELS.reduce((n, l) => n + counts[l], 0);
  const data = RISK_LEVELS.filter((l) => counts[l] > 0).map((l) => ({ level: l, name: LEVEL_LABEL[l], value: counts[l] }));

  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200" aria-labelledby="donut-title">
      <h2 id="donut-title" className="text-sm font-semibold text-slate-900">Files by risk level</h2>
      <div className="mt-2 flex flex-col items-center gap-6 sm:flex-row">
        <div className="relative h-44 w-44 shrink-0" role="img"
             aria-label={RISK_LEVELS.map((l) => `${counts[l]} ${LEVEL_LABEL[l]}`).join(", ")}>
          <ResponsiveContainer>
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="100%"
                   paddingAngle={data.length > 1 ? 2 : 0} stroke="none" isAnimationActive={false}
                   onClick={(d) => onSelect(selected === d.level ? null : (d.level as RiskLevel))}>
                {data.map((d) => (
                  <Cell key={d.level} fill={LEVEL_HEX[d.level]} cursor="pointer"
                        opacity={selected && selected !== d.level ? 0.3 : 1} />
                ))}
              </Pie>
              <Tooltip formatter={(v: number, n: string) => [`${v} files`, n]} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
            <div>
              <p className="text-2xl font-semibold tabular-nums">{total}</p>
              <p className="text-xs text-slate-500">files</p>
            </div>
          </div>
        </div>
        <ul className="w-full space-y-1">
          {RISK_LEVELS.map((l) => (
            <li key={l}>
              <button type="button" onClick={() => onSelect(selected === l ? null : l)} aria-pressed={selected === l}
                      className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition
                        ${selected === l ? "bg-slate-100" : "hover:bg-slate-50"}`}>
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: LEVEL_HEX[l] }} aria-hidden="true" />
                  {LEVEL_LABEL[l]}
                </span>
                <span className="tabular-nums text-slate-600">
                  {counts[l]} <span className="text-slate-400">({total ? Math.round((100 * counts[l]) / total) : 0}%)</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// One file's risk score across scans, with the risk-level thresholds drawn in.
import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { FileHistory } from "../../api/types";
import { LEVEL_HEX } from "../risk";

const ts = (iso: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
const monthYear = (t: number) => new Date(t).toLocaleDateString(undefined, { month: "short", year: "numeric" });

export function RiskHistoryChart({ points }: { points: FileHistory["risk_over_time"] }) {
  if (points.length < 2) {
    return <p className="text-sm text-slate-500">Only one scan so far: the trend appears after the next scan.</p>;
  }
  const data = points.map((p) => ({ t: ts(p.created_at), risk: Math.round(p.risk_score * 1000) / 10 }));
  const top = Math.max(40, Math.ceil(Math.max(...data.map((d) => d.risk)) / 10) * 10 + 5);
  return (
    <div className="h-56" role="img"
         aria-label={`Risk over time: ${data.map((d) => `${monthYear(d.t)} ${d.risk}%`).join(", ")}`}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
          {/* background bands = risk levels */}
          <ReferenceArea y1={0} y2={10} fill={LEVEL_HEX.low} fillOpacity={0.06} />
          <ReferenceArea y1={10} y2={20} fill={LEVEL_HEX.medium} fillOpacity={0.08} />
          <ReferenceArea y1={20} y2={35} fill={LEVEL_HEX.high} fillOpacity={0.08} />
          <ReferenceArea y1={35} y2={top} fill={LEVEL_HEX.critical} fillOpacity={0.08} />
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={monthYear}
                 tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={{ stroke: "#cbd5e1" }} minTickGap={40} />
          <YAxis domain={[0, top]} unit="%" tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
          <Tooltip labelFormatter={(t) => monthYear(Number(t))} formatter={(v: number) => [`${v}%`, "Risk"]} />
          <Line dataKey="risk" stroke="#0f172a" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

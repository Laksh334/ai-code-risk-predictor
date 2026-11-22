// SHAP explanation as a diverging bar chart: bars right (red) raise the risk, left (green) lower it.
import { useEffect, useState } from "react";
import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface Item { label: string; impact: number; value?: number | string | null }

function useNarrow(query = "(max-width: 639px)") {
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return narrow;
}

export function ShapChart({ items, title }: { items: Item[]; title: string }) {
  const narrow = useNarrow();
  const data = [...items].sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact)).slice(0, 10);
  const max = Math.max(0.1, ...data.map((d) => Math.abs(d.impact)));
  const fmtValue = (v: Item["value"]) =>
    v == null ? "" : typeof v === "number" ? ` = ${Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)}` : ` = ${v}`;
  const labelWidth = narrow ? 118 : 200;
  const maxChars = narrow ? 18 : 32;
  return (
    <figure>
      <figcaption className="sr-only">
        {title}: {data.map((d) => `${d.label}${fmtValue(d.value)} ${d.impact >= 0 ? "raises" : "lowers"} risk by ${Math.abs(d.impact).toFixed(2)}`).join("; ")}
      </figcaption>
      <div style={{ height: 34 * data.length + 30 }} aria-hidden="true">
        <ResponsiveContainer>
          {/* side margins leave room for the value labels on both ends */}
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 44, bottom: 4, left: 40 }}>
            <XAxis type="number" domain={[-max, max]} tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v: number) => v.toFixed(1)}
                   axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="label" width={labelWidth} tick={{ fontSize: narrow ? 11 : 12, fill: "#334155" }}
                   axisLine={false} tickLine={false}
                   tickFormatter={(l: string) => {
                     const d = data.find((x) => x.label === l);
                     const s = `${l}${fmtValue(d?.value)}`;
                     return s.length > maxChars ? `${s.slice(0, maxChars - 1)}…` : s;
                   }} />
            <ReferenceLine x={0} stroke="#94a3b8" />
            <Tooltip cursor={{ fill: "#f1f5f9" }}
                     formatter={(v: number) => [`${v >= 0 ? "+" : ""}${v.toFixed(3)} (log-odds)`, v >= 0 ? "Raises risk" : "Lowers risk"]} />
            <Bar dataKey="impact" radius={4} isAnimationActive={false}>
              {data.map((d) => <Cell key={d.label} fill={d.impact >= 0 ? "#f87171" : "#34d399"} />)}
              {/* value at the outer end of each bar: right of red bars, left of green bars */}
              <LabelList dataKey="impact" content={({ x, y, width, height, value }) => {
                const v = Number(value);
                const xs = Number(x) + Number(width);
                const pos = v >= 0 ? xs + 4 : Math.min(Number(x), xs) - 4;
                return (
                  <text x={pos} y={Number(y) + Number(height) / 2} dy={4} fontSize={11} fill="#475569"
                        textAnchor={v >= 0 ? "start" : "end"}>
                    {`${v >= 0 ? "+" : ""}${v.toFixed(2)}`}
                  </text>
                );
              }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

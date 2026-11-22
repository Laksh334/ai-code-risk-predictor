// Zoomable codebase heatmap: a treemap where each rectangle is a file.
//   size   = lines of code (or number of commits)
//   colour = predicted risk (green safe -> red critical)
// Click a folder to zoom in, use the breadcrumb to zoom out, click a file for details.
import { hierarchy, treemap, treemapSquarify, type HierarchyRectangularNode } from "d3-hierarchy";
import { useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import type { FileAnalysis } from "../../api/types";
import { LEVEL_LABEL } from "../risk";
import { filesUnder, riskColor, type TreeNode } from "./tree";

export type SizeBy = "loc" | "commits";
type Rect = HierarchyRectangularNode<TreeNode>;

const HEADER = 18; // folder label height inside a folder box

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  // Measure right away (before paint), then follow resizes. Relying on ResizeObserver alone
  // leaves the map blank until its first callback, which browsers delay for background tabs.
  useLayoutEffect(() => {
    if (!ref.current) return;
    setWidth(ref.current.clientWidth);
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function findNode(node: TreeNode, path: string): TreeNode | null {
  if (node.path === path) return node;
  for (const c of node.children ?? []) {
    if (path === c.path || path.startsWith(`${c.path}/`)) {
      const hit = findNode(c, path);
      if (hit) return hit;
    }
  }
  return null;
}

function trail(root: TreeNode, path: string): TreeNode[] {
  const out: TreeNode[] = [root];
  let node = root;
  while (node.path !== path) {
    const next = (node.children ?? []).find((c) => !c.file && (path === c.path || path.startsWith(`${c.path}/`)));
    if (!next) break;
    out.push(next);
    node = next;
  }
  return out;
}

interface Hover { node: TreeNode; x: number; y: number }

export function Heatmap({ tree, focusPath, onFocus, sizeBy, selected, onSelectFile }: {
  tree: TreeNode;
  focusPath: string;
  onFocus: (path: string) => void;
  sizeBy: SizeBy;
  selected: number | null;
  onSelectFile: (f: FileAnalysis) => void;
}) {
  const [boxRef, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Hover | null>(null);
  const height = width < 640 ? 380 : 540;
  const focus = findNode(tree, focusPath) ?? tree;

  const nodes = useMemo(() => {
    if (!width) return [] as Rect[];
    const root = hierarchy(focus)
      .sum((d) => (d.file ? Math.max(1, (sizeBy === "loc" ? d.file.loc : d.file.commit_count) ?? 1) : 0))
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
    return treemap<TreeNode>()
      .tile(treemapSquarify)
      .size([width, height])
      .paddingInner(2)
      .paddingOuter(3)
      .paddingTop((d) => (d.depth > 0 && d.children ? HEADER : 3))
      .round(true)(root)
      .descendants()
      .filter((d) => d.depth > 0);
  }, [focus, width, height, sizeBy]);

  const crumbs = trail(tree, focus.path);
  const move = (e: MouseEvent, node: TreeNode) => {
    const box = boxRef.current!.getBoundingClientRect();
    setHover({ node, x: e.clientX - box.left, y: e.clientY - box.top });
  };

  return (
    <div>
      <nav aria-label="Folder" className="mb-3 flex flex-wrap items-center gap-1 text-sm">
        {crumbs.map((c, i) => (
          <span key={c.path} className="flex items-center gap-1">
            {i > 0 && <span className="text-slate-400" aria-hidden="true">/</span>}
            {i < crumbs.length - 1 ? (
              <button type="button" onClick={() => onFocus(c.path)} className="rounded px-1.5 py-0.5 text-indigo-600 hover:bg-indigo-50">
                {c.name}
              </button>
            ) : (
              <span className="px-1.5 py-0.5 font-semibold text-slate-900" aria-current="location">{c.name}</span>
            )}
          </span>
        ))}
      </nav>

      <div ref={boxRef} className="relative w-full overflow-hidden rounded-xl bg-slate-100" style={{ height }}
           onMouseLeave={() => setHover(null)}>
        {nodes.map((d) => {
          const w = d.x1 - d.x0;
          const h = d.y1 - d.y0;
          const style = { left: d.x0, top: d.y0, width: w, height: h };
          const isFolder = !d.data.file;
          if (isFolder) {
            const files = filesUnder(d.data);
            const label = `${d.data.name}: ${files.length} files. Click to zoom in.`;
            return (
              <div key={`dir:${d.data.path}`} className="absolute rounded-md bg-white/40 ring-1 ring-slate-300 transition-all duration-300 motion-reduce:transition-none" style={style}>
                {h > HEADER && w > 30 && (
                  <button type="button" onClick={() => onFocus(d.data.path)} aria-label={label}
                          onMouseMove={(e) => move(e, d.data)}
                          className="block h-[18px] w-full truncate px-1.5 text-left text-[11px] font-semibold leading-[18px] text-slate-700 hover:bg-slate-900/10">
                    {d.data.name}/
                  </button>
                )}
              </div>
            );
          }
          const f = d.data.file!;
          const showText = w > 56 && h > 22;
          const isSelected = selected === f.id;
          return (
            <button key={`file:${d.data.path}`} type="button"
                    onClick={() => onSelectFile(f)}
                    onMouseMove={(e) => move(e, d.data)}
                    aria-label={`${f.file_path}: ${Math.round(f.risk_score * 100)}% risk, ${LEVEL_LABEL[f.risk_level]}`}
                    aria-pressed={isSelected}
                    className={`absolute overflow-hidden rounded-[3px] text-left text-white transition-all duration-300 motion-reduce:transition-none hover:brightness-110
                      focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 ${isSelected ? "ring-2 ring-slate-900 ring-offset-1" : ""}`}
                    style={{ ...style, background: riskColor(f.risk_score) }}>
              {showText && (
                <span className="block px-1.5 pt-1 leading-tight [text-shadow:0_1px_2px_rgb(0_0_0/0.35)]">
                  <span className="block truncate text-[11px] font-semibold">{d.data.name}</span>
                  {h > 36 && <span className="block text-[10px] opacity-90">{Math.round(f.risk_score * 100)}%</span>}
                </span>
              )}
            </button>
          );
        })}

        {hover && <Tooltip hover={hover} width={width} height={height} sizeBy={sizeBy} />}
      </div>
    </div>
  );
}

function Tooltip({ hover, width, height, sizeBy }: { hover: Hover; width: number; height: number; sizeBy: SizeBy }) {
  const { node } = hover;
  const left = Math.min(hover.x + 14, width - 250);
  const top = hover.y + 14 > height - 120 ? hover.y - 120 : hover.y + 14;
  let body;
  if (node.file) {
    const f = node.file;
    const reasons = (f.factors ?? []).filter((x) => x.impact > 0).slice(0, 2).map((x) => x.label).join(", ");
    body = (
      <>
        <p className="truncate font-mono text-xs font-semibold">{f.file_path}</p>
        <p className="mt-1"><b>{Math.round(f.risk_score * 100)}%</b> risk · {LEVEL_LABEL[f.risk_level]}</p>
        <p className="text-slate-300">{f.loc ?? "?"} lines · {f.commit_count ?? "?"} commits · {f.bug_fix_count ?? "?"} bug fixes</p>
        {reasons && <p className="mt-1 text-slate-300">Main reasons: {reasons}</p>}
      </>
    );
  } else {
    const files = filesUnder(node);
    const expected = files.reduce((s, f) => s + f.risk_score, 0);
    const worst = files.reduce((a, f) => (f.risk_score > a.risk_score ? f : a), files[0]);
    body = (
      <>
        <p className="font-mono text-xs font-semibold">{node.path || node.name}/</p>
        <p className="mt-1">{files.length} files · {files.reduce((s, f) => s + (sizeBy === "loc" ? f.loc ?? 0 : f.commit_count ?? 0), 0).toLocaleString()} {sizeBy === "loc" ? "lines" : "commits"}</p>
        <p className="text-slate-300">Expected bug-prone files: {expected.toFixed(1)}</p>
        {worst && <p className="text-slate-300">Riskiest: {worst.file_path.split("/").pop()} ({Math.round(worst.risk_score * 100)}%)</p>}
        <p className="mt-1 text-slate-400">Click to zoom in</p>
      </>
    );
  }
  return (
    <div className="pointer-events-none absolute z-10 w-60 rounded-lg bg-slate-900/95 px-3 py-2 text-xs text-white shadow-lg"
         style={{ left: Math.max(4, left), top: Math.max(4, top) }} role="tooltip">
      {body}
    </div>
  );
}

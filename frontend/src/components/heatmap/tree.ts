// Turn a flat list of analysed files into a folder tree, plus colour helpers for the heatmap.
import type { FileAnalysis } from "../../api/types";

export interface TreeNode {
  name: string; // shown label ("src/flask" when single-child folders are merged)
  path: string; // full path, "" for the root
  children?: TreeNode[];
  file?: FileAnalysis;
}

export function buildTree(files: FileAnalysis[], rootName: string): TreeNode {
  const root: TreeNode = { name: rootName, path: "", children: [] };
  for (const f of files) {
    const parts = f.file_path.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      if (i === parts.length - 1) {
        node.children!.push({ name: part, path, file: f });
        return;
      }
      let next = node.children!.find((c) => c.path === path && !c.file);
      if (!next) {
        next = { name: part, path, children: [] };
        node.children!.push(next);
      }
      node = next;
    });
  }
  return collapse(root);
}

/** "src" containing only "flask" becomes one box "src/flask": less nesting, more room. */
function collapse(node: TreeNode): TreeNode {
  if (!node.children) return node;
  let children: TreeNode[] = node.children.map(collapse);
  while (node.path !== "" && children.length === 1 && !children[0].file) {
    const only: TreeNode = children[0];
    node.name = `${node.name}/${only.name}`;
    node.path = only.path;
    children = only.children ?? [];
  }
  node.children = children;
  return node;
}

export function filesUnder(node: TreeNode): FileAnalysis[] {
  return node.file ? [node.file] : (node.children ?? []).flatMap(filesUnder);
}

// Colour = calibrated risk, with colour stops at the risk-level thresholds:
// green (0) -> yellow (0.10 medium) -> orange (0.20 high) -> red (>= 0.35 critical).
const STOPS: [number, [number, number, number]][] = [
  [0.0, [34, 197, 94]],
  [0.1, [234, 179, 8]],
  [0.2, [249, 115, 22]],
  [0.35, [220, 38, 38]],
];

export function riskColor(score: number): string {
  const s = Math.max(0, score);
  if (s >= STOPS[STOPS.length - 1][0]) return `rgb(${STOPS[STOPS.length - 1][1].join(",")})`;
  for (let i = 1; i < STOPS.length; i++) {
    const [x1, c1] = STOPS[i];
    const [x0, c0] = STOPS[i - 1];
    if (s <= x1) {
      const t = (s - x0) / (x1 - x0);
      return `rgb(${c0.map((v, k) => Math.round(v + t * (c1[k] - v))).join(",")})`;
    }
  }
  return `rgb(${STOPS[0][1].join(",")})`;
}

export const LEGEND_GRADIENT = `linear-gradient(to right, ${STOPS.map(([x, c]) => `rgb(${c.join(",")}) ${(x / 0.35) * 100}%`).join(", ")})`;

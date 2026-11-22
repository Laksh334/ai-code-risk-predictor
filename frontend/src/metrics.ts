// Readable names and formats for every per-file metric (same features as ml/explain.py FEATURE_INFO).
import type { FileAnalysis } from "./api/types";

type Fmt = "int" | "dec" | "pct" | "share" | "bool" | "days";
interface MetricDef { key: string; label: string; fmt: Fmt; help?: string }

export const METRIC_GROUPS: { title: string; items: MetricDef[] }[] = [
  {
    title: "Code size & complexity",
    items: [
      { key: "loc", label: "Lines of code", fmt: "int" },
      { key: "sloc", label: "Source lines", fmt: "int", help: "without blanks/comments" },
      { key: "num_functions", label: "Functions", fmt: "int" },
      { key: "num_classes", label: "Classes", fmt: "int" },
      { key: "complexity", label: "Most complex function", fmt: "int", help: "cyclomatic complexity" },
      { key: "avg_complexity", label: "Average function complexity", fmt: "dec" },
      { key: "max_nesting_depth", label: "Deepest nesting", fmt: "int" },
      { key: "max_function_length", label: "Longest function (lines)", fmt: "int" },
      { key: "max_params", label: "Most parameters", fmt: "int" },
      { key: "maintainability", label: "Maintainability index", fmt: "dec", help: "0–100, higher is better" },
      { key: "duplication", label: "Duplicated lines", fmt: "pct" },
      { key: "comment_ratio", label: "Comments per source line", fmt: "dec" },
    ],
  },
  {
    title: "Change history",
    items: [
      { key: "commit_count", label: "Commits", fmt: "int" },
      { key: "recent_commit_count", label: "Commits in last 90 days", fmt: "int" },
      { key: "churn", label: "Lines changed (all time)", fmt: "int" },
      { key: "recent_churn", label: "Lines changed (90 days)", fmt: "int" },
      { key: "bug_fix_count", label: "Bug-fix commits", fmt: "int" },
      { key: "bug_fix_ratio", label: "Share of commits that fixed bugs", fmt: "share" },
      { key: "age_days", label: "File age", fmt: "days" },
      { key: "days_since_last_change", label: "Since last change", fmt: "days" },
    ],
  },
  {
    title: "Team, coupling & tests",
    items: [
      { key: "num_developers", label: "Developers who changed it", fmt: "int" },
      { key: "top_author_share", label: "Main author's share", fmt: "share", help: "low = nobody really owns it" },
      { key: "fan_in", label: "Files that import it", fmt: "int" },
      { key: "fan_out", label: "Internal files it imports", fmt: "int" },
      { key: "has_test_file", label: "Has a matching test file", fmt: "bool" },
      { key: "test_importers", label: "Test files importing it", fmt: "int" },
    ],
  },
  {
    title: "Commit messages (NLP)",
    items: [
      { key: "msg_hf_frustration", label: "Frustration (AI emotion model)", fmt: "share" },
      { key: "msg_frustrated", label: "Frustrated messages", fmt: "share" },
      { key: "msg_rushed", label: "Rushed-work messages", fmt: "share" },
      { key: "msg_short", label: "Very short messages", fmt: "share" },
      { key: "msg_late_night", label: "Late-night commits", fmt: "share" },
      { key: "msg_weekend", label: "Weekend commits", fmt: "share" },
    ],
  },
];

export function metricValue(f: FileAnalysis, key: string): number | null {
  const col = (f as unknown as Record<string, unknown>)[key];
  if (typeof col === "number") return col;
  const v = f.metrics?.[key];
  return typeof v === "number" ? v : null;
}

export function formatMetric(v: number | null, fmt: Fmt): string {
  if (v == null) return "–";
  switch (fmt) {
    case "int": return Math.round(v).toLocaleString();
    case "dec": return v.toFixed(2).replace(/\.?0+$/, "");
    case "pct": return `${v.toFixed(1)}%`;
    case "share": return `${Math.round(v * 100)}%`;
    case "bool": return v ? "Yes" : "No";
    case "days": return v >= 365 ? `${(v / 365).toFixed(1)} years` : `${Math.round(v)} days`;
  }
}

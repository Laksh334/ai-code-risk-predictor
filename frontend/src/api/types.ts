// Shapes returned by the FastAPI backend (backend/app/schemas). Keep in sync.

export interface User {
  id: number;
  email: string;
  github_username: string | null;
  created_at: string;
}

export interface Token {
  access_token: string;
  token_type: "bearer";
}

export type RiskLevel = "low" | "medium" | "high" | "critical";
export const RISK_LEVELS: RiskLevel[] = ["critical", "high", "medium", "low"];
export type RiskCounts = Record<RiskLevel, number>;

export type ScanStatus = "pending" | "running" | "completed" | "failed";
export type ScanTrigger = "manual" | "pull_request" | "push" | "history";

export interface Scan {
  id: number;
  repository_id: number;
  trigger: ScanTrigger;
  status: ScanStatus;
  commit_sha: string | null;
  pr_number: number | null;
  overall_risk: number | null;
  model_version: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
  report_markdown: string | null;
}

export interface Repository {
  id: number;
  full_name: string;
  url: string;
  language: string | null;
  default_branch: string;
  created_at: string;
  latest_scan: Scan | null;
  report_scan_id: number | null; // latest COMPLETED scan
  risk_counts: RiskCounts | null;
}

export interface ScanDetail extends Scan {
  total_files: number;
  risk_counts: RiskCounts;
  averages: {
    complexity: number | null;
    maintainability: number | null;
    test_coverage: number | null;
    duplication: number | null;
  };
}

export interface ExplanationItem {
  feature: string;
  label: string | null;
  group: string | null;
  value: number | string | null;
  impact: number;
}

export interface Factor {
  factor: string;
  label: string;
  impact: number;
}

export interface FileAnalysis {
  id: number;
  scan_id: number;
  file_path: string;
  risk_score: number;
  risk_level: RiskLevel;
  priority_rank: number | null;
  commit_count: number | null;
  churn: number | null;
  num_developers: number | null;
  bug_fix_count: number | null;
  complexity: number | null;
  loc: number | null;
  coupling: number | null;
  duplication: number | null;
  test_coverage: number | null;
  maintainability: number | null;
  explanation: ExplanationItem[] | null;
  factors: Factor[] | null;
  recommendation: string | null;
  metrics: Record<string, number> | null;
}

export type FileSort = "priority" | "risk_score" | "complexity" | "churn" | "bug_fix_count" | "num_developers" | "loc";

export interface CommitInfo {
  commit_sha: string;
  commit_date: string;
  author: string | null;
  change_type: string | null;
  lines_added: number;
  lines_deleted: number;
  commit_message: string | null;
  is_bug_fix: boolean;
}

export interface FileHistory {
  file_path: string;
  risk_over_time: { scan_id: number; created_at: string; risk_score: number; risk_level: RiskLevel }[];
  recent_commits: CommitInfo[];
}

export interface DebtPoint {
  date: string;
  files?: number | null;
  expected_bug_prone_files: number;
  risk_weighted_kloc: number;
  critical?: number | null;
  high?: number | null;
  medium?: number | null;
  low?: number | null;
  expected_bug_prone_files_low?: number | null;
  expected_bug_prone_files_high?: number | null;
  risk_weighted_kloc_low?: number | null;
  risk_weighted_kloc_high?: number | null;
}

export interface DebtForecast {
  history: DebtPoint[];
  projection: DebtPoint[];
  trend: Record<"expected_bug_prone_files" | "risk_weighted_kloc", { per_year: number; direction: "rising" | "falling" | "flat" }>;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export const isActive = (s: Scan | null | undefined) => s?.status === "pending" || s?.status === "running";

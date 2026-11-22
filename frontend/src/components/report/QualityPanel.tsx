import type { ScanDetail } from "../../api/types";

type Grade = { label: string; tone: string };

// Thresholds from the tools' own guidance:
//  McCabe complexity: 1-10 simple, 11-20 moderate, > 20 complex
//  Radon maintainability index (0-100): >= 20 easy (A), 10-19 moderate (B), < 10 hard (C)
const complexityGrade = (v: number): Grade =>
  v <= 10 ? { label: "Simple", tone: "text-risk-low" } : v <= 20 ? { label: "Moderate", tone: "text-risk-medium" } : { label: "Complex", tone: "text-risk-critical" };
const maintainabilityGrade = (v: number): Grade =>
  v >= 20 ? { label: "Easy to maintain (A)", tone: "text-risk-low" } : v >= 10 ? { label: "Moderate (B)", tone: "text-risk-medium" } : { label: "Hard to maintain (C)", tone: "text-risk-critical" };
const duplicationGrade = (v: number): Grade =>
  v < 5 ? { label: "Low", tone: "text-risk-low" } : v < 15 ? { label: "Moderate", tone: "text-risk-medium" } : { label: "High", tone: "text-risk-critical" };

function Row({ name, value, unit, grade, help }: { name: string; value: number | null; unit?: string; grade?: (v: number) => Grade; help: string }) {
  const g = value != null && grade ? grade(value) : null;
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div>
        <dt className="text-sm font-medium text-slate-800">{name}</dt>
        <dd className="text-xs text-slate-500">{help}</dd>
      </div>
      <div className="text-right">
        <p className="text-lg font-semibold tabular-nums text-slate-900">
          {value == null ? "–" : `${value}${unit ?? ""}`}
        </p>
        {g && <p className={`text-xs font-medium ${g.tone}`}>{g.label}</p>}
      </div>
    </div>
  );
}

export function QualityPanel({ scan }: { scan: ScanDetail }) {
  const a = scan.averages;
  return (
    <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200" aria-labelledby="quality-title">
      <h2 id="quality-title" className="text-sm font-semibold text-slate-900">Code quality (average per file)</h2>
      <dl className="mt-1 divide-y divide-slate-100">
        <Row name="Most complex function" value={a.complexity} grade={complexityGrade}
             help="Cyclomatic complexity of each file's most complex function" />
        <Row name="Maintainability index" value={a.maintainability} grade={maintainabilityGrade}
             help="Radon MI, 0–100: higher is easier to change" />
        <Row name="Duplicated lines" value={a.duplication} unit="%" grade={duplicationGrade}
             help="Share of lines in copy-pasted blocks of 6+ lines" />
        <Row name="Test coverage" value={a.test_coverage} unit="%"
             help="Not measured yet: the model uses 'has a test file' instead" />
      </dl>
    </section>
  );
}

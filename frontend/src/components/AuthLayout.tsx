// Two-column frame for the login / sign-up pages: product pitch left, form right.
import type { ReactNode } from "react";

import { Logo } from "./ui";

const POINTS = [
  { color: "bg-risk-critical", text: "Ranks every file by its chance of needing a bug fix in the next 6 months" },
  { color: "bg-risk-high", text: "Explains why: complexity, churn, coupling, bug history, rushed commits" },
  { color: "bg-risk-low", text: "Comments the risk of each pull request automatically on GitHub" },
];

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <aside className="relative hidden w-[44%] flex-col justify-between overflow-hidden bg-slate-900 p-12 lg:flex">
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-indigo-600/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-orange-500/20 blur-3xl" />
        <Logo dark />
        <div className="relative">
          <h2 className="text-3xl font-semibold leading-tight text-white">
            Know which files will break <span className="text-indigo-300">before they do.</span>
          </h2>
          <ul className="mt-8 space-y-4">
            {POINTS.map((p) => (
              <li key={p.text} className="flex gap-3 text-slate-300">
                <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${p.color}`} aria-hidden="true" />
                <span className="text-sm leading-relaxed">{p.text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">Git history + static analysis + machine learning + SHAP</p>
      </aside>

      <main className="flex flex-1 items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
          <p className="mt-2 text-sm text-slate-600">{subtitle}</p>
          <div className="mt-8">{children}</div>
        </div>
      </main>
    </div>
  );
}

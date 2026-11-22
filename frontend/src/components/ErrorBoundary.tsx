// Catches crashes while rendering a page and shows a friendly screen instead of a blank page.
// Also handles the classic "new version deployed" problem: an open tab asks for a code chunk
// (e.g. the report page) that no longer exists on the server -> offer a reload.
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "./ui";

interface State { error: Error | null }

const isStaleChunk = (e: Error) =>
  /Failed to fetch dynamically imported module|Importing a module script failed|ChunkLoadError|error loading dynamically imported module/i
    .test(`${e.name} ${e.message}`);

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // A monitoring service (e.g. Sentry) would be called here.
    console.error("Page crashed:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const stale = isStaleChunk(error);
    return (
      <div role="alert" className="mx-auto max-w-lg py-20 text-center">
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-amber-50 text-2xl" aria-hidden="true">
          {stale ? "↻" : "!"}
        </div>
        <h1 className="mt-4 text-xl font-semibold text-slate-900">
          {stale ? "A new version is available" : "Something went wrong on this page"}
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          {stale
            ? "The app was updated since you opened it. Reload to get the latest version."
            : "This is a bug on our side, not something you did. Reloading usually helps; your data is safe."}
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Button onClick={() => window.location.reload()}>Reload page</Button>
          {!stale && <Button variant="secondary" onClick={() => { window.location.href = "/"; }}>Go to dashboard</Button>}
        </div>
        {import.meta.env.DEV && (
          <pre className="mt-8 overflow-auto rounded-lg bg-slate-900 p-4 text-left text-xs text-slate-200">{error.message}</pre>
        )}
      </div>
    );
  }
}

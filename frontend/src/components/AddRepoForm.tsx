import { useState, type FormEvent } from "react";

import { ApiError } from "../api/client";
import { useRepos } from "../store/repos";
import { Button } from "./ui";

// Same formats the backend accepts (backend/app/services/github_url.py).
const GITHUB_URL = /^(https?:\/\/)?(www\.)?github\.com\/[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]+?(\.git)?(\/.*)?$/;

export function AddRepoForm({ onAdded }: { onAdded?: () => void }) {
  const addRepo = useRepos((s) => s.addRepo);
  const [url, setUrl] = useState("");
  const [scanNow, setScanNow] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const value = url.trim();
    if (!GITHUB_URL.test(value)) {
      setError("Paste a GitHub repository link, e.g. https://github.com/pallets/flask");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await addRepo(value, scanNow);
      setUrl("");
      onAdded?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the repository.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <label htmlFor="repo-url" className="block text-sm font-semibold text-slate-900">Add a repository</label>
      <p className="mt-0.5 text-xs text-slate-500">Public GitHub repositories with Python code.</p>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row">
        <input
          id="repo-url"
          value={url}
          onChange={(e) => { setUrl(e.target.value); setError(null); }}
          placeholder="https://github.com/owner/repository"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          aria-invalid={!!error}
          aria-describedby={error ? "repo-url-error" : undefined}
          className={`block w-full flex-1 rounded-lg border-0 px-3 py-2.5 text-sm shadow-sm ring-1 ring-inset
            placeholder:text-slate-400 focus:ring-2 focus:ring-inset
            ${error ? "ring-red-400 focus:ring-red-500" : "ring-slate-300 focus:ring-indigo-600"}`}
        />
        <Button type="submit" loading={loading}>{scanNow ? "Add & scan" : "Add"}</Button>
      </div>
      <div className="mt-3 flex items-center justify-between gap-4">
        <label className="inline-flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={scanNow} onChange={(e) => setScanNow(e.target.checked)}
                 className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600" />
          Start the first scan right away
        </label>
      </div>
      {error && <p id="repo-url-error" role="alert" className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}

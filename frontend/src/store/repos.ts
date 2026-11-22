// Repositories state (Zustand): the list on the dashboard and the actions on it.
import { create } from "zustand";

import { api } from "../api/client";
import { isActive, type Repository, type Scan } from "../api/types";

interface ReposState {
  repos: Repository[];
  loaded: boolean;
  error: string | null;
  fetchRepos: () => Promise<void>;
  addRepo: (url: string, scanNow: boolean) => Promise<Repository>;
  startScan: (repoId: number) => Promise<Scan>;
  deleteRepo: (repoId: number) => Promise<void>;
  anyScanActive: () => boolean;
}

export const useRepos = create<ReposState>()((set, get) => ({
  repos: [],
  loaded: false,
  error: null,

  async fetchRepos() {
    try {
      set({ repos: await api<Repository[]>("/api/repositories"), loaded: true, error: null });
    } catch (e) {
      set({ loaded: true, error: (e as Error).message });
    }
  },

  async addRepo(url, scanNow) {
    const repo = await api<Repository>("/api/repositories", { method: "POST", json: { url } });
    set((s) => ({ repos: [repo, ...s.repos] }));
    if (scanNow) await get().startScan(repo.id);
    return repo;
  },

  async startScan(repoId) {
    const scan = await api<Scan>(`/api/repositories/${repoId}/scans`, { method: "POST" });
    // Show "queued" at once; polling picks up running/completed.
    set((s) => ({ repos: s.repos.map((r) => (r.id === repoId ? { ...r, latest_scan: scan } : r)) }));
    return scan;
  },

  async deleteRepo(repoId) {
    await api<void>(`/api/repositories/${repoId}`, { method: "DELETE" });
    set((s) => ({ repos: s.repos.filter((r) => r.id !== repoId) }));
  },

  anyScanActive: () => get().repos.some((r) => isActive(r.latest_scan)),
}));

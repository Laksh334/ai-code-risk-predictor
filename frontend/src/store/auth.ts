// Login state (Zustand). The token is kept in localStorage so a page refresh stays logged in.
import { create } from "zustand";
import { persist } from "zustand/middleware";

import { api, configureAuth } from "../api/client";
import type { Token, User } from "../api/types";
import { useRepos } from "./repos";

interface AuthState {
  token: string | null;
  user: User | null;
  /** Set when the server rejected the saved token (expired): the login page explains why. */
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, githubUsername?: string) => Promise<void>;
  loadUser: () => Promise<void>;
  logout: (expired?: boolean) => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      sessionExpired: false,

      async login(email, password) {
        const { access_token } = await api<Token>("/api/auth/login", {
          method: "POST",
          form: { username: email, password },
          auth: false,
        });
        set({ token: access_token, sessionExpired: false });
        await get().loadUser();
      },

      async register(email, password, githubUsername) {
        await api<User>("/api/auth/register", {
          method: "POST",
          json: { email, password, github_username: githubUsername || null },
          auth: false,
        });
        await get().login(email, password);
      },

      async loadUser() {
        set({ user: await api<User>("/api/auth/me") });
      },

      logout(expired = false) {
        set({ token: null, user: null, sessionExpired: expired });
        // Don't flash the previous user's repositories to the next one on this browser.
        useRepos.setState({ repos: [], loaded: false, error: null });
      },
    }),
    { name: "code-risk-auth", partialize: (s) => ({ token: s.token, user: s.user }) },
  ),
);

configureAuth(
  () => useAuth.getState().token,
  () => useAuth.getState().logout(true),
);

// Frame for logged-in pages: top bar with the user and a sign-out button.
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useOnline } from "../hooks";
import { useAuth } from "../store/auth";
import { ErrorBoundary } from "./ErrorBoundary";
import { Button, Logo } from "./ui";

export function AppLayout() {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const online = useOnline();

  return (
    <div className="min-h-screen">
      {/* Keyboard users can jump past the header straight to the page content. */}
      <a href="#main" className="sr-only z-50 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white focus:not-sr-only focus:fixed focus:left-4 focus:top-3">
        Skip to content
      </a>
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link to="/" aria-label="Code Risk Predictor home" className="min-w-0">
            <Logo />
          </Link>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <span className="hidden max-w-[16rem] truncate text-sm text-slate-600 md:inline" title={`Signed in as ${user?.email}`}>
              {user?.email}
            </span>
            <span className="grid h-8 w-8 place-items-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700"
                  aria-hidden="true">
              {user?.email?.[0]?.toUpperCase() ?? "?"}
            </span>
            <Button variant="ghost" className="!px-3" onClick={() => { logout(); navigate("/login"); }}>
              Sign out
            </Button>
          </div>
        </div>
        {!online && (
          <div role="status" className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-900">
            You're offline. The dashboard will update again when the connection is back.
          </div>
        )}
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-6 focus:outline-none sm:px-6 sm:py-8">
        {/* Keyed by page: a crash on one page shows the error screen there, and navigating
            to another page recovers without a full reload. */}
        <ErrorBoundary key={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}

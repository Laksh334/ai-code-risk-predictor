import { lazy, Suspense, useEffect } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { GuestOnly, RequireAuth } from "./components/RequireAuth";
import { Spinner } from "./components/ui";
import { usePageTitle } from "./hooks";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";

// The report and file pages pull in the charting library (~400 kB), so they are loaded only when
// opened: login and the dashboard stay small and fast.
const RepoPage = lazy(() => import("./pages/RepoPage").then((m) => ({ default: m.RepoPage })));
const FilePage = lazy(() => import("./pages/FilePage").then((m) => ({ default: m.FilePage })));
const lazyPage = (page: JSX.Element) => (
  <Suspense fallback={<div className="grid place-items-center py-24 text-slate-400"><Spinner className="h-6 w-6" /></div>}>
    {page}
  </Suspense>
);

function NotFound() {
  usePageTitle("Page not found");
  return (
    <div className="grid min-h-screen place-items-center px-6 text-center">
      <div>
        <p className="text-sm font-semibold text-indigo-600">404</p>
        <h1 className="mt-2 text-2xl font-semibold">Page not found</h1>
        <Link to="/" className="mt-4 inline-block text-sm font-medium text-indigo-600 hover:text-indigo-500">
          Back to the dashboard
        </Link>
      </div>
    </div>
  );
}

/** New page -> start at the top (but not when only filters in the URL change). */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

/** Development only: /__crash shows the error screen (for testing the error boundary). */
function Crash(): JSX.Element {
  throw new Error("Test crash from /__crash");
}

export default function App() {
  return (
    <ErrorBoundary>
      <ScrollToTop />
      <Routes>
        <Route element={<GuestOnly />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/repos/:repoId" element={lazyPage(<RepoPage />)} />
            {/* PR comments link to /repos/:id/scans/:scanId -> the repo's report */}
            <Route path="/repos/:repoId/scans/:scanId" element={lazyPage(<RepoPage />)} />
            <Route path="/repos/:repoId/scans/:scanId/files/:fileId" element={lazyPage(<FilePage />)} />
            {import.meta.env.DEV && <Route path="/__crash" element={<Crash />} />}
          </Route>
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </ErrorBoundary>
  );
}

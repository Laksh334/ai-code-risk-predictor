// Guards logged-in pages: no token -> login page (then back to where the user wanted to go).
import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../store/auth";
import { Spinner } from "./ui";

export function RequireAuth() {
  const token = useAuth((s) => s.token);
  const user = useAuth((s) => s.user);
  const loadUser = useAuth((s) => s.loadUser);
  const location = useLocation();
  const [checking, setChecking] = useState(!!token && !user);

  // A saved token may have expired: check it once (an invalid token logs out automatically).
  useEffect(() => {
    if (token && !user) loadUser().catch(() => {}).finally(() => setChecking(false));
  }, [token, user, loadUser]);

  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (checking) {
    return (
      <div className="grid min-h-screen place-items-center text-slate-500">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  return <Outlet />;
}

/** Login/register pages: already logged in -> go to the dashboard. */
export function GuestOnly() {
  const token = useAuth((s) => s.token);
  return token ? <Navigate to="/" replace /> : <Outlet />;
}

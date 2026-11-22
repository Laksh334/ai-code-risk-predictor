import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { AuthLayout } from "../components/AuthLayout";
import { Alert, Button, Input } from "../components/ui";
import { emailError } from "../components/validation";
import { usePageTitle } from "../hooks";
import { useAuth } from "../store/auth";

export function LoginPage() {
  const login = useAuth((s) => s.login);
  const sessionExpired = useAuth((s) => s.sessionExpired);
  usePageTitle("Sign in");
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const emailProblem = touched ? emailError(email) : undefined;
  const passwordProblem = touched && !password ? "Enter your password" : undefined;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (emailError(email) || !password) return;
    setLoading(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle={<>New here? <Link to="/register" className="font-medium text-indigo-600 hover:text-indigo-500">Create an account</Link></>}
    >
      <form onSubmit={onSubmit} noValidate className="space-y-5">
        {error ? <Alert>{error}</Alert> : sessionExpired && (
          <Alert tone="info">Your session has expired. Please sign in again.</Alert>
        )}
        <Input label="Email" name="email" type="email" autoComplete="email" autoFocus
               value={email} onChange={(e) => setEmail(e.target.value)} error={emailProblem} />
        <Input label="Password" name="password" type="password" autoComplete="current-password"
               value={password} onChange={(e) => setPassword(e.target.value)} error={passwordProblem} />
        <Button type="submit" loading={loading} className="w-full">
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}

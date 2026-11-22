import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { AuthLayout } from "../components/AuthLayout";
import { Alert, Button, Input } from "../components/ui";
import { emailError, passwordError } from "../components/validation";
import { usePageTitle } from "../hooks";
import { useAuth } from "../store/auth";

export function RegisterPage() {
  const register = useAuth((s) => s.register);
  usePageTitle("Create account");
  const navigate = useNavigate();

  const [form, setForm] = useState({ email: "", password: "", confirm: "", github: "" });
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const problems = {
    email: emailError(form.email),
    password: passwordError(form.password),
    confirm: form.confirm !== form.password ? "Passwords don't match" : undefined,
  };
  const show = (k: keyof typeof problems) => (touched ? problems[k] : undefined);
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (Object.values(problems).some(Boolean)) return;
    setLoading(true);
    setError(null);
    try {
      await register(form.email.trim(), form.password, form.github.trim());
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("An account with this email already exists. Try signing in instead.");
      } else {
        setError(err instanceof ApiError ? err.message : "Sign-up failed. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle={<>Already have one? <Link to="/login" className="font-medium text-indigo-600 hover:text-indigo-500">Sign in</Link></>}
    >
      <form onSubmit={onSubmit} noValidate className="space-y-5">
        {error && <Alert>{error}</Alert>}
        <Input label="Email" name="email" type="email" autoComplete="email" autoFocus
               value={form.email} onChange={set("email")} error={show("email")} />
        <Input label="Password" name="password" type="password" autoComplete="new-password"
               value={form.password} onChange={set("password")} error={show("password")}
               hint="At least 8 characters" />
        <Input label="Confirm password" name="confirm" type="password" autoComplete="new-password"
               value={form.confirm} onChange={set("confirm")} error={show("confirm")} />
        <Input label="GitHub username (optional)" name="github" autoComplete="username"
               value={form.github} onChange={set("github")} placeholder="octocat" />
        <Button type="submit" loading={loading} className="w-full">
          {loading ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}

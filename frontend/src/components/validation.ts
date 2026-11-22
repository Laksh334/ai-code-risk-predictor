// Same rules as the backend (backend/app/schemas/user.py), checked before sending.

export function emailError(email: string): string | undefined {
  if (!email.trim()) return "Enter your email address";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return "That doesn't look like an email address";
}

export function passwordError(password: string): string | undefined {
  if (password.length < 8) return "Use at least 8 characters";
  // bcrypt only reads the first 72 bytes; the backend rejects longer passwords.
  if (new TextEncoder().encode(password).length > 72) return "Use at most 72 bytes (about 72 characters)";
}

import { useState } from "react";
import { api } from "../api";
import { Alert, Field } from "../components/ui";
import type { User } from "../types";

export default function AuthPage({ onAuthed }: { onAuthed: (token: string, user: User) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res =
        mode === "login"
          ? await api.post<{ token: string; user: User }>("/auth/login", { email, password })
          : await api.post<{ token: string; user: User }>("/auth/signup", {
              email,
              password,
              workspace_name: workspace,
            });
      onAuthed(res.token, res.user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="logo">
        <span className="logo-mark">A</span> Adpress
      </div>
      <form className="card" onSubmit={submit}>
        <h1>{mode === "login" ? "Sign in" : "Create your workspace"}</h1>
        <p className="muted lede">
          {mode === "login" ? "On-brand ads for every platform." : "Set up a brand in about 10 minutes."}
        </p>
        <Alert>{error}</Alert>
        {mode === "signup" && (
          <Field label="Workspace name" hint="Your business or agency name">
            <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} required />
          </Field>
        )}
        <Field label="Email">
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </Field>
        <Field label="Password" hint={mode === "signup" ? "At least 8 characters" : undefined}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "signup" ? 8 : undefined}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </Field>
        <button className="btn block mt-2" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create workspace"}
        </button>
        <p className="small muted switch">
          {mode === "login" ? "New to Adpress? " : "Already have an account? "}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setMode(mode === "login" ? "signup" : "login");
              setError("");
            }}
          >
            {mode === "login" ? "Create a workspace" : "Sign in"}
          </a>
        </p>
      </form>
    </div>
  );
}

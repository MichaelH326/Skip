import { useEffect, useState } from "react";
import { api } from "../api";
import { Alert, Field } from "../components/ui";
import type { Role, User } from "../types";

export default function TeamPage({ user }: { user: User }) {
  const [users, setUsers] = useState<User[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("Editor");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = () => api.get<User[]>("/workspace/users").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setOk("");
    try {
      await api.post("/workspace/users", { email, password, role });
      setOk(`Added ${email}. Share their temporary password with them directly.`);
      setEmail("");
      setPassword("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div>
      <h1>Team</h1>
      <p className="muted">{user.workspace_name}</p>
      <div className="card">
        <table className="simple">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>{u.role}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted" style={{ marginTop: 10 }}>
          Owners can override blocking flags and delete brands. Editors create and edit. Viewers can only look.
        </p>
      </div>
      {user.role === "Owner" && (
        <form className="card" onSubmit={add}>
          <h2>Add a teammate</h2>
          <Alert>{error}</Alert>
          <Alert kind="ok">{ok}</Alert>
          <div className="grid2">
            <Field label="Email">
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </Field>
            <Field label="Temporary password" hint="At least 8 characters">
              <input value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
            </Field>
          </div>
          <Field label="Role">
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              <option>Editor</option>
              <option>Viewer</option>
              <option>Owner</option>
            </select>
          </Field>
          <button className="btn">Add teammate</button>
        </form>
      )}
    </div>
  );
}

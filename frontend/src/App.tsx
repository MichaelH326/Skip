import { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { navigate, useHashRoute } from "./router";
import type { User } from "./types";
import AuthPage from "./pages/AuthPage";
import BrandsPage from "./pages/BrandsPage";
import BrandPage from "./pages/BrandPage";
import TeamPage from "./pages/TeamPage";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!getToken());
  const route = useHashRoute();

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
    navigate("/login");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    if (!getToken()) return;
    api
      .get<User>("/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, [signOut]);

  if (loading) return <div className="center muted">Loading…</div>;

  if (!user) {
    return (
      <AuthPage
        onAuthed={(token, u) => {
          setToken(token);
          setUser(u);
          navigate("/brands");
        }}
      />
    );
  }

  const [section, id, tab] = route;
  let page;
  if (section === "brands" && id) page = <BrandPage brandId={id} tab={tab || "setup"} user={user} />;
  else if (section === "team") page = <TeamPage user={user} />;
  else page = <BrandsPage user={user} />;

  return (
    <div className="shell">
      <header className="topbar">
        <a className="logo" href="#/brands">
          <span className="logo-mark">A</span> Adpress
        </a>
        <nav className="topnav">
          <a href="#/brands" className={section !== "team" ? "active" : ""}>
            Brands
          </a>
          <a href="#/team" className={section === "team" ? "active" : ""}>
            Team
          </a>
        </nav>
        <div className="topbar-user">
          <span className="muted small">
            {user.email} · {user.role}
          </span>
          <button
            className="btn ghost small"
            onClick={async () => {
              try {
                await api.post("/auth/logout");
              } finally {
                signOut();
              }
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="main">{page}</main>
    </div>
  );
}

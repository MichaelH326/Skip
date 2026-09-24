import { useCallback, useEffect, useState } from "react";
import { api, waitForJob } from "../api";
import { navigate } from "../router";
import { Alert, Field, JobProgress } from "../components/ui";
import { PLATFORMS, PLATFORM_LABELS, type Brand, type Job, type Platform, type Source, type User } from "../types";
import { hashQuery } from "./BrandPage";

export default function SetupTab({ brand, user, onChange }: { brand: Brand; user: User; onChange: () => void }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [url, setUrl] = useState(brand.website_url || "");
  const [platform, setPlatform] = useState<Platform>("facebook");
  const [kind, setKind] = useState<"bio" | "post">("post");
  const [text, setText] = useState("");
  const [owned, setOwned] = useState(true);
  const canEdit = user.role !== "Viewer";

  const load = useCallback(
    () => api.get<Source[]>(`/brands/${brand.id}/sources`).then(setSources).catch((e) => setError(e.message)),
    [brand.id],
  );

  const follow = useCallback(
    async (id: string) => {
      const done = await waitForJob(id, setJob);
      if (done.status === "failed") setError(done.error || "That didn't work.");
      else if (done.kind === "import") {
        const r = done.result as { pages: number; warnings: string[] };
        setNotice(`Imported ${r.pages} page${r.pages === 1 ? "" : "s"}.`);
      }
      await load();
      onChange();
      return done;
    },
    [load, onChange],
  );

  useEffect(() => {
    load();
    const pending = hashQuery().get("job");
    if (pending) follow(pending).catch((e) => setError(e.message));
  }, [load, follow]);

  const running = job && (job.status === "queued" || job.status === "running");

  const importSite = async () => {
    setError("");
    setNotice("");
    try {
      if (url !== brand.website_url) await api.patch(`/brands/${brand.id}`, { website_url: url });
      const j = await api.post<Job>(`/brands/${brand.id}/import`);
      setJob(j);
      await follow(j.id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const addSource = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      await api.post(`/brands/${brand.id}/sources`, { platform, kind, text, owned });
      setText("");
      load();
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const buildKit = async () => {
    setError("");
    try {
      const j = await api.post<Job>(`/brands/${brand.id}/kit/build`);
      setJob(j);
      const done = await follow(j.id);
      if (done.status === "done") navigate(`/brands/${brand.id}/kit`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const website = sources.filter((s) => s.type === "website");
  const pasted = sources.filter((s) => s.type === "paste");
  const siteMeta = website.find((s) => s.meta.colors)?.meta;

  return (
    <div className="stack">
      <Alert>{error}</Alert>
      <Alert kind="ok">{notice}</Alert>
      <JobProgress job={job} />

      <div className="card">
        <div className="card-title">
          <h2>Website</h2>
          <span className="muted small">{website.length} pages imported</span>
        </div>
        <div className="row">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="example.com" style={{ flex: 1 }}
            disabled={!canEdit} />
          {canEdit && (
            <button className="btn secondary" onClick={importSite} disabled={!!running || !url.trim()}>
              {website.length ? "Re-import" : "Import"}
            </button>
          )}
        </div>
        {siteMeta && (
          <div className="row small" style={{ marginTop: 10 }}>
            <span className="muted">Colors found:</span>
            {(siteMeta.colors || []).map((c) => (
              <span key={c} className="swatch" style={{ background: c }} title={c} />
            ))}
            {!!siteMeta.fonts?.length && <span className="muted">Fonts: {siteMeta.fonts.join(", ")}</span>}
          </div>
        )}
        {website.length > 0 && (
          <details style={{ marginTop: 10 }}>
            <summary className="small">Show imported pages</summary>
            {website.map((s) => (
              <div className="source" key={s.id}>
                <a href={s.url || "#"} target="_blank" rel="noreferrer" className="small">
                  {s.meta.title || s.url}
                </a>
                <pre>{s.text.slice(0, 600)}</pre>
              </div>
            ))}
          </details>
        )}
      </div>

      <div className="card">
        <div className="card-title">
          <h2>Social content</h2>
          <span className="muted small">Paste your bio and up to 10 recent posts per platform</span>
        </div>
        {canEdit && (
          <form onSubmit={addSource}>
            <div className="grid2">
              <Field label="Platform">
                <select value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
                  {PLATFORMS.map((p) => (
                    <option key={p} value={p}>
                      {PLATFORM_LABELS[p]}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Type">
                <select value={kind} onChange={(e) => setKind(e.target.value as "bio" | "post")}>
                  <option value="post">Post</option>
                  <option value="bio">Bio</option>
                </select>
              </Field>
            </div>
            <Field label="Text">
              <textarea value={text} onChange={(e) => setText(e.target.value)} required />
            </Field>
            <div className="row between">
              <label className="check">
                <input type="checkbox" checked={owned} onChange={(e) => setOwned(e.target.checked)} />
                Our own content (untick for competitor or third-party examples; Adpress will never copy those)
              </label>
              <button className="btn secondary" disabled={!text.trim()}>
                Add
              </button>
            </div>
          </form>
        )}
        {PLATFORMS.map((p) => {
          const items = pasted.filter((s) => s.platform === p);
          if (!items.length) return null;
          return (
            <div key={p} style={{ marginTop: 14 }}>
              <h3>
                {PLATFORM_LABELS[p]} <span className="muted small">({items.length})</span>
              </h3>
              {items.map((s) => (
                <div className="source" key={s.id}>
                  <div className="row between small">
                    <span>
                      <span className="badge">{s.kind}</span> {!s.owned && <span className="badge warn">third-party</span>}
                    </span>
                    {canEdit && (
                      <button
                        className="btn ghost small"
                        onClick={async () => {
                          await api.del(`/sources/${s.id}`);
                          load();
                        }}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <pre>{s.text}</pre>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {canEdit && (
        <div className="card row between">
          <div>
            <h2>Build the brand kit</h2>
            <p className="muted small" style={{ margin: 0 }}>
              {brand.current_kit_version
                ? "Rebuilding keeps your locations, offers, and examples, and replaces the rest."
                : "Adpress drafts your voice, words, colors, audiences, and platform themes. You review every guess."}
            </p>
          </div>
          <button className="btn" onClick={buildKit} disabled={!!running || sources.length === 0}>
            {brand.current_kit_version ? "Rebuild kit" : "Build kit"}
          </button>
        </div>
      )}
    </div>
  );
}

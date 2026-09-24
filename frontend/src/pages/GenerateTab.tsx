import { useEffect, useState } from "react";
import { api, waitForJob } from "../api";
import { navigate } from "../router";
import { Alert, Field, JobProgress } from "../components/ui";
import { PLATFORMS, PLATFORM_LABELS, type Brand, type FormatSpec, type Job, type Kit, type User } from "../types";

const MAX_PAIRS = 50;
const MAX_ADS = 200;

function toggle(list: string[], v: string) {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

export default function GenerateTab({ brand, user }: { brand: Brand; user: User }) {
  const [formats, setFormats] = useState<FormatSpec[]>([]);
  const [kit, setKit] = useState<Kit | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [audiences, setAudiences] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [offer, setOffer] = useState("");
  const [angle, setAngle] = useState("");
  const [count, setCount] = useState(5);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<FormatSpec[]>("/formats").then(setFormats).catch((e) => setError(e.message));
    api
      .get<{ kit: Kit }>(`/brands/${brand.id}/kit`)
      .then((r) => setKit(r.kit))
      .catch(() => setKit(null));
  }, [brand.id]);

  if (!brand.kit_ready)
    return (
      <div className="card empty">
        <h2>Finish the brand kit first</h2>
        <p className="muted">
          {brand.current_kit_version
            ? `Review the ${brand.guessed_count} guessed field(s) in the kit so every ad starts from facts you've confirmed.`
            : "Build a brand kit from your website or posts."}
        </p>
        <a className="btn" href={`#/brands/${brand.id}/${brand.current_kit_version ? "kit" : "setup"}`}>
          {brand.current_kit_version ? "Review kit" : "Add content"}
        </a>
      </div>
    );

  const combos = Math.max(chosen.length, 0) * Math.max(audiences.length, 1) * Math.max(locations.length, 1);
  const total = combos * count;
  const running = job && (job.status === "queued" || job.status === "running");
  const tooMany = combos > MAX_PAIRS || total > MAX_ADS;

  const submit = async () => {
    setError("");
    try {
      const j = await api.post<Job>(`/brands/${brand.id}/requests`, {
        formats: chosen,
        audiences,
        locations,
        offer: offer || null,
        angle: angle || null,
        count,
      });
      setJob(j);
      const done = await waitForJob(j.id, setJob);
      if (done.status === "failed") setError(done.error || "Generation failed.");
      else navigate(`/brands/${brand.id}/ads?request=${(done.result as { request_id: string }).request_id}`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="stack">
      <Alert>{error}</Alert>
      <JobProgress job={job} />

      <div className="card">
        <div className="card-title">
          <h2>Platforms and formats</h2>
          <span className="muted small">Pick several to get the same message written natively for each</span>
        </div>
        <div className="format-grid">
        {PLATFORMS.map((p) => {
          const fs = formats.filter((f) => f.platform === p);
          if (!fs.length) return null;
          return (
            <div key={p} className="format-group">
              <div className="xs">{PLATFORM_LABELS[p]}</div>
              <div className="picker">
                {fs.map((f) => (
                  <button
                    type="button"
                    key={f.key}
                    className={`pick ${chosen.includes(f.key) ? "on" : ""}`}
                    onClick={() => setChosen(toggle(chosen, f.key))}
                    aria-pressed={chosen.includes(f.key)}
                  >
                    {f.name}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title">
            <h2>Audiences</h2>
            <span className="muted small">None selected = general audience</span>
          </div>
          <div className="picker">
            {kit?.audiences.map((a) => (
              <button type="button" key={a.name} className={`pick ${audiences.includes(a.name) ? "on" : ""}`}
                aria-pressed={audiences.includes(a.name)} onClick={() => setAudiences(toggle(audiences, a.name))}>
                {a.name}
              </button>
            ))}
            {!kit?.audiences.length && <span className="muted small">Add audiences in the kit.</span>}
          </div>
        </div>
        <div className="card">
          <div className="card-title">
            <h2>Locations</h2>
            <span className="muted small">Each runs every audience</span>
          </div>
          <div className="picker">
            {kit?.locations.map((l) => (
              <button type="button" key={l.name} className={`pick ${locations.includes(l.name) ? "on" : ""}`}
                aria-pressed={locations.includes(l.name)} onClick={() => setLocations(toggle(locations, l.name))}>
                {l.name}
              </button>
            ))}
            {!kit?.locations.length && <span className="muted small">Add locations in the kit.</span>}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="grid-3">
          <Field label="Offer">
            <select value={offer} onChange={(e) => setOffer(e.target.value)}>
              <option value="">No specific offer</option>
              {kit?.offers.map((o) => (
                <option key={o.headline} value={o.headline}>
                  {o.headline}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Angle" hint='Optional, e.g. "spring market", "first-time buyer myths"'>
            <input value={angle} onChange={(e) => setAngle(e.target.value)} maxLength={300} />
          </Field>
          <Field label="Ads per combination" hint="1 to 20">
            <input type="number" min={1} max={20} value={count}
              onChange={(e) => setCount(Math.min(20, Math.max(1, Number(e.target.value) || 1)))} />
          </Field>
        </div>
        <div className="gen-summary">
          <span className={`small num ${tooMany ? "over-limit" : "muted"}`} aria-live="polite">
            {chosen.length
              ? `${combos} combination${combos === 1 ? "" : "s"} × ${count} = ${total} ads` +
                (tooMany ? ` (limit ${MAX_PAIRS} combinations and ${MAX_ADS} ads per run)` : "")
              : "Pick at least one format"}
          </span>
          {user.role !== "Viewer" && (
            <button className="btn" onClick={submit} disabled={!chosen.length || tooMany || !!running}>
              {running ? "Writing…" : `Generate ${total || ""} ads`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

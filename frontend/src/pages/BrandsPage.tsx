import { useEffect, useState } from "react";
import { api } from "../api";
import { navigate } from "../router";
import { Alert, Field, Modal } from "../components/ui";
import { INDUSTRIES, type Brand, type Industry, type Job, type User } from "../types";

export default function BrandsPage({ user }: { user: User }) {
  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.get<Brand[]>("/brands").then(setBrands).catch((e) => setError(e.message));
  }, []);

  const canEdit = user.role !== "Viewer";

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Brands</h1>
          <p className="muted sub">Each brand has one kit that every ad is written from.</p>
        </div>
        {canEdit && (
          <button className="btn" onClick={() => setCreating(true)}>
            New brand
          </button>
        )}
      </div>
      {error && <div className="mt-2"><Alert>{error}</Alert></div>}
      {brands === null ? (
        <p className="muted">Loading…</p>
      ) : brands.length === 0 ? (
        <div className="card empty">
          <h2>Set up your first brand</h2>
          <p className="muted">Enter a website and Adpress drafts a brand kit from it.</p>
          {canEdit && (
            <button className="btn" onClick={() => setCreating(true)}>
              New brand
            </button>
          )}
        </div>
      ) : (
        <div className="brand-list">
          {brands.map((b) => (
            <a key={b.id} className="card brand-card" href={`#/brands/${b.id}/${b.kit_ready ? "generate" : "setup"}`}>
              <div className="row between nowrap">
                <h2 className="truncate">{b.name}</h2>
                {b.kit_ready ? (
                  <span className="badge ok">Kit ready</span>
                ) : b.current_kit_version ? (
                  <span className="badge warn">{b.guessed_count} to review</span>
                ) : (
                  <span className="badge">Setting up</span>
                )}
              </div>
              <p className="muted small truncate">{b.website_url || "No website"}</p>
              <div className="foot">
                <span>{INDUSTRIES.find(([k]) => k === b.industry)?.[1]}</span>
                <span className="num">{b.ad_count} ads</span>
              </div>
            </a>
          ))}
        </div>
      )}
      {creating && <NewBrand onClose={() => setCreating(false)} />}
    </div>
  );
}

function NewBrand({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [industry, setIndustry] = useState<Industry>("general");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ brand: Brand; job: Job | null }>("/brands", {
        name,
        website_url: url || null,
        industry,
      });
      navigate(`/brands/${res.brand.id}/setup${res.job ? `?job=${res.job.id}` : ""}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal onClose={onClose}>
      <form onSubmit={submit}>
        <h2>New brand</h2>
        <Alert>{error}</Alert>
        <Field label="Company name">
          <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </Field>
        <Field label="Website" hint="We read up to 10 public pages to learn your voice, colors, and facts.">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="example.com" />
        </Field>
        <Field label="Industry" hint="Housing, credit, and employment ads get stricter compliance checks.">
          <select value={industry} onChange={(e) => setIndustry(e.target.value as Industry)}>
            {INDUSTRIES.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create brand"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

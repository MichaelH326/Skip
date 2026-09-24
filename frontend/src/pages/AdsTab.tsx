import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import AdPreview from "../components/AdPreview";
import { Alert, Field, Modal, Spinner } from "../components/ui";
import {
  PLATFORMS,
  PLATFORM_LABELS,
  type Ad,
  type AdContent,
  type Brand,
  type Flag,
  type FormatSpec,
  type Kit,
  type Metrics,
  type Platform,
  type User,
} from "../types";
import { hashQuery } from "./BrandPage";

const REFINES: [string, string][] = [
  ["shorter", "Shorter"],
  ["more_local", "More local"],
  ["different_angle", "Different angle"],
  ["more_formal", "More formal"],
  ["more_casual", "More casual"],
];

export default function AdsTab({ brand, user, onChange }: { brand: Brand; user: User; onChange: () => void }) {
  const [ads, setAds] = useState<Ad[] | null>(null);
  const [kit, setKit] = useState<Kit | null>(null);
  const [formats, setFormats] = useState<Record<string, FormatSpec>>({});
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [status, setStatus] = useState("");
  const [platform, setPlatform] = useState<string>("");
  const [requestId, setRequestId] = useState(hashQuery().get("request") || "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exportPlatform, setExportPlatform] = useState<Platform>("facebook");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    if (platform) q.set("platform", platform);
    if (requestId) q.set("request_id", requestId);
    try {
      const [list, m] = await Promise.all([
        api.get<Ad[]>(`/brands/${brand.id}/ads?${q}`),
        api.get<Metrics>(`/brands/${brand.id}/metrics`),
      ]);
      setAds(list);
      setMetrics(m);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [brand.id, status, platform, requestId]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    api.get<{ kit: Kit }>(`/brands/${brand.id}/kit`).then((r) => setKit(r.kit)).catch(() => {});
    api
      .get<FormatSpec[]>("/formats")
      .then((fs) => setFormats(Object.fromEntries(fs.map((f) => [f.key, f]))))
      .catch(() => {});
  }, [brand.id]);

  const replace = (updated: Ad, oldId?: string) => {
    setAds((prev) => (prev || []).map((a) => (a.id === (oldId || updated.id) ? updated : a)));
    onChange();
  };

  const selectedForPlatform = useMemo(
    () => (ads || []).filter((a) => selected.has(a.id) && a.platform === exportPlatform),
    [ads, selected, exportPlatform],
  );

  const exportCsv = async () => {
    setError("");
    setNotice("");
    try {
      await api.download("POST", `/brands/${brand.id}/exports`, {
        platform: exportPlatform,
        ad_ids: selectedForPlatform.length ? selectedForPlatform.map((a) => a.id) : null,
      });
      setNotice(
        `Exported ${selectedForPlatform.length || "approved"} ${PLATFORM_LABELS[exportPlatform]} ads.` +
          (kit?.compliance.special_ad_category
            ? " Set the Special Ad Category in Ads Manager: this brand's industry requires it."
            : ""),
      );
      setSelected(new Set());
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const canEdit = user.role !== "Viewer";

  return (
    <div>
      {metrics && metrics.ads_generated > 0 && (
        <div className="stats">
          <Stat v={metrics.ads_generated} l="Ads generated" />
          <Stat v={metrics.ads_kept} l="Approved or exported" />
          <Stat v={pct(metrics.kept_without_edits_pct)} l="Kept without edits (target 60%)" />
          <Stat v={pct(metrics.kept_after_light_edits_pct)} l="Kept after light edits (target 85%)" />
          <Stat v={metrics.flags_per_100_ads ?? "—"} l="Flags per 100 ads" />
          <Stat v={metrics.cost_per_ad_usd != null ? `$${metrics.cost_per_ad_usd.toFixed(3)}` : "—"} l="AI cost per ad" />
        </div>
      )}
      <div className="toolbar">
        <div className="group">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">All active</option>
          <option value="draft">Drafts</option>
          <option value="approved">Approved</option>
          <option value="exported">Exported</option>
        </select>
        <select value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label="Platform">
          <option value="">All platforms</option>
          {PLATFORMS.map((p) => (
            <option key={p} value={p}>
              {PLATFORM_LABELS[p]}
            </option>
          ))}
        </select>
        {requestId && (
          <button className="btn ghost small" onClick={() => setRequestId("")}>
            Latest run only ✕
          </button>
        )}
        </div>
        {canEdit && (
          <div className="group export">
            <select value={exportPlatform} onChange={(e) => setExportPlatform(e.target.value as Platform)}
              aria-label="Export platform">
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABELS[p]}
                </option>
              ))}
            </select>
            <button className="btn" onClick={exportCsv}>
              Export {selectedForPlatform.length ? `${selectedForPlatform.length} selected` : "approved"} as CSV
            </button>
          </div>
        )}
      </div>
      {(error || notice) && (
        <div className="stack-sm notices">
          <Alert>{error}</Alert>
          <Alert kind="ok">{notice}</Alert>
        </div>
      )}
      {ads === null ? (
        <p className="muted">Loading…</p>
      ) : ads.length === 0 ? (
        <div className="card empty">
          <h2>No ads here yet</h2>
          <a className="btn" href={`#/brands/${brand.id}/generate`}>
            Generate ads
          </a>
        </div>
      ) : (
        <div className="ad-grid">
          {ads.map((ad) => (
            <AdCard
              key={ad.id}
              ad={ad}
              kit={kit}
              brand={brand}
              user={user}
              format={formats[ad.format]}
              selected={selected.has(ad.id)}
              onSelect={(on) => {
                const next = new Set(selected);
                if (on) next.add(ad.id);
                else next.delete(ad.id);
                setSelected(next);
              }}
              onUpdate={replace}
              onError={setError}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function pct(v: number | null) {
  return v == null ? "—" : `${v}%`;
}

function Stat({ v, l }: { v: string | number; l: string }) {
  return (
    <div className="stat">
      <div className="v">{v}</div>
      <div className="l">{l}</div>
    </div>
  );
}

/** Replace the flagged words with the suggestion, in the flagged field when known. */
function applySuggestion(content: AdContent, flag: Flag): AdContent {
  const next: AdContent = structuredClone(content);
  const swap = (s: string) => s.split(flag.words).join(flag.suggestion || "").replace(/\s{2,}/g, " ").trim();
  const m = flag.field ? /^(\w+)(?:\[(\d+)\])?$/.exec(flag.field) : null;
  const touch = (key: string, idx?: number) => {
    if (key === "cta") next.cta = swap(next.cta);
    else if (key === "hashtags" && idx !== undefined) next.hashtags[idx] = swap(next.hashtags[idx]);
    else {
      const v = next.fields[key];
      if (Array.isArray(v)) {
        if (idx !== undefined) v[idx] = swap(v[idx]);
        else next.fields[key] = v.map(swap);
      } else if (typeof v === "string") next.fields[key] = swap(v);
    }
  };
  if (m) touch(m[1], m[2] !== undefined ? Number(m[2]) : undefined);
  else Object.keys(next.fields).forEach((k) => touch(k));
  next.hashtags = next.hashtags.filter((h) => h.trim());
  return next;
}

function AdCard({
  ad,
  kit,
  brand,
  user,
  format,
  selected,
  onSelect,
  onUpdate,
  onError,
}: {
  ad: Ad;
  kit: Kit | null;
  brand: Brand;
  user: User;
  format?: FormatSpec;
  selected: boolean;
  onSelect: (on: boolean) => void;
  onUpdate: (ad: Ad, oldId?: string) => void;
  onError: (msg: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<AdContent>(ad.content);
  const [busy, setBusy] = useState(false);
  const [overriding, setOverriding] = useState<number | null>(null);
  const [custom, setCustom] = useState(false);
  const canEdit = user.role !== "Viewer";

  const patch = async (body: object) => {
    setBusy(true);
    onError("");
    try {
      const updated = await api.patch<Ad>(`/ads/${ad.id}`, body);
      onUpdate(updated);
      setDraft(updated.content);
      return true;
    } catch (e) {
      onError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const refine = async (instruction: string) => {
    setBusy(true);
    onError("");
    try {
      const child = await api.post<Ad>(`/ads/${ad.id}/refine`, { instruction });
      onUpdate(child, ad.id);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = ad.flags.filter((f) => !f.overridden);
  const blocking = open.filter((f) => f.severity === "blocking");

  return (
    <div className={`card ad-card ${selected ? "selected" : ""}`}>
      <div className="ad-head">
        {canEdit && (
          <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label="Select for export" />
        )}
        <span className="ad-format truncate" title={format?.name || ad.format}>{format?.name || ad.format}</span>
        <span className={`badge cap ${ad.status === "approved" ? "ok" : ad.status === "exported" ? "accent" : ""}`}>
          {ad.status}
        </span>
      </div>
      <div className="ad-sub">
        <span className="truncate" title={[ad.audience, ad.location, ad.offer, ad.angle].filter(Boolean).join(" · ")}>
          {[ad.audience, ad.location, ad.offer, ad.angle].filter(Boolean).join(" · ") || "General audience"}
        </span>
        {ad.edited && <span className="badge">edited</span>}
        {blocking.length > 0 && <span className="badge danger">{blocking.length} blocking</span>}
      </div>

      <div className="ad-body">
        {editing && format ? (
          <EditFields format={format} content={draft} onChange={setDraft} />
        ) : (
          <AdPreview ad={ad} kit={kit} websiteUrl={brand.website_url} />
        )}

        {ad.flags.length > 0 && (
          <div className="flags">
            {ad.flags.map((f, i) => (
              <div key={i} className={`flag ${f.overridden ? "overridden" : f.severity}`}>
                <div className="flag-head">
                  {f.overridden ? "Overridden: " : ""}
                  {f.label}
                  {f.source === "review" && <span className="badge">AI review</span>}
                </div>
                <div>{f.message}</div>
                {f.overridden && f.override_reason && <div className="xs mt-1">Reason: {f.override_reason}</div>}
                {canEdit && !f.overridden && (
                  <div className="flag-actions">
                    {f.words && f.suggestion !== null && ad.status !== "superseded" && (
                      <button className="btn secondary small" disabled={busy}
                        onClick={() => patch({ content: applySuggestion(ad.content, f) })}>
                        {f.suggestion ? `Replace with “${f.suggestion}”` : `Remove “${f.words}”`}
                      </button>
                    )}
                    {f.severity === "blocking" && user.role === "Owner" && (
                      <button className="btn ghost small" onClick={() => setOverriding(i)}>
                        Override
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {ad.content.image_direction && !editing && (
          <div className="image-note">
            <strong>Image direction:</strong> {ad.content.image_direction}
          </div>
        )}
      </div>

      {canEdit && (
        <div className="ad-actions">
          {editing ? (
            <>
              <button className="btn small" disabled={busy}
                onClick={async () => (await patch({ content: draft })) && setEditing(false)}>
                Save
              </button>
              <button className="btn ghost small" onClick={() => { setDraft(ad.content); setEditing(false); }}>
                Cancel
              </button>
              {busy && <Spinner />}
            </>
          ) : (
            <>
              {ad.status === "draft" ? (
                <button className="btn small" disabled={busy || blocking.length > 0}
                  title={blocking.length ? "Fix or override blocking flags first" : ""}
                  onClick={() => patch({ status: "approved" })}>
                  Approve
                </button>
              ) : (
                <button className="btn secondary small" disabled={busy} onClick={() => patch({ status: "draft" })}>
                  Back to draft
                </button>
              )}
              <button className="btn secondary small" onClick={() => setEditing(true)} disabled={!format}>
                Edit
              </button>
              {busy && <Spinner />}
              <select
                className="small"
                value=""
                disabled={busy}
                aria-label="Refine"
                onChange={(e) => {
                  if (e.target.value === "custom") setCustom(true);
                  else if (e.target.value) refine(e.target.value);
                }}
              >
                <option value="">Refine…</option>
                {REFINES.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
                <option value="custom">Custom instruction…</option>
              </select>
            </>
          )}
        </div>
      )}

      {overriding !== null && (
        <OverrideModal
          flag={ad.flags[overriding]}
          onClose={() => setOverriding(null)}
          onSubmit={async (reason) => {
            if (await patch({ override: { index: overriding, reason } })) setOverriding(null);
          }}
        />
      )}
      {custom && (
        <CustomRefine
          onClose={() => setCustom(false)}
          onSubmit={(text) => {
            setCustom(false);
            refine(text);
          }}
        />
      )}
    </div>
  );
}

function EditFields({ format, content, onChange }: { format: FormatSpec; content: AdContent; onChange: (c: AdContent) => void }) {
  const setField = (key: string, value: string | string[]) =>
    onChange({ ...content, fields: { ...content.fields, [key]: value } });
  const counter = (text: string, rec: number, limit: number) => {
    const n = text.length;
    return <div className={`count ${n > limit ? "over" : n > rec ? "warn" : ""}`}>{n} / {limit}{rec < limit ? ` (aim for ${rec})` : ""}</div>;
  };
  return (
    <div>
      {format.fields.map((spec) => {
        const value = content.fields[spec.key];
        if (spec.multi) {
          const items = Array.isArray(value) ? value : [];
          return (
            <div className="edit-field" key={spec.key}>
              <label>{spec.label} ({spec.multi.min}–{spec.multi.max})</label>
              {items.map((item, i) => (
                <div key={i} className="edit-item">
                  <div className="row nowrap">
                    <input value={item} className="grow"
                      onChange={(e) => setField(spec.key, items.map((x, j) => (j === i ? e.target.value : x)))} />
                    <button type="button" className="btn ghost small"
                      aria-label="Remove" onClick={() => setField(spec.key, items.filter((_, j) => j !== i))}>✕</button>
                  </div>
                  {counter(item, spec.recommended, spec.limit)}
                </div>
              ))}
              {items.length < spec.multi.max && (
                <button type="button" className="btn ghost small" onClick={() => setField(spec.key, [...items, ""])}>
                  + Add
                </button>
              )}
            </div>
          );
        }
        const text = typeof value === "string" ? value : "";
        return (
          <div className="edit-field" key={spec.key}>
            <label>{spec.label}</label>
            {spec.limit > 100 ? (
              <textarea value={text} onChange={(e) => setField(spec.key, e.target.value)} />
            ) : (
              <input value={text} onChange={(e) => setField(spec.key, e.target.value)} />
            )}
            {counter(text, spec.recommended, spec.limit)}
          </div>
        );
      })}
      <div className="grid-2 mt-3">
        <Field label="Call to action">
          <input value={content.cta} onChange={(e) => onChange({ ...content, cta: e.target.value })} />
        </Field>
        {format.max_hashtags > 0 && (
          <Field label={`Hashtags (max ${format.max_hashtags})`}>
            <input
              value={content.hashtags.join(" ")}
              onChange={(e) => onChange({ ...content, hashtags: e.target.value.split(/\s+/).filter(Boolean) })}
            />
          </Field>
        )}
      </div>
      {format.image_direction && (
        <div className="mt-3">
        <Field label="Image direction">
          <textarea value={content.image_direction} onChange={(e) => onChange({ ...content, image_direction: e.target.value })} />
        </Field>
        </div>
      )}
    </div>
  );
}

function OverrideModal({ flag, onClose, onSubmit }: { flag: Flag; onClose: () => void; onSubmit: (r: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <Modal onClose={onClose}>
      <h2>Override “{flag.label}”</h2>
      <p className="small">{flag.message}</p>
      <p className="small muted mt-2">Overrides are logged with your name, the time, and your reason.</p>
      <div className="mt-4" />
      <Field label="Reason">
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
      </Field>
      <div className="modal-actions">
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={reason.trim().length < 3} onClick={() => onSubmit(reason.trim())}>
          Override
        </button>
      </div>
    </Modal>
  );
}

function CustomRefine({ onClose, onSubmit }: { onClose: () => void; onSubmit: (t: string) => void }) {
  const [text, setText] = useState("");
  return (
    <Modal onClose={onClose}>
      <h2>Refine this ad</h2>
      <Field label="Instruction" hint='e.g. "lead with the free valuation", "mention the waterfront"'>
        <input value={text} onChange={(e) => setText(e.target.value)} autoFocus maxLength={500} />
      </Field>
      <div className="modal-actions">
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={!text.trim()} onClick={() => onSubmit(text.trim())}>
          Rewrite
        </button>
      </div>
    </Modal>
  );
}

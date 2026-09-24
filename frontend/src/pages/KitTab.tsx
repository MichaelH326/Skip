import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { Alert, ChipList, Field } from "../components/ui";
import {
  INDUSTRIES,
  PLATFORMS,
  PLATFORM_LABELS,
  type Audience,
  type Brand,
  type Color,
  type Example,
  type Fact,
  type Industry,
  type Kit,
  type Location,
  type Offer,
  type Platform,
  type PlatformTheme,
  type User,
  type VoiceDials,
} from "../types";

type SaveState = "saved" | "saving" | "pending" | "error";

export default function KitTab({ brand, user, onChange }: { brand: Brand; user: User; onChange: () => void }) {
  const [kit, setKit] = useState<Kit | null>(null);
  const [missing, setMissing] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const version = useRef(0);
  const queued = useRef<Kit | null>(null);
  const saving = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const readOnly = user.role === "Viewer";

  const load = useCallback(async () => {
    try {
      const res = await api.get<{ version: number; kit: Kit }>(`/brands/${brand.id}/kit`);
      version.current = res.version;
      setKit(res.kit);
      setConflict(false);
      setError("");
      setSaveState("saved");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMissing(true);
      else setError((e as Error).message);
    }
  }, [brand.id]);

  useEffect(() => {
    load();
    return () => window.clearTimeout(timer.current);
  }, [load]);

  const flush = useCallback(async () => {
    if (saving.current || !queued.current) return;
    const next = queued.current;
    queued.current = null;
    saving.current = true;
    setSaveState("saving");
    try {
      const res = await api.put<{ version: number }>(`/brands/${brand.id}/kit`, {
        kit: next,
        base_version: version.current,
      });
      version.current = res.version;
      setError("");
      setSaveState(queued.current ? "pending" : "saved");
      onChange();
    } catch (e) {
      setSaveState("error");
      if (e instanceof ApiError && e.status === 409) setConflict(true);
      setError((e as Error).message);
    } finally {
      saving.current = false;
      if (queued.current) flush();
    }
  }, [brand.id, onChange]);

  /** Apply a change. Editing a guessed field confirms it. */
  const update = useCallback(
    (fn: (k: Kit) => Kit, confirms: string[] = []) => {
      setKit((prev) => {
        if (!prev) return prev;
        const next = fn(prev);
        if (confirms.length) {
          const guessed = { ...next.guessed };
          confirms.forEach((c) => delete guessed[c]);
          next.guessed = guessed;
        }
        queued.current = next;
        setSaveState("pending");
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(flush, 700);
        return next;
      });
    },
    [flush],
  );

  if (missing)
    return (
      <div className="card empty">
        <h2>No kit yet</h2>
        <p className="muted">Add your website or social content, then build the kit.</p>
        <a className="btn" href={`#/brands/${brand.id}/setup`}>
          Go to content
        </a>
      </div>
    );
  if (!kit) return error ? <Alert>{error}</Alert> : <p className="muted">Loading…</p>;

  const guessedKeys = Object.keys(kit.guessed);
  const set = <K extends keyof Kit>(key: K, value: Kit[K], confirms: string[] = [key as string]) =>
    update((k) => ({ ...k, [key]: value }), confirms);

  const exportMd = () => api.download("GET", `/brands/${brand.id}/kit/export.md`).catch((e) => setError(e.message));
  const importMd = async (file: File) => {
    try {
      const markdown = await file.text();
      const res = await api.post<{ version: number; kit: Kit }>(`/brands/${brand.id}/kit/import`, { markdown });
      version.current = res.version;
      setKit(res.kit);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="stack">
      <div className="kit-bar">
        <div className="row">
          {guessedKeys.length ? (
            <span className="badge warn">{guessedKeys.length} guessed fields to review before generating</span>
          ) : (
            <span className="badge ok">Kit reviewed: ready to generate</span>
          )}
          {!readOnly && (
            <span className={`save-state ${saveState}`} aria-live="polite">
              {saveState === "saving" ? "Saving…" : saveState === "pending" ? "Unsaved changes" : saveState === "saved" ? "All changes saved" : "Not saved"}
            </span>
          )}
        </div>
        <div className="row">
          {!readOnly && guessedKeys.length > 0 && (
            <button className="btn secondary small" onClick={() => update((k) => k, guessedKeys)}>
              Confirm all guesses
            </button>
          )}
          <button className="btn secondary small" onClick={exportMd}>
            Export .md
          </button>
          {!readOnly && (
            <label className="btn secondary small file">
              Import .md
              <input
                type="file"
                accept=".md,text/markdown"
                onChange={(e) => e.target.files?.[0] && importMd(e.target.files[0])}
              />
            </label>
          )}
        </div>
      </div>
      {conflict ? (
        <Alert>
          {error}{" "}
          <button className="btn small secondary" onClick={load}>
            Reload kit
          </button>
        </Alert>
      ) : (
        <Alert>{error}</Alert>
      )}

      <fieldset disabled={readOnly} className="plain stack">
        <Section title="Voice" kit={kit} keys={["core_voice", "voice_dials"]} update={update}>
          <Field label="Core voice" hint={`${kit.core_voice.length}/300 characters`}>
            <textarea
              value={kit.core_voice}
              maxLength={300}
              onChange={(e) => set("core_voice", e.target.value)}
            />
          </Field>
          <div className="dials">
            {(Object.keys(kit.voice_dials) as (keyof VoiceDials)[]).map((d) => (
              <div className="dial" key={d}>
                <label>
                  <span className="cap">{d}</span>
                  <span>{kit.voice_dials[d]}</span>
                </label>
                <input
                  type="range"
                  min={1}
                  max={5}
                  value={kit.voice_dials[d]}
                  onChange={(e) => set("voice_dials", { ...kit.voice_dials, [d]: Number(e.target.value) })}
                  aria-label={d}
                />
              </div>
            ))}
          </div>
        </Section>

        <Section title="Words" kit={kit} keys={["always_words", "never_words"]} update={update}>
          <div className="grid-2">
            <Field label="Always use">
              <ChipList values={kit.always_words} onChange={(v) => set("always_words", v)} disabled={readOnly} />
            </Field>
            <Field label="Never use" hint="Ads with these words (or their forms) are blocked.">
              <ChipList values={kit.never_words} onChange={(v) => set("never_words", v)} disabled={readOnly} />
            </Field>
          </div>
        </Section>

        <Section
          title="Facts"
          subtitle="The only numbers, awards, and claims ads may use. Anything else is flagged."
          kit={kit}
          keys={["facts"]}
          update={update}
        >
          <ListEditor<Fact>
            items={kit.facts}
            onChange={(v) => set("facts", v)}
            blank={{ claim: "", source_url: "" }}
            addLabel="Add fact"
            title={(f) => f.claim || "New fact"}
            render={(f, change) => (
              <div className="grid-2">
                <Field label="Claim">
                  <input value={f.claim} onChange={(e) => change({ ...f, claim: e.target.value })} />
                </Field>
                <Field label="Source URL">
                  <input value={f.source_url} onChange={(e) => change({ ...f, source_url: e.target.value })} />
                </Field>
              </div>
            )}
          />
        </Section>

        <Section title="Colors and type" kit={kit} keys={["colors", "typography"]} update={update}>
          <ListEditor<Color>
            items={kit.colors}
            onChange={(v) => set("colors", v)}
            blank={{ hex: "#1F3A5F", role: "primary" }}
            addLabel="Add color"
            title={(c) => (
              <span className="row nowrap">
                <span className="swatch" style={{ background: c.hex }} />
                <span className="num">{c.hex}</span>
                <span className="muted cap">{c.role}</span>
              </span>
            )}
            render={(c, change) => (
              <div className="row nowrap">
                <input type="color" value={c.hex.length === 7 ? c.hex : "#000000"}
                  onChange={(e) => change({ ...c, hex: e.target.value.toUpperCase() })} />
                <input className="hex" value={c.hex} onChange={(e) => change({ ...c, hex: e.target.value })} aria-label="Hex" />
                <select className="role" value={c.role} onChange={(e) => change({ ...c, role: e.target.value as Color["role"] })}
                  aria-label="Role">
                  <option value="primary">Primary</option>
                  <option value="secondary">Secondary</option>
                  <option value="accent">Accent</option>
                  <option value="background">Background</option>
                </select>
              </div>
            )}
          />
          <div className="grid-2 mt-4">
            <Field label="Heading font">
              <input value={kit.typography.heading}
                onChange={(e) => set("typography", { ...kit.typography, heading: e.target.value })} />
            </Field>
            <Field label="Body font">
              <input value={kit.typography.body}
                onChange={(e) => set("typography", { ...kit.typography, body: e.target.value })} />
            </Field>
          </div>
        </Section>

        <Section title="Compliance" kit={kit} keys={["compliance"]} update={update}>
          <div className="grid-2">
            <Field label="Industry">
              <select
                value={kit.compliance.industry}
                onChange={(e) => set("compliance", { ...kit.compliance, industry: e.target.value as Industry })}
              >
                {INDUSTRIES.map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Meta special ad category">
              <label className="check">
                <input
                  type="checkbox"
                  checked={kit.compliance.special_ad_category}
                  onChange={(e) => set("compliance", { ...kit.compliance, special_ad_category: e.target.checked })}
                />
                Required (housing, credit, employment)
              </label>
            </Field>
          </div>
          <Field label="Required disclaimers" hint="Every ad must include each of these, word for word.">
            <ChipList
              values={kit.compliance.required_disclaimers}
              onChange={(v) => set("compliance", { ...kit.compliance, required_disclaimers: v })}
              disabled={readOnly}
            />
          </Field>
          <Field label="Rules">
            <ChipList
              values={kit.compliance.rules}
              onChange={(v) => set("compliance", { ...kit.compliance, rules: v })}
              disabled={readOnly}
            />
          </Field>
        </Section>

        <Section title="Platform themes" subtitle="How the voice shifts on each platform." kit={kit}
          keys={PLATFORMS.map((p) => `platform_themes.${p}`)} update={update}>
          {PLATFORMS.filter((p) => kit.platform_themes[p]).map((p) => {
            const theme = kit.platform_themes[p]!;
            const key = `platform_themes.${p}`;
            const change = (t: PlatformTheme) => set("platform_themes", { ...kit.platform_themes, [p]: t }, [key]);
            return (
              <div className="list-item" key={p}>
                <div className="list-item-head">
                  <h3>{PLATFORM_LABELS[p as Platform]}</h3>
                  <button type="button" className="btn ghost small" onClick={() => {
                    const next = { ...kit.platform_themes };
                    delete next[p];
                    set("platform_themes", next, [key]);
                  }}>Remove</button>
                </div>
                <div className="grid-3">
                  {(["audience", "voice_shift", "length", "hashtags", "emoji", "cta_style"] as const).map((f) => (
                    <Field key={f} label={f.replace("_", " ").replace(/^./, (c) => c.toUpperCase())}>
                      <input value={theme[f]} onChange={(e) => change({ ...theme, [f]: e.target.value })} />
                    </Field>
                  ))}
                </div>
              </div>
            );
          })}
          {PLATFORMS.some((p) => !kit.platform_themes[p]) && (
            <div className="add-row">
              {PLATFORMS.filter((p) => !kit.platform_themes[p]).map((p) => (
                <button key={p} type="button" className="btn secondary small"
                  onClick={() => set("platform_themes", { ...kit.platform_themes, [p]: blankTheme() }, [`platform_themes.${p}`])}>
                  + {PLATFORM_LABELS[p]}
                </button>
              ))}
            </div>
          )}
        </Section>

        <Section title="Audiences" kit={kit} keys={["audiences"]} update={update}>
          <ListEditor<Audience>
            items={kit.audiences}
            onChange={(v) => set("audiences", v)}
            blank={{ name: "", who: "", goals: [], objections: [], key_message: "", best_platforms: [], ctas: [] }}
            addLabel="Add audience"
            title={(a) => a.name || "New audience"}
            render={(a, change) => (
              <>
                <div className="grid-2">
                  <Field label="Name"><input value={a.name} onChange={(e) => change({ ...a, name: e.target.value })} /></Field>
                  <Field label="Key message"><input value={a.key_message} onChange={(e) => change({ ...a, key_message: e.target.value })} /></Field>
                </div>
                <Field label="Who they are" hint="Describe needs and situation, never protected traits like age, religion, or family status.">
                  <textarea value={a.who} onChange={(e) => change({ ...a, who: e.target.value })} />
                </Field>
                <div className="grid-2">
                  <Field label="Goals"><ChipList values={a.goals} onChange={(v) => change({ ...a, goals: v })} disabled={readOnly} /></Field>
                  <Field label="Objections"><ChipList values={a.objections} onChange={(v) => change({ ...a, objections: v })} disabled={readOnly} /></Field>
                  <Field label="Best platforms"><ChipList values={a.best_platforms} onChange={(v) => change({ ...a, best_platforms: v })} disabled={readOnly} /></Field>
                  <Field label="CTAs"><ChipList values={a.ctas} onChange={(v) => change({ ...a, ctas: v })} disabled={readOnly} /></Field>
                </div>
              </>
            )}
          />
        </Section>

        <Section title="Locations" subtitle="Only details you enter here are used in local ads." kit={kit} keys={["locations"]} update={update}>
          <ListEditor<Location>
            items={kit.locations}
            onChange={(v) => set("locations", v)}
            blank={{ name: "", references: [], phrasing: "", seasonal_hooks: [], avoid: [] }}
            addLabel="Add location"
            title={(l) => l.name || "New location"}
            render={(l, change) => (
              <>
                <div className="grid-2">
                  <Field label="Name"><input value={l.name} onChange={(e) => change({ ...l, name: e.target.value })} /></Field>
                  <Field label="Local phrasing"><input value={l.phrasing} onChange={(e) => change({ ...l, phrasing: e.target.value })} /></Field>
                </div>
                <div className="grid-3">
                  <Field label="References (landmarks, neighborhoods)"><ChipList values={l.references} onChange={(v) => change({ ...l, references: v })} disabled={readOnly} /></Field>
                  <Field label="Seasonal hooks"><ChipList values={l.seasonal_hooks} onChange={(v) => change({ ...l, seasonal_hooks: v })} disabled={readOnly} /></Field>
                  <Field label="Avoid"><ChipList values={l.avoid} onChange={(v) => change({ ...l, avoid: v })} disabled={readOnly} /></Field>
                </div>
              </>
            )}
          />
        </Section>

        <Section title="Offers" kit={kit} keys={["offers"]} update={update}>
          <ListEditor<Offer>
            items={kit.offers}
            onChange={(v) => set("offers", v)}
            blank={{ headline: "", proof: "", cta: "", expires_on: null }}
            addLabel="Add offer"
            title={(o) => o.headline || "New offer"}
            render={(o, change) => (
              <div className="grid-4">
                <Field label="Headline promise"><input value={o.headline} onChange={(e) => change({ ...o, headline: e.target.value })} /></Field>
                <Field label="Proof"><input value={o.proof} onChange={(e) => change({ ...o, proof: e.target.value })} /></Field>
                <Field label="CTA"><input value={o.cta} onChange={(e) => change({ ...o, cta: e.target.value })} /></Field>
                <Field label="Expires">
                  <input type="date" value={o.expires_on || ""} onChange={(e) => change({ ...o, expires_on: e.target.value || null })} />
                </Field>
              </div>
            )}
          />
        </Section>

        <Section title="Examples" subtitle="Ads or posts that show the voice well (good) or badly (bad)." kit={kit} keys={["examples"]} update={update}>
          <ListEditor<Example>
            items={kit.examples}
            onChange={(v) => set("examples", v)}
            blank={{ text: "", platform: "", rating: "good" }}
            addLabel="Add example"
            title={(x) => `${x.rating === "good" ? "Good" : "Bad"}${x.platform ? ` · ${x.platform}` : ""}`}
            render={(x, change) => (
              <>
                <Field label="Text"><textarea value={x.text} onChange={(e) => change({ ...x, text: e.target.value })} /></Field>
                <div className="grid-2">
                  <Field label="Platform"><input value={x.platform} onChange={(e) => change({ ...x, platform: e.target.value })} /></Field>
                  <Field label="Rating">
                    <select value={x.rating} onChange={(e) => change({ ...x, rating: e.target.value as Example["rating"] })}>
                      <option value="good">Good example</option>
                      <option value="bad">Bad example</option>
                    </select>
                  </Field>
                </div>
              </>
            )}
          />
        </Section>
      </fieldset>
    </div>
  );
}

function blankTheme(): PlatformTheme {
  return { audience: "", voice_shift: "", length: "", hashtags: "", emoji: "", cta_style: "", colors: [] };
}

function Section({
  title,
  subtitle,
  kit,
  keys,
  update,
  children,
}: {
  title: string;
  subtitle?: string;
  kit: Kit;
  keys: string[];
  update: (fn: (k: Kit) => Kit, confirms?: string[]) => void;
  children: ReactNode;
}) {
  const guesses = keys.filter((k) => kit.guessed[k]);
  return (
    <section className={`card ${guesses.length ? "section-guessed" : ""}`}>
      <div className="card-title">
        <h2>{title}</h2>
        {subtitle && <span className="muted small">{subtitle}</span>}
      </div>
      {guesses.map((k) => (
        <div className="guess" key={k}>
          <span className="grow">
            <strong>Guessed{k.includes(".") ? ` (${k.split(".")[1]})` : ""}:</strong> {kit.guessed[k]}
          </span>
          <button type="button" className="btn secondary small" onClick={() => update((x) => x, [k])}>
            Looks right
          </button>
        </div>
      ))}
      {children}
    </section>
  );
}

function ListEditor<T>({
  items,
  onChange,
  blank,
  render,
  title,
  addLabel,
}: {
  items: T[];
  onChange: (items: T[]) => void;
  blank: T;
  render: (item: T, change: (item: T) => void) => ReactNode;
  title: (item: T) => ReactNode;
  addLabel: string;
}) {
  return (
    <div>
      {items.map((item, i) => (
        <div className="list-item" key={i}>
          <div className="list-item-head">
            <strong>{title(item)}</strong>
            <button type="button" className="btn ghost small" onClick={() => onChange(items.filter((_, j) => j !== i))}>
              Remove
            </button>
          </div>
          {render(item, (next) => onChange(items.map((x, j) => (j === i ? next : x))))}
        </div>
      ))}
      <button type="button" className="btn secondary small" onClick={() => onChange([...items, structuredClone(blank)])}>
        + {addLabel}
      </button>
    </div>
  );
}

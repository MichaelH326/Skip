import { useEffect, useState, type ReactNode } from "react";
import type { Job } from "../types";

export function Alert({ kind = "error", children }: { kind?: "error" | "warn" | "ok" | "info"; children: ReactNode }) {
  if (!children) return null;
  return <div className={`alert ${kind}`}>{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="Working" />;
}

export function JobProgress({ job }: { job: Job | null }) {
  if (!job || job.status === "done" || job.status === "failed") return null;
  return (
    <div className="alert info progress">
      <Spinner /> {job.progress || "Starting…"}
    </div>
  );
}

export function ChipList({
  values,
  onChange,
  placeholder,
  disabled,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const items = draft
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter((s) => s && !values.includes(s));
    if (items.length) onChange([...values, ...items]);
    setDraft("");
  };
  return (
    <div>
      <div className="chips">
        {values.map((v) => (
          <span className="chip" key={v} title={v}>
            <span>{v}</span>
            {!disabled && (
              <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}>
                ×
              </button>
            )}
          </span>
        ))}
        {!values.length && <span className="muted small">None yet</span>}
      </div>
      {!disabled && (
        <div className="chip-input">
          <input
            value={draft}
            placeholder={placeholder || "Add and press Enter"}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
          <button type="button" className="btn secondary" onClick={add} disabled={!draft.trim()}>
            Add
          </button>
        </div>
      )}
    </div>
  );
}

export function Modal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        {children}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

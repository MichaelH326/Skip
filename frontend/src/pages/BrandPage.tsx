import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { navigate } from "../router";
import { Alert } from "../components/ui";
import { INDUSTRIES, type Brand, type User } from "../types";
import SetupTab from "./SetupTab";
import KitTab from "./KitTab";
import GenerateTab from "./GenerateTab";
import AdsTab from "./AdsTab";

export function hashQuery(): URLSearchParams {
  const q = window.location.hash.split("?")[1] || "";
  return new URLSearchParams(q);
}

export default function BrandPage({ brandId, tab, user }: { brandId: string; tab: string; user: User }) {
  const [brand, setBrand] = useState<Brand | null>(null);
  const [error, setError] = useState("");
  const current = tab.split("?")[0];

  const reload = useCallback(
    () =>
      api
        .get<Brand>(`/brands/${brandId}`)
        .then(setBrand)
        .catch((e) => setError(e.message)),
    [brandId],
  );
  useEffect(() => {
    reload();
  }, [reload]);

  if (error) return <Alert>{error}</Alert>;
  if (!brand) return <p className="muted">Loading…</p>;

  const tabs: [string, string, React.ReactNode?][] = [
    ["setup", "1. Content"],
    [
      "kit",
      "2. Brand kit",
      brand.current_kit_version > 0 && brand.guessed_count > 0 ? (
        <span className="badge warn">{brand.guessed_count}</span>
      ) : null,
    ],
    ["generate", "3. Generate"],
    ["ads", "4. Ads", brand.ad_count ? <span className="badge">{brand.ad_count}</span> : null],
  ];

  const remove = async () => {
    if (!confirm(`Delete ${brand.name} and all its kits, content, and ads? This cannot be undone.`)) return;
    try {
      await api.del(`/brands/${brand.id}`);
      navigate("/brands");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <div className="page-head">
        <div className="grow">
          <a href="#/brands" className="crumb">
            ← All brands
          </a>
          <h1 className="truncate">{brand.name}</h1>
          <p className="muted small sub truncate">
            {INDUSTRIES.find(([k]) => k === brand.industry)?.[1]}
            {brand.website_url ? ` · ${brand.website_url}` : ""}
            {brand.current_kit_version ? ` · kit v${brand.current_kit_version}` : ""}
          </p>
        </div>
        {user.role === "Owner" && (
          <button className="btn danger small" onClick={remove}>
            Delete brand
          </button>
        )}
      </div>
      <nav className="tabs">
        {tabs.map(([key, label, extra]) => (
          <a key={key} href={`#/brands/${brand.id}/${key}`} className={current === key ? "active" : ""}>
            {label}
            {extra}
          </a>
        ))}
      </nav>
      {current === "setup" && <SetupTab brand={brand} user={user} onChange={reload} />}
      {current === "kit" && <KitTab brand={brand} user={user} onChange={reload} />}
      {current === "generate" && <GenerateTab brand={brand} user={user} />}
      {current === "ads" && <AdsTab brand={brand} user={user} onChange={reload} />}
    </div>
  );
}

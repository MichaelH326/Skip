import type { Ad, Kit } from "../types";

function str(v: unknown): string {
  return Array.isArray(v) ? v.join(" ") : typeof v === "string" ? v : "";
}

function hostOf(url: string | null): string {
  if (!url) return "example.com";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Readable text color for a background. */
function onColor(hex: string): string {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#111" : "#fff";
}

export default function AdPreview({ ad, kit, websiteUrl }: { ad: Ad; kit: Kit | null; websiteUrl: string | null }) {
  const c = ad.content;
  const f = c.fields;
  const name = kit?.name || "Brand";
  const primary = kit?.colors.find((x) => x.role === "primary")?.hex || kit?.colors[0]?.hex || "#1F3A5F";
  const accent = kit?.colors.find((x) => x.role === "accent")?.hex || kit?.colors[1]?.hex || primary;
  const themeColor = kit?.platform_themes[ad.platform]?.colors?.[0] || primary;
  const host = hostOf(websiteUrl);
  const tags = c.hashtags.length ? <span className="mock-tags"> {c.hashtags.join(" ")}</span> : null;
  const avatar = (
    <div className="mock-avatar" style={{ background: themeColor, color: onColor(themeColor) }}>
      {name.slice(0, 1).toUpperCase()}
    </div>
  );
  const image = (tall = false, overlay?: string) => (
    <div
      className={`mock-image ${tall ? "story" : ""}`}
      style={{ background: `linear-gradient(135deg, ${themeColor}, ${accent})`, color: onColor(themeColor) }}
      title="Image direction"
    >
      {overlay ? <strong style={{ fontSize: 16 }}>{overlay}</strong> : c.image_direction || "Image"}
    </div>
  );

  switch (ad.format) {
    case "facebook_feed":
      return (
        <div className="mock">
          <div className="mock-head">
            {avatar}
            <div>
              <div className="mock-name">{name}</div>
              <div className="mock-sub">Sponsored</div>
            </div>
          </div>
          <div className="mock-body">
            {str(f.primary_text)}
            {tags}
          </div>
          {image()}
          <div className="mock-foot">
            <div className="t">
              <div className="d">{host.toUpperCase()}</div>
              <div className="h">{str(f.headline)}</div>
              <div className="d">{str(f.description)}</div>
            </div>
            <span className="mock-cta">{c.cta || "Learn more"}</span>
          </div>
        </div>
      );
    case "instagram_feed":
      return (
        <div className="mock">
          <div className="mock-head">
            {avatar}
            <div>
              <div className="mock-name">{name.toLowerCase().replace(/\s+/g, "")}</div>
              <div className="mock-sub">Sponsored</div>
            </div>
          </div>
          {image()}
          <div className="mock-foot" style={{ background: themeColor, color: onColor(themeColor) }}>
            <div className="t h">{c.cta || "Learn more"}</div>›
          </div>
          <div className="mock-body" style={{ paddingTop: 10 }}>
            <strong>{name.toLowerCase().replace(/\s+/g, "")}</strong> {str(f.caption)}
            {tags}
          </div>
        </div>
      );
    case "instagram_story":
      return (
        <div className="mock">
          <div style={{ position: "relative" }}>
            {image(true, str(f.primary_text))}
            <div style={{ position: "absolute", top: 10, left: 10, display: "flex", gap: 6, alignItems: "center",
              color: onColor(themeColor), fontSize: 12, fontWeight: 700 }}>
              {name} · Sponsored
            </div>
            <div style={{ position: "absolute", bottom: 14, left: 0, right: 0, textAlign: "center" }}>
              <span className="mock-cta" style={{ background: "#fff", color: "#111" }}>
                {c.cta || "Learn more"}
              </span>
            </div>
          </div>
        </div>
      );
    case "linkedin_sponsored":
      return (
        <div className="mock">
          <div className="mock-head">
            {avatar}
            <div>
              <div className="mock-name">{name}</div>
              <div className="mock-sub">Promoted</div>
            </div>
          </div>
          <div className="mock-body">
            {str(f.intro_text)}
            {tags}
          </div>
          {image()}
          <div className="mock-foot">
            <div className="t">
              <div className="h">{str(f.headline)}</div>
              <div className="d">{host}</div>
            </div>
            <span className="mock-cta" style={{ border: "1px solid #0a66c2", color: "#0a66c2", background: "#fff" }}>
              {c.cta || "Learn more"}
            </span>
          </div>
        </div>
      );
    case "google_search": {
      const heads = (Array.isArray(f.headlines) ? f.headlines : []).slice(0, 3).join(" | ");
      const descs = (Array.isArray(f.descriptions) ? f.descriptions : []).slice(0, 2).join(" ");
      return (
        <div className="mock google">
          <div className="sponsored">Sponsored</div>
          <div className="url">
            {name} · {host}
          </div>
          <div className="gh">{heads}</div>
          <div className="gd">{descs}</div>
        </div>
      );
    }
    case "google_display":
      return (
        <div className="mock">
          {image()}
          <div className="mock-body" style={{ paddingTop: 10 }}>
            <div className="h" style={{ fontWeight: 700 }}>{str(f.long_headline) || str(f.short_headline)}</div>
            <div className="mock-sub">{str(f.description)}</div>
          </div>
          <div className="mock-foot">
            <div className="t d">{name}</div>
            <span className="mock-cta" style={{ background: themeColor, color: onColor(themeColor) }}>
              {c.cta || "Open"}
            </span>
          </div>
        </div>
      );
    case "x_promoted":
      return (
        <div className="mock x">
          <div className="mock-head">
            {avatar}
            <div>
              <span className="mock-name">{name}</span>{" "}
              <span className="mock-sub">@{name.toLowerCase().replace(/\s+/g, "")} · Ad</span>
            </div>
          </div>
          <div className="mock-body">
            {str(f.post)}
            {tags}
          </div>
          <div style={{ position: "relative" }}>
            {image()}
          </div>
          <div className="mock-body small muted" style={{ marginTop: -6 }}>
            {str(f.card_headline)} · {host}
          </div>
        </div>
      );
    default:
      return (
        <div className="mock">
          <div className="mock-body" style={{ paddingTop: 10 }}>
            {Object.values(f).map(str).join("\n\n")}
          </div>
        </div>
      );
  }
}

export type Role = "Owner" | "Editor" | "Viewer";
export type Platform = "facebook" | "instagram" | "linkedin" | "google" | "x";
export const PLATFORMS: Platform[] = ["facebook", "instagram", "linkedin", "google", "x"];
export const PLATFORM_LABELS: Record<Platform, string> = {
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  google: "Google Ads",
  x: "X",
};

export const INDUSTRIES = [
  ["real_estate", "Real estate"],
  ["credit", "Credit and lending"],
  ["employment", "Employment and hiring"],
  ["restaurant", "Restaurant"],
  ["retail", "Retail"],
  ["local_services", "Local services"],
  ["saas", "Software"],
  ["general", "Other"],
] as const;
export type Industry = (typeof INDUSTRIES)[number][0];

export interface User {
  id: string;
  email: string;
  role: Role;
  workspace_id: string;
  workspace_name: string | null;
}

export interface Brand {
  id: string;
  name: string;
  website_url: string | null;
  industry: Industry;
  current_kit_version: number;
  kit_ready: boolean;
  guessed_count: number;
  source_count: number;
  ad_count: number;
  created_at: string;
}

export interface Job {
  id: string;
  kind: "import" | "kit_build" | "generate";
  status: "queued" | "running" | "done" | "failed";
  progress: string;
  result: Record<string, unknown> | null;
  error: string | null;
  brand_id: string | null;
}

export interface Source {
  id: string;
  type: "website" | "paste";
  platform: Platform | null;
  kind: "bio" | "post" | "page";
  url: string | null;
  text: string;
  owned: boolean;
  meta: { title?: string; colors?: string[]; fonts?: string[] };
}

export interface VoiceDials {
  formal: number;
  playful: number;
  bold: number;
  technical: number;
  warm: number;
}
export interface Fact { claim: string; source_url: string }
export interface Color { hex: string; role: "primary" | "secondary" | "accent" | "background" }
export interface PlatformTheme {
  audience: string;
  voice_shift: string;
  length: string;
  hashtags: string;
  emoji: string;
  cta_style: string;
  colors: string[];
}
export interface Audience {
  name: string;
  who: string;
  goals: string[];
  objections: string[];
  key_message: string;
  best_platforms: string[];
  ctas: string[];
}
export interface Location {
  name: string;
  references: string[];
  phrasing: string;
  seasonal_hooks: string[];
  avoid: string[];
}
export interface Offer { headline: string; proof: string; cta: string; expires_on: string | null }
export interface Example { text: string; platform: string; rating: "good" | "bad" }

export interface Kit {
  name: string;
  core_voice: string;
  voice_dials: VoiceDials;
  always_words: string[];
  never_words: string[];
  facts: Fact[];
  colors: Color[];
  typography: { heading: string; body: string };
  compliance: {
    industry: Industry;
    special_ad_category: boolean;
    required_disclaimers: string[];
    rules: string[];
  };
  platform_themes: Partial<Record<Platform, PlatformTheme>>;
  audiences: Audience[];
  locations: Location[];
  offers: Offer[];
  examples: Example[];
  guessed: Record<string, string>;
}

export interface FieldSpec {
  key: string;
  label: string;
  recommended: number;
  limit: number;
  multi: { min: number; max: number } | null;
  counts_hashtags: boolean;
}
export interface FormatSpec {
  key: string;
  platform: Platform;
  name: string;
  image_direction: string | null;
  max_hashtags: number;
  fields: FieldSpec[];
}

export interface AdContent {
  fields: Record<string, string | string[]>;
  cta: string;
  hashtags: string[];
  image_direction: string;
  angle?: string;
  facts_used?: string[];
}

export interface Flag {
  rule: string;
  label: string;
  severity: "blocking" | "warning";
  field: string | null;
  words: string;
  message: string;
  suggestion: string | null;
  source: "code" | "review";
  overridden: boolean;
  override_reason: string | null;
}

export interface Ad {
  id: string;
  request_id: string;
  platform: Platform;
  format: string;
  audience: string | null;
  location: string | null;
  offer: string | null;
  angle: string | null;
  content: AdContent;
  generated: AdContent;
  status: "draft" | "approved" | "exported" | "superseded";
  flags: Flag[];
  blocking: number;
  edited: boolean;
  parent_ad_id: string | null;
  created_at: string;
}

export interface Metrics {
  ads_generated: number;
  ads_kept: number;
  kept_without_edits_pct: number | null;
  kept_after_light_edits_pct: number | null;
  flags_per_100_ads: number | null;
  llm_cost_usd: number;
  cost_per_ad_usd: number | null;
}

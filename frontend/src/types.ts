export type Project = {
  id: string; name: string; description: string; language: string;
  pacing_profile: string; target_duration_sec: number;
  style_bible: Record<string, string>; created_at: number; updated_at: number;
};
export type CharacterImage = {
  id: string; asset_id: string; url: string; kind: string; prompt: string;
  seed: number | null; parent_id: string | null; created_at: number;
};
export type Variant = {
  id: string; name: string; prompt_delta: string;
  reference_image_id: string | null; reference_url: string | null;
};
export type Voice = { provider: string; voice_id: string; language: string; settings: Record<string, unknown>; reference_audio_id?: string | null; reference_url?: string | null };
export type Character = {
  id: string; project_id: string; name: string; name_en: string; role: string; description: string;
  appearance: Record<string, string>; negative: string; seed: number | null;
  canonical_image_id: string | null; canonical_url: string | null;
  images: CharacterImage[]; variants: Variant[]; voice: Voice | null;
  created_at: number; updated_at: number;
};
export type VoiceCatalogEntry = {
  label: string; language: string;
  voices: { id: string; name: string; gender: string }[];
};

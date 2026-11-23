import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Character, Project, VoiceCatalogEntry } from "./types";

const TABS = [
  { id: "characters", label: "کاراکترها" },
  { id: "script", label: "سناریو" },
  { id: "scenes", label: "صحنه‌ها" },
  { id: "render", label: "رندر" },
  { id: "settings", label: "تنظیمات" },
] as const;

const APPEARANCE_FIELDS: [string, string][] = [
  ["age", "سن"], ["build", "اندام"], ["face", "چهره"], ["hair", "مو"],
  ["beard", "ریش و سبیل"], ["eyes", "چشم"], ["skin", "پوست"],
  ["clothing", "پوشاک"], ["armor", "زره"], ["accessories", "تجهیزات"], ["signature", "نشانهٔ خاص"],
];

export default function App() {
  const initial = (typeof window !== "undefined" && window.location.hash.replace("#", "")) || "characters";
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>(
    (TABS.some((t) => t.id === initial) ? initial : "characters") as (typeof TABS)[number]["id"],
  );
  const [project, setProject] = useState<Project | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");

  async function boot() {
    try {
      const health = await api.health();
      if (!health.image_api?.gateway) setError("سرویس تصویر در دسترس نیست.");
      const list = (await api.projects()).data as Project[];
      let p = list[0];
      if (!p) {
        p = await api.createProject({ name: "شاهنامه — فصل اول", description: "استودیو فیلم‌سازی شاهنامه" });
      }
      setProject(p);
      const cs = (await api.characters(p.id)).data as Character[];
      setCharacters(cs);
      if (cs.length) setSelectedId(cs[0].id);
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  useEffect(() => { boot(); }, []);

  async function refreshCharacters(select?: string) {
    if (!project) return;
    const cs = (await api.characters(project.id)).data as Character[];
    setCharacters(cs);
    if (select) setSelectedId(select);
    else if (!selectedId && cs.length) setSelectedId(cs[0].id);
  }

  const selected = useMemo(
    () => characters.find((c) => c.id === selectedId) || null,
    [characters, selectedId],
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="glyph">❖</span>
          <div>
            <h1>استودیو شاهنامه</h1>
            <p>{project?.name || "…"}</p>
          </div>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "tab active" : "tab"}
              onClick={() => { setTab(t.id); window.location.hash = t.id; }} disabled={!["characters", "script", "scenes", "render", "settings"].includes(t.id)}>
              {t.label}
              {!["characters", "script", "scenes", "render", "settings"].includes(t.id) && <em>به‌زودی</em>}
            </button>
          ))}
        </nav>
      </header>

      {error && <div className="banner error">{error}</div>}
      {message && <div className="banner ok">{message}</div>}

      <main className={tab === "characters" ? "layout" : "layout full"}>
        {tab === "characters" && <aside className="sidebar">
          <div className="sidebar-head">
            <h2>شخصیت‌ها</h2>
            <span className="count">{characters.length}</span>
          </div>
          <NewCharacter projectId={project?.id} onCreated={async (id) => { await refreshCharacters(id); }} />
          <ul className="char-list">
            {characters.map((c) => (
              <li key={c.id} className={c.id === selectedId ? "char-item active" : "char-item"}
                onClick={() => setSelectedId(c.id)}>
                <div className="avatar">
                  {c.canonical_url ? <img src={c.canonical_url} alt="" /> : <span>{c.name.slice(0, 1)}</span>}
                </div>
                <div>
                  <strong>{c.name}</strong>
                  <small>{c.role || "بدون نقش"}</small>
                </div>
              </li>
            ))}
            {!characters.length && <li className="empty">هنوز شخصیتی نساخته‌ای.</li>}
          </ul>
        </aside>}

        <section className="content">
          {tab === "settings" ? <SettingsView />
            : tab === "script" ? <ScriptView projectId={project?.id} />
            : tab === "scenes" ? <ScenesView projectId={project?.id} />
            : tab === "render" ? <RenderView projectId={project?.id} />
            : selected ? (
            <CharacterView key={selected.id} character={selected}
              onRefresh={() => refreshCharacters()}
              onError={setError} onMessage={setMessage} />
          ) : (
            <div className="placeholder">
              <h2>اولین شخصیت را بساز</h2>
              <p>مثلاً «رستم» را توصیف کن، چند پرتره بگیر، یکی را اصل بگذار و بعد لباس و صدایش را تعیین کن.</p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function NewCharacter({ projectId, onCreated }: { projectId?: string; onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [role, setRole] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!projectId || !name.trim()) return;
    setBusy(true);
    try {
      const c = await api.createCharacter(projectId, { name, name_en: nameEn, role, description });
      setName(""); setNameEn(""); setRole(""); setDescription(""); setOpen(false);
      onCreated(c.id);
    } finally { setBusy(false); }
  }

  if (!open) return <button className="btn ghost block" onClick={() => setOpen(true)}>+ شخصیت جدید</button>;
  return (
    <div className="new-char">
      <input placeholder="نام (مثلاً رستم)" value={name} onChange={(e) => setName(e.target.value)} />
      <input placeholder="نام لاتین برای پرامپت (Rostam)" value={nameEn} onChange={(e) => setNameEn(e.target.value)} />
      <input placeholder="نقش (قهرمان، پادشاه، …)" value={role} onChange={(e) => setRole(e.target.value)} />
      <textarea placeholder="توصیف کوتاه" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      <div className="row">
        <button className="btn" disabled={busy || !name.trim()} onClick={submit}>{busy ? "…" : "ساختن"}</button>
        <button className="btn ghost" onClick={() => setOpen(false)}>لغو</button>
      </div>
    </div>
  );
}

function CharacterView({ character, onRefresh, onError, onMessage }: {
  character: Character; onRefresh: () => void;
  onError: (s: string) => void; onMessage: (s: string) => void;
}) {
  const [extra, setExtra] = useState("");
  const [framing, setFraming] = useState("portrait");
  const [count, setCount] = useState(4);
  const [refId, setRefId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [maskTarget, setMaskTarget] = useState<any>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [edit, setEdit] = useState(false);
  const [desc, setDesc] = useState(character.description);
  const [nameEn, setNameEn] = useState(character.name_en || "");
  const [app, setApp] = useState<Record<string, string>>(character.appearance || {});
  const [voiceCatalog, setVoiceCatalog] = useState<Record<string, VoiceCatalogEntry>>({});
  const [voiceProvider, setVoiceProvider] = useState(character.voice?.provider || "avalai");
  const [voiceId, setVoiceId] = useState(character.voice?.voice_id || "");
  const [cloneFile, setCloneFile] = useState<File | null>(null);
  const [cloneText, setCloneText] = useState("");

  useEffect(() => {
    api.voices().then((r) => setVoiceCatalog(r.data)).catch(() => {});
  }, []);

  async function uploadImage(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setUploading(true); onError("");
    try {
      await api.uploadCharacterImage(character.id, f);
      onMessage("عکس آپلود شد"); onRefresh();
    } catch (err: any) { onError(String(err.message || err)); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function generate() {
    setBusy(true); onError("");
    try {
      const res = await api.generate(character.id, {
        count, width: 768, height: 1024, framing,
        extra_prompt: extra, reference_image_id: refId,
      });
      if (res.errors?.length) onError(res.errors[0]);
      onMessage(`ساخته شد: ${res.images?.length || 0} تصویر`);
      setExtra(""); setRefId(null);
      onRefresh();
    } catch (e: any) { onError(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function makeCanonical(imageId: string) {
    await api.canonical(character.id, imageId);
    onMessage("تصویر اصلی ثبت شد");
    onRefresh();
  }

  async function saveProfile() {
    await api.patchCharacter(character.id, { description: desc, name_en: nameEn, appearance: app });
    setEdit(false); onMessage("مشخصات ذخیره شد"); onRefresh();
  }

  async function saveVoice() {
    await api.setVoice(character.id, { provider: voiceProvider, voice_id: voiceId, language: "fa" });
    onMessage("صدا ثبت شد"); onRefresh();
  }

  async function uploadRef(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      await api.uploadVoiceRef(character.id, f);
      onMessage("نمونهٔ صدای مرجع ذخیره شد"); onRefresh();
    } catch (err: any) { onError(String(err.message || err)); }
  }

  async function doClone() {
    if (!cloneFile || cloneText.trim().length < 5) return;
    try {
      const r = await api.cloneVoice(character.id, cloneFile, cloneText);
      setVoiceProvider(r.provider); setVoiceId(r.voice_id);
      onMessage(r.provider === "fish" ? "کلون صدا ساخته شد" : "نمونهٔ صدا برای LTX ذخیره شد");
      setCloneFile(null); setCloneText(""); onRefresh();
    } catch (e: any) { onError("کلون ناموفق: " + String(e.message || e)); }
  }

  async function previewVoice() {
    try {
      const r = await api.ttsPreview({ text: `سلام، من ${character.name} هستم.`, voice: voiceId, language: "fa" });
      const audio = new Audio(`data:audio/${r.format};base64,${r.audio_b64}`);
      await audio.play();
    } catch (e: any) { onError("پیش‌نمایش صدا ناموفق بود: " + String(e.message || e)); }
  }

  return (
    <div className="character">
      <div className="char-head">
        <div>
          <h2>{character.name} {character.role && <span className="role">{character.role}</span>}</h2>
          <p className="muted">{character.description || "بدون توصیف"}</p>
        </div>
        <button className="btn ghost" onClick={() => setEdit(!edit)}>{edit ? "بستن" : "ویرایش مشخصات"}</button>
      </div>

      {edit && (
        <div className="panel">
          <label>نام لاتین (برای پرامپت)</label>
          <input value={nameEn} onChange={(e) => setNameEn(e.target.value)} placeholder="Rostam" />
          <label style={{ marginTop: 10 }}>توصیف</label>
          <textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} />
          <div className="grid-3">
            {APPEARANCE_FIELDS.map(([key, label]) => (
              <div key={key}>
                <label>{label}</label>
                <input value={app[key] || ""} onChange={(e) => setApp({ ...app, [key]: e.target.value })} />
              </div>
            ))}
          </div>
          <button className="btn" onClick={saveProfile}>ذخیره</button>
        </div>
      )}

      <div className="panel generate">
        <div className="gen-row">
          <div>
            <label>قاب‌بندی</label>
            <select value={framing} onChange={(e) => setFraming(e.target.value)}>
              <option value="portrait">پرتره</option>
              <option value="full">تمام‌قد</option>
              <option value="turnaround">برگهٔ چرخش</option>
            </select>
          </div>
          <div>
            <label>تعداد</label>
            <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
              {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div className="grow">
            <label>توضیح/ویرایش (مثلاً: ریش پرپشت اضافه کن، همان چهره بماند)</label>
            <input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="اختیاری" />
          </div>
          <button className="btn primary" disabled={busy} onClick={generate}>
            {busy ? "در حال ساخت…" : refId ? "بازسازی از تصویر مرجع" : "تولید تصویر"}
          </button>
          <button className="btn ghost" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? "…" : "آپلود عکس"}
          </button>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={uploadImage} />
        </div>
        {refId && <p className="hint">تصویر مرجع انتخاب شده — چهره حفظ می‌شود. <button className="link" onClick={() => setRefId(null)}>حذف مرجع</button></p>}
      </div>

      <div className="images">
        {character.images.map((img) => {
          const isCanonical = img.asset_id === character.canonical_image_id;
          return (
            <figure key={img.id} className={isCanonical ? "shot canonical" : "shot"}>
              <img src={img.url} alt="" />
              {isCanonical && <span className="badge">اصلی</span>}
              <figcaption>
                <span>seed {img.seed}</span>
                <div className="row">
                  {!isCanonical && <button className="link" onClick={() => makeCanonical(img.id)}>انتخاب اصلی</button>}
                  <button className="link" onClick={() => { setRefId(img.asset_id); setExtra(""); window.scrollTo({ top: 0, behavior: "smooth" }); }}>ویرایش از این</button>
                  <button className="link" onClick={() => setMaskTarget(img)}>ویرایش ناحیه‌ای</button>
                </div>
              </figcaption>
            </figure>
          );
        })}
        {!character.images.length && <div className="placeholder small">هنوز تصویری ساخته نشده.</div>}
      </div>

      {maskTarget && (
        <MaskEditor character={character} image={maskTarget}
          onClose={() => setMaskTarget(null)}
          onDone={() => { setMaskTarget(null); onRefresh(); onMessage("ویرایش ناحیه‌ای اعمال شد"); }}
          onError={onError} />
      )}

      <div className="two-col">
        <VariantsPanel character={character} onRefresh={onRefresh} onMessage={onMessage} onError={onError} />
        <div className="panel">
          <h3>صدا</h3>
          <div className="grid-2">
            <div>
              <label>سرویس</label>
              <select value={voiceProvider} onChange={(e) => { setVoiceProvider(e.target.value); setVoiceId(""); }}>
                {Object.entries(voiceCatalog).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
            <div>
              <label>صدا</label>
              <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                <option value="">— انتخاب —</option>
                {(voiceCatalog[voiceProvider]?.voices || []).map((v) => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="row">
            <button className="btn" onClick={saveVoice} disabled={!voiceId}>ذخیرهٔ صدا</button>
            <button className="btn ghost" onClick={previewVoice} disabled={!voiceId}>پیش‌نمایش</button>
          </div>
          {(voiceProvider === "ltx" || voiceProvider === "fish") && (
            <div style={{ marginTop: 12 }}>
              <label>نمونهٔ صدای مرجع (۱۰ تا ۳۰ ثانیه) + متنِ همان نمونه</label>
              <input type="file" accept="audio/*" onChange={(e) => setCloneFile(e.target.files?.[0] || null)} />
              <textarea rows={2} style={{ marginTop: 8 }} placeholder="متن دقیق همان فایل صوتی" value={cloneText} onChange={(e) => setCloneText(e.target.value)} />
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn" onClick={doClone} disabled={!cloneFile || cloneText.trim().length < 5}>
                  {voiceProvider === "fish" ? "ساخت کلون صدا" : "ذخیرهٔ مرجع LTX"}
                </button>
                {character.voice?.reference_audio_id && <span className="hint">مرجع ذخیره شده ✓</span>}
              </div>
              {voiceProvider === "fish" && (
                <p className="hint">برای Fish: فایل کوتاه و تمیز، همان متن را دقیق بنویس. بعد از کلون، voice_id ساخته می‌شود.</p>
              )}
            </div>
          )}
          {voiceCatalog[voiceProvider] && !voiceCatalog[voiceProvider].voices.length && (
            <p className="hint">برای این سرویس هنوز voice ثبت نشده (کلون صدا در فاز بعد).</p>
          )}
        </div>
      </div>
    </div>
  );
}

function VariantsPanel({ character, onRefresh, onMessage, onError }: {
  character: Character; onRefresh: () => void;
  onMessage: (s: string) => void; onError: (s: string) => void;
}) {
  const [name, setName] = useState("");
  const [delta, setDelta] = useState("");
  async function add() {
    if (!name.trim()) return;
    try {
      await api.addVariant(character.id, { name, prompt_delta: delta });
      setName(""); setDelta(""); onMessage("لباس/حالت اضافه شد"); onRefresh();
    } catch (e: any) { onError(String(e.message || e)); }
  }
  return (
    <div className="panel">
      <h3>لباس و حالت‌ها</h3>
      <ul className="variants">
        {character.variants.map((v) => (
          <li key={v.id}>
            <div><strong>{v.name}</strong>{v.prompt_delta && <small> — {v.prompt_delta}</small>}</div>
            <button className="link danger" onClick={async () => { await api.deleteVariant(character.id, v.id); onRefresh(); }}>حذف</button>
          </li>
        ))}
        {!character.variants.length && <li className="empty">مثلاً «شلوار آبی، شال مشکی».</li>}
      </ul>
      <div className="row">
        <input placeholder="نام حالت" value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder="توضیح پوشاک" value={delta} onChange={(e) => setDelta(e.target.value)} />
        <button className="btn" onClick={add} disabled={!name.trim()}>افزودن</button>
      </div>
    </div>
  );
}

const SECTIONS: { key: "image" | "video" | "tts" | "llm"; title: string; hint: string; providers: [string, string][] }[] = [
  { key: "image", title: "تولید تصویر", hint: "پرتره‌ها، فریم‌های نگاه و استوری‌بورد", providers: [["flux_gateway", "Flux Gateway (سرور محلی)"], ["openai_images", "OpenAI-compatible Images"]] },
  { key: "video", title: "تولید ویدیو", hint: "LTX-2.5 (سازگار با OpenAI Videos)", providers: [["ltx_openai", "LTX OpenAI-compatible"], ["openai_videos", "OpenAI/Sora-compatible"]] },
  { key: "tts", title: "گفتار", hint: "نریشن و صداگذاری", providers: [["piper", "Piper (محلی)"], ["openai", "OpenAI-compatible TTS"], ["fish", "Fish Audio"], ["ltx", "LTX reference audio"]] },
  { key: "llm", title: "زبان و سناریو", hint: "نوشتن و بازنویسی سناریو", providers: [["openai", "OpenAI-compatible Chat"]] },
];

function SettingsView() {
  const [cfg, setCfg] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState("");

  useEffect(() => { api.settings().then(setCfg).catch((e) => setMsg(String(e))); }, []);
  if (!cfg) return <div className="placeholder">در حال خواندن تنظیمات…</div>;

  function set(key: string, field: string, value: string) {
    setCfg({ ...cfg, [key]: { ...cfg[key], [field]: value } });
  }

  async function save() {
    setSaving(true);
    try {
      const payload: any = {};
      for (const s of SECTIONS) {
        const c = cfg[s.key];
        payload[s.key] = { provider: c.provider, base_url: c.base_url, model: c.model, api_key: c.api_key || "" };
        if (s.key === "tts") payload[s.key].default_voice = c.default_voice || "";
        if (s.key === "image") payload[s.key].edit_base_url = c.edit_base_url || "";
      }
      const res = await api.saveSettings(payload);
      setCfg(res); setMsg("تنظیمات ذخیره شد");
    } catch (e: any) { setMsg("خطا: " + String(e.message || e)); }
    finally { setSaving(false); }
  }

  async function test(key: string) {
    setResult({ ...result, [key]: { pending: true } });
    try {
      const c = cfg[key];
      const r = await api.testSettings({ section: key, config: { provider: c.provider, base_url: c.base_url, model: c.model, api_key: c.api_key || "", default_voice: c.default_voice } });
      setResult({ ...result, [key]: r });
    } catch (e: any) {
      setResult({ ...result, [key]: { ok: false, detail: String(e.message || e) } });
    }
  }

  return (
    <div className="settings">
      <div className="char-head">
        <div>
          <h2>تنظیمات APIها</h2>
          <p className="muted">هر سرویس را می‌توانی عوض کنی؛ تغییرات فوری اعمال می‌شوند. کلیدها ذخیره شده و دوباره نمایش داده نمی‌شوند.</p>
        </div>
        <button className="btn primary" onClick={save} disabled={saving}>{saving ? "…" : "ذخیرهٔ همه"}</button>
      </div>
      {msg && <div className="banner ok">{msg}</div>}
      <div className="settings-grid">
        {SECTIONS.map((s) => {
          const c = cfg[s.key] || {};
          const r = result[s.key];
          return (
            <div className="panel" key={s.key}>
              <h3>{s.title}</h3>
              <p className="hint" style={{ marginTop: -6 }}>{s.hint}</p>
              <label>سرویس</label>
              <select value={c.provider || ""} onChange={(e) => set(s.key, "provider", e.target.value)}>
                {s.providers.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <label style={{ marginTop: 10 }}>آدرس (Base URL)</label>
              <input value={c.base_url || ""} onChange={(e) => set(s.key, "base_url", e.target.value)} dir="ltr" />
              <label style={{ marginTop: 10 }}>مدل</label>
              <input value={c.model || ""} onChange={(e) => set(s.key, "model", e.target.value)} dir="ltr" />
              {s.key === "image" && (<>
                <label style={{ marginTop: 10 }}>آدرس ویرایش ناحیه‌ای (Inpaint)</label>
                <input value={c.edit_base_url || ""} onChange={(e) => set(s.key, "edit_base_url", e.target.value)} dir="ltr" />
              </>)}
              {s.key === "tts" && (<>
                <label style={{ marginTop: 10 }}>صدای پیش‌فرض</label>
                <input value={c.default_voice || ""} onChange={(e) => set(s.key, "default_voice", e.target.value)} dir="ltr" />
              </>)}
              <label style={{ marginTop: 10 }}>کلید API {c.api_key_set && <span className="muted">(ذخیره شده — خالی بگذارید تا عوض نشود)</span>}</label>
              <input type="password" value={c.api_key || ""} placeholder={c.api_key_set ? "••••••••" : "اختیاری"} onChange={(e) => set(s.key, "api_key", e.target.value)} dir="ltr" />
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn" onClick={() => test(s.key)} disabled={r?.pending}>{r?.pending ? "…" : "تست اتصال"}</button>
                {r && !r.pending && (
                  <span className={r.ok ? "test ok" : "test bad"}>
                    {r.ok ? `سالم (${r.ms}ms)` : `خطا: ${String(r.detail || "").slice(0, 90)}`}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ScriptView({ projectId }: { projectId?: string }) {
  const [script, setScript] = useState<any>(null);
  const [scriptList, setScriptList] = useState<any[]>([]);
  const [project, setProject] = useState<any>(null);
  const [profiles, setProfiles] = useState<any[]>([]);
  const [treatment, setTreatment] = useState("");
  const [sceneCount, setSceneCount] = useState(24);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const activeProfile = profiles.find((p: any) => p.id === project?.pacing_profile) || profiles[0] || null;
  const suggestCount = (target: number, profile: any) => {
    if (!profile) return 24;
    const avg = (profile.scene_duration[0] + profile.scene_duration[1]) / 2;
    return Math.max(3, Math.min(40, Math.round((target || 600) / avg)));
  };

  async function loadScript(id: string) {
    const full = await api.getScript(id);
    setScript(full); setTreatment(full.treatment || "");
  }

  async function changeProfile(id: string) {
    if (!project) return;
    const p = await api.patchProject(project.id, { pacing_profile: id });
    setProject(p);
    setSceneCount(suggestCount(p.target_duration_sec || 600, profiles.find((x: any) => x.id === id)));
    setMsg("پروفایل ریتم به‌روز شد");
  }

  async function changeTarget(minutes: number) {
    if (!project) return;
    const sec = Math.max(60, Math.min(7200, Math.round((minutes || 10) * 60)));
    const p = await api.patchProject(project.id, { target_duration_sec: sec });
    setProject(p);
    setSceneCount(suggestCount(sec, activeProfile));
    setMsg("مدت هدف به‌روز شد");
  }

  useEffect(() => {
    (async () => {
      if (!projectId) return;
      try {
        const [listRes, proj, profRes] = await Promise.all([
          api.scripts(projectId), api.project(projectId), api.pacingProfiles(),
        ]);
        setScriptList(listRes.data);
        setProject(proj);
        setProfiles(profRes.data);
        const active = profRes.data.find((p: any) => p.id === proj.pacing_profile) || profRes.data[0];
        setSceneCount(suggestCount(proj.target_duration_sec || 600, active));
        let s = listRes.data[0];
        if (!s) s = await api.createScript(projectId, { title: "سناریوی جدید", treatment: "" });
        await loadScript(s.id);
      } catch (e: any) { setErr(String(e.message || e)); }
    })();
  }, [projectId]);

  if (err) return <div className="banner error">{err}</div>;
  if (!script) return <div className="placeholder">در حال بارگذاری سناریو…</div>;

  const updateScene = (id: string, patch: any) =>
    setScript({ ...script, scenes: script.scenes.map((s: any) => (s.id === id ? { ...s, ...patch } : s)) });

  async function generate() {
    setBusy(true); setErr(""); setMsg("");
    try {
      const s = await api.generateScript(script.id, { treatment, scene_count: sceneCount });
      setScript(s); setMsg(`سناریو با ${s.scenes.length} سکانس ساخته شد`);
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function saveMeta() {
    const s = await api.patchScript(script.id, { treatment, title: script.title, logline: script.logline });
    setScript(s); setMsg("ذخیره شد");
  }

  async function saveScene(sc: any) {
    await api.patchScene(sc.id, {
      heading: sc.heading, location: sc.location, time_of_day: sc.time_of_day,
      summary: sc.summary, action_text: sc.action_text, dialogue: sc.dialogue,
    });
    setMsg(`سکانس ${sc.index} ذخیره شد`);
  }

  async function addScene() {
    await api.addScene(script.id, { heading: "سکانس جدید", location: "", time_of_day: "", summary: "", action_text: "" });
    const s = await api.getScript(script.id); setScript(s);
  }

  async function delScene(id: string) {
    await api.deleteScene(id);
    const s = await api.getScript(script.id); setScript(s);
  }

  function setDialogue(sc: any, lines: any[]) { updateScene(sc.id, { dialogue: lines }); }

  return (
    <div className="script-view">
      <div className="char-head">
        <div>
          <h2>{script.title || "سناریو"}</h2>
          <p className="muted">{script.logline || "طرح کلی را بنویس و بگذار AI سناریو را بسازد."}</p>
          {scriptList.length > 1 && (
            <div className="row" style={{ marginTop: 8 }}>
              <label style={{ margin: 0 }}>فیلم</label>
              <select value={script.id} onChange={(e) => loadScript(e.target.value)}>
                {[...scriptList]
                  .sort((a, b) => (a.meta?.film_no ?? 99) - (b.meta?.film_no ?? 99))
                  .map((s: any) => (
                    <option key={s.id} value={s.id}>
                      {s.meta?.film_no ? `فیلم ${s.meta.film_no} — ${s.title}` : s.title}
                    </option>
                  ))}
              </select>
            </div>
          )}
        </div>
        <button className="btn primary" onClick={generate} disabled={busy || !treatment.trim()}>
          {busy ? "در حال نوشتن…" : "تولید سناریو با AI"}
        </button>
      </div>
      {msg && <div className="banner ok">{msg}</div>}
      {err && <div className="banner error">{err}</div>}

      <div className="panel">
        <div className="grid-2">
          <div>
            <label>پروفایل ریتم/ژانر</label>
            <select value={project?.pacing_profile || ""} onChange={(e) => changeProfile(e.target.value)}
              disabled={!project || !profiles.length}>
              {profiles.map((p: any) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
          <div>
            <label>مدت هدف (دقیقه)</label>
            <input type="number" min={1} max={120} value={Math.round((project?.target_duration_sec || 600) / 60)}
              onChange={(e) => changeTarget(Number(e.target.value))} />
          </div>
        </div>
        {activeProfile && (
          <p className="hint" style={{ marginTop: 8 }}>
            {activeProfile.description} — صحنه {activeProfile.scene_duration[0]}–{activeProfile.scene_duration[1]}s،
            شات {activeProfile.shot_duration[0]}–{activeProfile.shot_duration[1]}s،
            {activeProfile.shots_per_scene[0]}–{activeProfile.shots_per_scene[1]} شات در صحنه؛
            پیشنهاد: {suggestCount(project?.target_duration_sec || 600, activeProfile)} صحنه.
            برای سناریوی جدید اعمال می‌شود.
          </p>
        )}
      </div>

      <div className="panel">
        <div className="grid-2">
          <div>
            <label>عنوان</label>
            <input value={script.title || ""} onChange={(e) => setScript({ ...script, title: e.target.value })} />
          </div>
          <div>
            <label>تعداد سکانس</label>
            <select value={sceneCount} onChange={(e) => setSceneCount(Number(e.target.value))}>
              {Array.from(new Set([5, 8, 10, 12, 15, 18, 20, 22, 24, 26, 28, 30, sceneCount])).sort((a, b) => a - b)
                .map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </div>
        <label style={{ marginTop: 10 }}>طرح کلی / Treatment</label>
        <textarea rows={5} value={treatment} onChange={(e) => setTreatment(e.target.value)}
          placeholder="مثلاً: نبرد رستم و اسفندیار در چند سکانس؛ شروع با چالش، میانه با نبرد و راز سیمرغ، پایان با پیکان گز دو شاخ." />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" onClick={saveMeta}>ذخیرهٔ طرح</button>
          <button className="btn ghost" onClick={async () => { const s = await api.getScript(script.id); setScript(s); }}>بازخوانی</button>
        </div>
      </div>

      <div className="scenes">
        {(script.scenes || []).map((sc: any) => (
          <div className="panel scene-card" key={sc.id}>
            <div className="scene-head">
              <span className="scene-no">{sc.index}</span>
              <input className="scene-title" value={sc.heading || ""} onChange={(e) => updateScene(sc.id, { heading: e.target.value })} />
              <button className="link danger" onClick={() => delScene(sc.id)}>حذف</button>
            </div>
            <div className="grid-3">
              <div><label>مکان</label><input value={sc.location || ""} onChange={(e) => updateScene(sc.id, { location: e.target.value })} /></div>
              <div><label>زمان</label><input value={sc.time_of_day || ""} onChange={(e) => updateScene(sc.id, { time_of_day: e.target.value })} /></div>
              <div><label>بازیگران</label><input value={(sc.style_overrides?.cast || []).join("، ")} onChange={(e) => updateScene(sc.id, { style_overrides: { ...(sc.style_overrides || {}), cast: e.target.value.split(/[،,]/).map((x: string) => x.trim()).filter(Boolean) } })} /></div>
            </div>
            <label style={{ marginTop: 10 }}>خلاصه</label>
            <textarea rows={2} value={sc.summary || ""} onChange={(e) => updateScene(sc.id, { summary: e.target.value })} />
            <label style={{ marginTop: 10 }}>اکشن / توضیح صحنه</label>
            <textarea rows={3} value={sc.action_text || ""} onChange={(e) => updateScene(sc.id, { action_text: e.target.value })} />
            <label style={{ marginTop: 10 }}>دیالوگ‌ها</label>
            {(sc.dialogue || []).map((d: any, i: number) => (
              <div className="row dialogue-row" key={i}>
                <input style={{ maxWidth: 160 }} placeholder="شخصیت" value={d.character || ""} onChange={(e) => { const arr = [...sc.dialogue]; arr[i] = { ...d, character: e.target.value }; setDialogue(sc, arr); }} />
                <input className="grow" placeholder="جمله" value={d.line || ""} onChange={(e) => { const arr = [...sc.dialogue]; arr[i] = { ...d, line: e.target.value }; setDialogue(sc, arr); }} />
                <input style={{ maxWidth: 120 }} placeholder="حس" value={d.emotion || ""} onChange={(e) => { const arr = [...sc.dialogue]; arr[i] = { ...d, emotion: e.target.value }; setDialogue(sc, arr); }} />
                <button className="link danger" onClick={() => setDialogue(sc, sc.dialogue.filter((_: any, j: number) => j !== i))}>×</button>
              </div>
            ))}
            <div className="row" style={{ marginTop: 8 }}>
              <button className="link" onClick={() => setDialogue(sc, [...(sc.dialogue || []), { character: "", line: "", emotion: "" }])}>+ دیالوگ</button>
              <button className="btn" onClick={() => saveScene(sc)}>ذخیرهٔ سکانس</button>
            </div>
          </div>
        ))}
      </div>
      <button className="btn ghost block" onClick={addScene}>+ سکانس جدید</button>
    </div>
  );
}

function ScenesView({ projectId }: { projectId?: string }) {
  const [script, setScript] = useState<any>(null);
  const [scriptList, setScriptList] = useState<any[]>([]);
  const [characters, setCharacters] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr] = useState("");

  async function loadScript(id: string) {
    const full = await api.getScript(id);
    setScript(full);
    setSelected(full.scenes?.length ? full.scenes[0].id : null);
  }

  useEffect(() => {
    (async () => {
      if (!projectId) return;
      try {
        const list = (await api.scripts(projectId)).data;
        setScriptList(list);
        if (list[0]) await loadScript(list[0].id);
        setCharacters((await api.characters(projectId)).data);
      } catch (e: any) { setErr(String(e.message || e)); }
    })();
  }, [projectId]);

  if (err) return <div className="banner error">{err}</div>;
  if (!script) return <div className="placeholder">اول در تب «سناریو» یک سناریو بساز.</div>;

  return (
    <div className="scenes-view">
      <div className="char-head">
        <div>
          <h2>صحنه‌ها — {script.title}</h2>
          <p className="muted">بازیگران را وصل کن، فریم نگاه بساز و بعد انیمیت کن.</p>
          {scriptList.length > 1 && (
            <div className="row" style={{ marginTop: 8 }}>
              <label style={{ margin: 0 }}>فیلم</label>
              <select value={script.id} onChange={(e) => loadScript(e.target.value)}>
                {[...scriptList]
                  .sort((a, b) => (a.meta?.film_no ?? 99) - (b.meta?.film_no ?? 99))
                  .map((s: any) => (
                    <option key={s.id} value={s.id}>
                      {s.meta?.film_no ? `فیلم ${s.meta.film_no} — ${s.title}` : s.title}
                    </option>
                  ))}
              </select>
            </div>
          )}
        </div>
      </div>
      <div className="split">
        <ul className="scene-list">
          {script.scenes.map((s: any) => (
            <li key={s.id} className={s.id === selected ? "scene-item active" : "scene-item"} onClick={() => setSelected(s.id)}>
              <span className="scene-no">{s.index}</span>
              <div><strong>{s.heading || "بدون عنوان"}</strong><small>{s.location} · {s.time_of_day}</small></div>
            </li>
          ))}
        </ul>
        <div>
          {selected ? <SceneDetail sceneId={selected} characters={characters} /> : <div className="placeholder small">سکانسی انتخاب نشده.</div>}
        </div>
      </div>
    </div>
  );
}

function SceneDetail({ sceneId, characters }: { sceneId: string; characters: any[] }) {
  const [sc, setSc] = useState<any>(null);
  const [visual, setVisual] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [audio, setAudio] = useState(true);
  const [pickChar, setPickChar] = useState("");
  const [narration, setNarration] = useState<any>(null);
  const [shots, setShots] = useState<any[]>([]);
  const [renders, setRenders] = useState<Record<string, any>>({});
  const [proposal, setProposal] = useState<any[] | null>(null);
  const [replaceAll, setReplaceAll] = useState(false);
  const [maskShot, setMaskShot] = useState<any>(null);
  const [shotBusy, setShotBusy] = useState("");

  async function load() {
    const d = await api.scene(sceneId);
    setSc(d); setVisual(d.visual_prompt || "");
    const list = d.shots || [];
    setShots(list);
    const map: Record<string, any> = {};
    for (const s of list) if (s.last_render) map[s.id] = s.last_render;
    setRenders(map);
  }
  useEffect(() => { load().catch((e) => setErr(String(e.message || e))); }, [sceneId]);

  const activeIds = Object.values(renders)
    .filter((r: any) => ["queued", "running"].includes(r.status))
    .map((r: any) => r.id).join(",");

  useEffect(() => {
    if (!activeIds) return;
    const t = setInterval(async () => {
      try {
        const ids = activeIds.split(",");
        const upd = await Promise.all(ids.map(async (id) => {
          try { return await api.render(id); } catch { return null; }
        }));
        setRenders((prev) => {
          const next = { ...prev };
          for (const r of upd) if (r) next[r.shot_id] = r;
          return next;
        });
        if (upd.some((r: any) => r && !["queued", "running"].includes(r.status))) await load();
      } catch { /* ignore */ }
    }, 4000);
    return () => clearInterval(t);
  }, [activeIds]);

  if (!sc) return <div className="placeholder small">…</div>;

  async function addCast() {
    if (!pickChar) return;
    setBusy("cast"); setErr("");
    try { await api.addCast(sc.id, { character_id: pickChar }); setPickChar(""); await load(); }
    catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function compile() {
    setBusy("compile"); setErr(""); setMsg("");
    try { const r = await api.compileScene(sc.id); setVisual(r.visual_prompt || ""); setMsg("پرامپت سینمایی ساخته شد"); }
    catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function makeLook() {
    setBusy("look"); setErr("");
    try {
      await api.lookFrame(sc.id, { prompt: visual, width: 1280, height: 720 });
      setMsg("فریم نگاه ساخته شد"); await load();
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function doDub() {
    setBusy("dub"); setErr(""); setMsg("");
    try { const r = await api.dubScene(sc.id); setNarration(r); setMsg(`دوبلهٔ ${r.lines} خط ساخته شد`); }
    catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  function patchShot(id: string, patch: any) {
    setShots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  async function saveShot(shot: any) {
    setShotBusy(shot.id + ":save"); setErr("");
    try {
      await api.upsertShot(sc.id, { index: shot.index, prompt: shot.prompt, seconds: Number(shot.seconds), width: 1280, height: 720, audio });
      await load(); setMsg(`شات ${shot.index} ذخیره شد`);
    } catch (e: any) { setErr(String(e.message || e)); } finally { setShotBusy(""); }
  }

  async function propose() {
    setBusy("propose"); setErr(""); setMsg("");
    try { const r = await api.proposeShots(sc.id, {}); setProposal(r.data || []); setReplaceAll(false); }
    catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  function patchProposal(i: number, patch: any) {
    setProposal((prev) => prev ? prev.map((x, idx) => (idx === i ? { ...x, ...patch } : x)) : prev);
  }

  async function applyProposal() {
    if (!proposal) return;
    if (replaceAll && !confirm("همهٔ شات‌های فعلی و رندرهایشان حذف شوند؟")) return;
    setBusy("apply"); setErr("");
    try {
      const d = await api.applyShots(sc.id, { shots: proposal, replace: replaceAll });
      setSc(d); setShots(d.shots || []); setProposal(null);
      setMsg(`${(d.shots || []).length} شات ذخیره شد`);
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function addShot() {
    setBusy("add"); setErr("");
    try {
      const idx = shots.reduce((m, s) => Math.max(m, s.index), 0) + 1;
      await api.upsertShot(sc.id, { index: idx, seconds: 10, prompt: "" });
      await load();
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function removeShot(shot: any) {
    if (!confirm(`شات ${shot.index} حذف شود؟ رندرهای آن هم حذف می‌شوند.`)) return;
    setShotBusy(shot.id + ":del"); setErr("");
    try { const d = await api.deleteShot(shot.id); setSc(d); setShots(d.shots || []); }
    catch (e: any) { setErr(String(e.message || e)); } finally { setShotBusy(""); }
  }

  async function chainShot(shot: any) {
    setShotBusy(shot.id + ":chain"); setErr(""); setMsg("");
    try {
      await api.chainShot(shot.id); await load();
      setMsg(`فریم اول شات ${shot.index} از فریم آخر شات ${shot.index - 1} ساخته شد`);
    } catch (e: any) { setErr(String(e.message || e)); } finally { setShotBusy(""); }
  }

  async function renderShot(shot: any) {
    setShotBusy(shot.id + ":render"); setErr(""); setMsg("");
    try {
      await api.upsertShot(sc.id, { index: shot.index, prompt: shot.prompt, seconds: Number(shot.seconds), width: 1280, height: 720, audio });
      const r = await api.startRender(shot.id, {});
      setRenders((prev) => ({ ...prev, [shot.id]: r }));
      setMsg(`رندر شات ${shot.index} شروع شد`);
    } catch (e: any) { setErr(String(e.message || e)); } finally { setShotBusy(""); }
  }

  async function cancelShot(shot: any) {
    const r = renders[shot.id];
    if (!r) return;
    try { const x = await api.cancelRender(r.id); setRenders((p) => ({ ...p, [shot.id]: x })); }
    catch (e: any) { setErr(String(e.message || e)); }
  }

  async function applyInpaint(mask: string, prompt: string) {
    if (!maskShot) return;
    await api.inpaintShot(maskShot.id, { mask, prompt, denoise: 0.9 });
    await load();
    await renderShot(maskShot);
  }

  return (
    <div className="scene-detail">
      <div className="char-head">
        <div><h3>{sc.index}. {sc.heading}</h3><p className="muted">{sc.location} · {sc.time_of_day}</p></div>
      </div>
      {msg && <div className="banner ok">{msg}</div>}
      {err && <div className="banner error">{err}</div>}

      <div className="panel">
        <h3>بازیگران این صحنه</h3>
        <div className="row">
          {(sc.cast || []).map((c: any) => (
            <span className="chip" key={c.id}>
              {c.reference_url && <img src={c.reference_url} alt="" />}
              {c.character_name}{c.variant_name ? ` — ${c.variant_name}` : ""}
              <button className="link danger" onClick={async () => { await api.removeCast(sc.id, c.id); await load(); }}>×</button>
            </span>
          ))}
          {(sc.cast || []).length === 0 && <span className="muted">هنوز بازیگری وصل نیست.</span>}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <select value={pickChar} onChange={(e) => setPickChar(e.target.value)} style={{ maxWidth: 260 }}>
            <option value="">— انتخاب کاراکتر —</option>
            {characters.filter((ch) => !(sc.cast || []).some((c: any) => c.character_id === ch.id)).map((ch) => (
              <option key={ch.id} value={ch.id}>{ch.name}</option>
            ))}
          </select>
          <button className="btn" onClick={addCast} disabled={!pickChar || busy === "cast"}>افزودن</button>
        </div>
      </div>

      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>فریم نگاه (Keyframe)</h3>
          <button className="btn" onClick={compile} disabled={busy === "compile"}>
            {busy === "compile" ? "…" : "کامپایل با AI"}
          </button>
        </div>
        <label style={{ marginTop: 10 }}>پرامپت سینمایی (انگلیسی)</label>
        <textarea rows={4} value={visual} onChange={(e) => setVisual(e.target.value)}
          placeholder="اول «کامپایل با AI» را بزن تا از سناریو ساخته شود." dir="ltr" />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" onClick={makeLook} disabled={busy === "look" || !visual.trim()}>
            {busy === "look" ? "در حال ساخت…" : "ساخت فریم نگاه"}
          </button>
          <span className="hint">۱۲۸۰×۷۲۰ · با مرجع چهرهٔ بازیگران</span>
        </div>
        {sc.look_frame_url && (
          <div className="look-wrap">
            <img src={sc.look_frame_url} alt="look frame" />
          </div>
        )}
      </div>

      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>دوبله و صدا</h3>
          <button className="btn" onClick={doDub} disabled={busy === "dub" || !(sc.dialogue || []).length}>
            {busy === "dub" ? "…" : "ساخت دوبلهٔ صحنه"}
          </button>
        </div>
        {(sc.dialogue || []).length === 0 && <p className="hint">این صحنه دیالوگ ندارد.</p>}
        {narration?.url && <audio src={narration.url} controls style={{ width: "100%", marginTop: 10 }} />}
      </div>

      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h3 style={{ margin: 0 }}>شات‌ها</h3>
            <p className="hint" style={{ margin: "4px 0 0" }}>
              فریم اول شات ۱ از فریم نگاه است؛ از شات ۲ به بعد از فریم آخر شات قبلی شروع می‌شود.
            </p>
          </div>
          <div className="row">
            <button className="btn" onClick={propose} disabled={busy === "propose"}>
              {busy === "propose" ? "…" : "پیشنهاد شات با AI"}
            </button>
            <button className="btn ghost" onClick={addShot} disabled={busy === "add"}>+ شات</button>
          </div>
        </div>

        {proposal && (
          <div style={{ marginTop: 12, padding: 12, border: "1px solid rgba(255,255,255,.12)", borderRadius: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
              <strong>پیشنهاد AI — {proposal.length} شات</strong>
              <label className="hint">
                <input type="checkbox" checked={replaceAll} onChange={(e) => setReplaceAll(e.target.checked)} />{" "}
                جایگزینی شات‌های فعلی
              </label>
            </div>
            {proposal.map((it, i) => (
              <div key={i} style={{ marginTop: 10 }}>
                <div className="row">
                  <span className="chip">شات {i + 1} · {it.kind || "medium"}</span>
                  <select value={it.seconds} style={{ maxWidth: 90 }}
                    onChange={(e) => patchProposal(i, { seconds: Number(e.target.value) })}>
                    {[3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 18, 20].map((n) => <option key={n} value={n}>{n}s</option>)}
                  </select>
                </div>
                <textarea rows={3} dir="ltr" value={it.prompt || ""}
                  onChange={(e) => patchProposal(i, { prompt: e.target.value })} style={{ marginTop: 6 }} />
              </div>
            ))}
            <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
              <button className="btn primary" onClick={applyProposal} disabled={busy === "apply"}>
                {busy === "apply" ? "…" : "اعمال پیشنهاد"}
              </button>
              <button className="btn ghost" onClick={() => setProposal(null)}>انصراف</button>
              {replaceAll && <span className="hint">رندرهای شات‌های فعلی حذف می‌شوند.</span>}
            </div>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: 12, marginTop: 12 }}>
          {shots.map((shot) => {
            const r = renders[shot.id];
            const prevRender = shots.find((x) => x.index === shot.index - 1)
              ? renders[shots.find((x) => x.index === shot.index - 1)!.id] : null;
            return (
              <div className="panel" key={shot.id} style={{ margin: 0 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <strong>شات {shot.index}</strong>
                  <span className={`test ${r?.status === "succeeded" ? "ok" : "bad"}`}>{r?.status || shot.status || "draft"}</span>
                </div>
                <textarea rows={4} dir="ltr" value={shot.prompt || ""}
                  onChange={(e) => patchShot(shot.id, { prompt: e.target.value })}
                  placeholder="English motion prompt…" style={{ marginTop: 8 }} />
                <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
                  <div style={{ maxWidth: 100 }}>
                    <label>مدت</label>
                    <select value={shot.seconds} onChange={(e) => patchShot(shot.id, { seconds: Number(e.target.value) })}>
                      {[3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 18, 20].map((n) => <option key={n} value={n}>{n}s</option>)}
                    </select>
                  </div>
                  <button className="link" onClick={() => saveShot(shot)} disabled={shotBusy === shot.id + ":save"}>ذخیره</button>
                  <button className="link danger" onClick={() => removeShot(shot)} disabled={shotBusy === shot.id + ":del"}>حذف</button>
                </div>
                <div style={{ marginTop: 10 }}>
                  <label>فریم اول</label>
                  {shot.first_frame_url
                    ? <div className="look-wrap" style={{ marginTop: 6 }}><img src={shot.first_frame_url} alt="" /></div>
                    : <p className="hint">{shot.index === 1 ? "با ساخت فریم نگاه صحنه ساخته می‌شود." : "هنوز فریمی ندارد؛ با پیوستگی ساخته می‌شود."}</p>}
                  <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
                    {shot.index > 1 && (
                      <button className="btn ghost" onClick={() => chainShot(shot)} disabled={shotBusy === shot.id + ":chain"}>
                        {shotBusy === shot.id + ":chain" ? "…" : "پیوستگی از شات قبل"}
                      </button>
                    )}
                    {shot.first_frame_url && shot.index > 1 && (
                      <button className="btn ghost" onClick={() => setMaskShot(shot)}>ویرایش ناحیه‌ای</button>
                    )}
                    {shot.first_frame_manual && <span className="chip">فریم دستی</span>}
                    {shot.index > 1 && prevRender?.status === "succeeded" && !shot.first_frame_manual && !shot.first_frame_url && (
                      <span className="hint">آمادهٔ پیوستگی خودکار</span>
                    )}
                  </div>
                </div>
                <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
                  <button className="btn primary" onClick={() => renderShot(shot)}
                    disabled={shotBusy === shot.id + ":render" || (shot.index === 1 && !sc.look_frame_url)}>
                    {shotBusy === shot.id + ":render" ? "…" : "ساخت ویدیو"}
                  </button>
                  {r && ["queued", "running"].includes(r.status) && (
                    <button className="link danger" onClick={() => cancelShot(shot)}>لغو</button>
                  )}
                </div>
                {r?.status === "failed" && r.error && <p className="hint" style={{ color: "#f0b4b4" }}>{r.error}</p>}
                {r?.video_url && <video src={r.video_url} controls playsInline style={{ width: "100%", borderRadius: 10, marginTop: 10 }} />}
              </div>
            );
          })}
          {!shots.length && <p className="placeholder small">هنوز شاتی برای این صحنه ساخته نشده؛ اول «پیشنهاد شات با AI» را بزن.</p>}
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          صدا: {audio ? "با صدا" : "بدون صدا"} —{" "}
          <button className="link" onClick={() => setAudio(!audio)}>تغییر</button>
        </p>
      </div>

      {maskShot && (
        <MaskEditor
          image={{ url: maskShot.first_frame_url }}
          title={`ویرایش ناحیه‌ای فریم اول شات ${maskShot.index}`}
          onClose={() => setMaskShot(null)}
          onDone={() => setMaskShot(null)}
          onError={setErr}
          onApply={applyInpaint}
        />
      )}
    </div>
  );
}

function RenderView({ projectId }: { projectId?: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [final, setFinal] = useState<any>(null);
  const [exported, setExported] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [scripts, setScripts] = useState<any[]>([]);
  const [scriptId, setScriptId] = useState("");
  useEffect(() => {
    if (!projectId) return;
    api.scripts(projectId).then((r) => {
      const list = [...(r.data || [])].sort((a, b) => ((a.meta?.film_no ?? 0) - (b.meta?.film_no ?? 0)));
      setScripts(list);
      if (!scriptId && list.length) setScriptId(list[list.length - 1].id);
    }).catch((e) => setErr(String(e.message || e)));
  }, [projectId]);
  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const list = (await api.renders()).data;
        if (!alive) return;
        const next = await Promise.all(list.map(async (r: any) => {
          if (["queued", "running"].includes(r.status)) {
            try { return await api.render(r.id); } catch { return r; }
          }
          return r;
        }));
        if (alive) setRows(next);
      } catch (e: any) { if (alive) setErr(String(e.message || e)); }
    }
    tick();
    const t = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  return (
    <div>
      <div className="char-head">
        <div><h2>رندرها</h2><p className="muted">همهٔ ویدیوهای ساخته‌شده و در صف.</p></div>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ maxWidth: 260 }}>
            <label>فیلم</label>
            <select value={scriptId} onChange={(e) => setScriptId(e.target.value)}>
              {scripts.map((s: any, i: number) => (
                <option key={s.id} value={s.id}>{`فیلم ${s.meta?.film_no ?? i + 1} — ${s.title}`}</option>
              ))}
            </select>
          </div>
          <button className="btn primary" disabled={busy || !projectId || !scriptId} onClick={async () => {
            setBusy(true); setErr("");
            try { setFinal(await api.finalCut(projectId!, { script_id: scriptId })); }
            catch (e: any) { setErr(String(e.message || e)); }
            finally { setBusy(false); }
          }}>{busy ? "در حال تدوین…" : "تدوین نهایی صحنه‌ها"}</button>
        </div>
      </div>
      <div className="panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div><strong>نسخهٔ کامل با دوبله و زیرنویس</strong><p className="hint" style={{ margin: "4px 0 0" }}>دیالوگ‌ها با صدای کاراکترها خوانده و روی ویدیو میکس می‌شوند؛ SRT هم ساخته می‌شود.</p></div>
        <button className="btn primary" disabled={busy || !projectId || !scriptId} onClick={async () => {
          setBusy(true); setErr("");
          try { setExported(await api.exportAV(projectId!, { script_id: scriptId })); }
          catch (e: any) { setErr(String(e.message || e)); }
          finally { setBusy(false); }
        }}>{busy ? "…" : "تدوین با صدا و زیرنویس"}</button>
      </div>
      {exported && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>نسخهٔ نهایی (با صدا)</strong>
            <div className="row">
              <a className="link" href={exported.video_url} download>دانلود ویدیو</a>
              {exported.srt_url && <a className="link" href={exported.srt_url} download>دانلود زیرنویس</a>}
            </div>
          </div>
          <video src={exported.video_url} controls playsInline style={{ width: "100%", borderRadius: 12, marginTop: 8 }} />
        </div>
      )}
      {final && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>نسخهٔ نهایی — صحنه‌های {final.scenes?.join("، ")}</strong>
            <a className="link" href={final.url} download>دانلود</a>
          </div>
          <video src={final.url} controls playsInline style={{ width: "100%", borderRadius: 12, marginTop: 8 }} />
        </div>
      )}
      {err && <div className="banner error">{err}</div>}
      <div className="renders-grid">
        {rows.map((r) => (
          <div className="panel render-card" key={r.id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{r.scene_index ? `${r.scene_index}. ` : ""}{r.scene_heading || "شات"}</strong>
              <span className={`test ${r.status === "succeeded" ? "ok" : "bad"}`}>{r.status}</span>
            </div>
            <p className="hint">{r.params?.size} · {r.params?.seconds}s · {r.params?.mode} {r.params?.audio ? "· صدا" : ""}</p>
            {r.video_url ? <video src={r.video_url} controls playsInline /> : <div className="video-placeholder">{["queued","running"].includes(r.status) ? "در حال ساخت…" : "بدون ویدیو"}</div>}
          </div>
        ))}
        {!rows.length && <div className="placeholder small">هنوز رندی نیست.</div>}
      </div>
    </div>
  );
}

function MaskEditor({ character, image, onClose, onDone, onError, onApply, title }: {
  character?: Character; image: any; onClose: () => void; onDone: () => void; onError: (s: string) => void;
  onApply?: (mask: string, prompt: string) => Promise<void>; title?: string;
}) {
  const viewRef = useRef<HTMLCanvasElement | null>(null);
  const maskRef = useRef<HTMLCanvasElement | null>(null);
  const drawing = useRef(false);
  const [brush, setBrush] = useState(30);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth, h = img.naturalHeight;
      const mc = maskRef.current!; mc.width = w; mc.height = h;
      const mctx = mc.getContext("2d")!;
      mctx.fillStyle = "#000"; mctx.fillRect(0, 0, w, h);
      const vc = viewRef.current!; vc.width = w; vc.height = h;
      vc.getContext("2d")!.clearRect(0, 0, w, h);
    };
    img.src = image.url;
  }, [image.url]);

  function point(e: React.PointerEvent) {
    const c = viewRef.current!;
    const r = c.getBoundingClientRect();
    return {
      x: (e.clientX - r.left) * (c.width / r.width),
      y: (e.clientY - r.top) * (c.height / r.height),
      k: c.width / r.width,
    };
  }

  function paint(e: React.PointerEvent) {
    if (!drawing.current || !viewRef.current || !maskRef.current) return;
    const { x, y, k } = point(e);
    const r = (brush / 2) * k;
    const m = maskRef.current.getContext("2d")!;
    m.fillStyle = "#fff"; m.beginPath(); m.arc(x, y, r, 0, Math.PI * 2); m.fill();
    const v = viewRef.current.getContext("2d")!;
    v.fillStyle = "rgba(214,178,94,0.45)"; v.beginPath(); v.arc(x, y, r, 0, Math.PI * 2); v.fill();
  }

  function clearMask() {
    const mc = maskRef.current!;
    const m = mc.getContext("2d")!;
    m.fillStyle = "#000"; m.fillRect(0, 0, mc.width, mc.height);
    const vc = viewRef.current!;
    vc.getContext("2d")!.clearRect(0, 0, vc.width, vc.height);
  }

  async function apply() {
    if (!prompt.trim()) return;
    setBusy(true);
    try {
      const mask = maskRef.current!.toDataURL("image/png");
      if (onApply) {
        await onApply(mask, prompt);
      } else {
        await api.editCharacter(character!.id, {
          image_asset_id: image.asset_id, mask, prompt, denoise: 0.9,
        });
      }
      onDone();
    } catch (e: any) { onError("ویرایش ناموفق: " + String(e.message || e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="char-head">
          <div><h3>{title || "ویرایش ناحیه‌ای"}</h3><p className="muted">روی ناحیه‌ای که می‌خواهی عوض شود بکش، بعد توضیح بده.</p></div>
          <button className="link" onClick={onClose}>بستن</button>
        </div>
        <div className="mask-stage">
          <img src={image.url} alt="" />
          <canvas ref={viewRef}
            onPointerDown={(e) => { drawing.current = true; (e.target as HTMLElement).setPointerCapture(e.pointerId); paint(e); }}
            onPointerMove={paint}
            onPointerUp={() => { drawing.current = false; }}
            onPointerLeave={() => { drawing.current = false; }}
          />
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <div style={{ maxWidth: 220 }}>
            <label>ضخامت قلم</label>
            <input type="range" min={8} max={120} value={brush} onChange={(e) => setBrush(Number(e.target.value))} />
          </div>
          <button className="btn ghost" onClick={clearMask}>پاک کردن ماسک</button>
        </div>
        <label style={{ marginTop: 10 }}>تغییر مورد نظر (انگلیسی بهتر است)</label>
        <textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. add a thick black beard and long mustache, keep the same face" dir="ltr" />
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" onClick={apply} disabled={busy || !prompt.trim()}>
            {busy ? "در حال ویرایش…" : "اعمال ویرایش"}
          </button>
          <span className="hint">فقط ناحیهٔ رنگ‌شده بازسازی می‌شود.</span>
        </div>
      </div>
    </div>
  );
}

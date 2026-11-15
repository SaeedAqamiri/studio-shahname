import { useEffect, useMemo, useState } from "react";
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
  const [edit, setEdit] = useState(false);
  const [desc, setDesc] = useState(character.description);
  const [nameEn, setNameEn] = useState(character.name_en || "");
  const [app, setApp] = useState<Record<string, string>>(character.appearance || {});
  const [voiceCatalog, setVoiceCatalog] = useState<Record<string, VoiceCatalogEntry>>({});
  const [voiceProvider, setVoiceProvider] = useState(character.voice?.provider || "piper");
  const [voiceId, setVoiceId] = useState(character.voice?.voice_id || "");
  const [cloneFile, setCloneFile] = useState<File | null>(null);
  const [cloneText, setCloneText] = useState("");

  useEffect(() => {
    api.voices().then((r) => setVoiceCatalog(r.data)).catch(() => {});
  }, []);

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
                </div>
              </figcaption>
            </figure>
          );
        })}
        {!character.images.length && <div className="placeholder small">هنوز تصویری ساخته نشده.</div>}
      </div>

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
  const [treatment, setTreatment] = useState("");
  const [sceneCount, setSceneCount] = useState(6);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      if (!projectId) return;
      try {
        const list = (await api.scripts(projectId)).data;
        let s = list[0];
        if (!s) s = await api.createScript(projectId, { title: "سناریوی جدید", treatment: "" });
        const full = await api.getScript(s.id);
        setScript(full); setTreatment(full.treatment || "");
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
            <label>عنوان</label>
            <input value={script.title || ""} onChange={(e) => setScript({ ...script, title: e.target.value })} />
          </div>
          <div>
            <label>تعداد سکانس</label>
            <select value={sceneCount} onChange={(e) => setSceneCount(Number(e.target.value))}>
              {[3, 4, 5, 6, 8, 10, 12].map((n) => <option key={n} value={n}>{n}</option>)}
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
  const [characters, setCharacters] = useState<any[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      if (!projectId) return;
      try {
        const list = (await api.scripts(projectId)).data;
        if (list[0]) {
          const full = await api.getScript(list[0].id);
          setScript(full);
          if (full.scenes?.length) setSelected(full.scenes[0].id);
        }
        setCharacters((await api.characters(projectId)).data);
      } catch (e: any) { setErr(String(e.message || e)); }
    })();
  }, [projectId]);

  if (err) return <div className="banner error">{err}</div>;
  if (!script) return <div className="placeholder">اول در تب «سناریو» یک سناریو بساز.</div>;

  return (
    <div className="scenes-view">
      <div className="char-head">
        <div><h2>صحنه‌ها — {script.title}</h2><p className="muted">بازیگران را وصل کن، فریم نگاه بساز و بعد انیمیت کن.</p></div>
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
  const [seconds, setSeconds] = useState(4);
  const [audio, setAudio] = useState(true);
  const [render, setRender] = useState<any>(null);
  const [pickChar, setPickChar] = useState("");
  const [prevFrame, setPrevFrame] = useState<any>(null);
  const [narration, setNarration] = useState<any>(null);

  async function load() {
    const d = await api.scene(sceneId);
    setSc(d); setVisual(d.visual_prompt || "");
    if (d.shots?.[0]) {
      const rs = (await api.renders()).data.filter((r: any) => r.shot_id === d.shots[0].id);
      setRender(rs[0] || null);
    } else setRender(null);
  }
  useEffect(() => { load().catch((e) => setErr(String(e.message || e))); }, [sceneId]);

  useEffect(() => {
    if (!render || !["queued", "running"].includes(render.status)) return;
    const t = setInterval(async () => {
      const r = await api.render(render.id);
      setRender(r);
      if (["succeeded", "failed", "cancelled"].includes(r.status)) clearInterval(t);
    }, 4000);
    return () => clearInterval(t);
  }, [render?.id, render?.status]);

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

  async function usePrev() {
    setBusy("prev"); setErr(""); setMsg("");
    try {
      const pf = await api.prevFrame(sc.id);
      setPrevFrame(pf);
      setMsg(`فریم آخر صحنهٔ ${pf.from_scene_index} برداشته شد — ویدیو از همان ادامه پیدا می‌کند.`);
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function doDub() {
    setBusy("dub"); setErr(""); setMsg("");
    try { const r = await api.dubScene(sc.id); setNarration(r); setMsg(`دوبلهٔ ${r.lines} خط ساخته شد`); }
    catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
  }

  async function doRender() {
    setBusy("render"); setErr(""); setMsg("");
    try {
      const shot = await api.upsertShot(sc.id, { prompt: visual, width: 1280, height: 720, seconds, audio,
        first_frame_asset_id: prevFrame?.asset_id || null });
      const r = await api.startRender(shot.id, {});
      setRender(r); setMsg("رندر شروع شد");
    } catch (e: any) { setErr(String(e.message || e)); } finally { setBusy(""); }
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
        <h3>انیمیت (LTX-2.5)</h3>
        {sc.prev_scene_id && (
          <div className="row" style={{ marginBottom: 10 }}>
            <button className="btn ghost" onClick={usePrev} disabled={busy === "prev"}>
              {busy === "prev" ? "…" : "پیوستگی از صحنهٔ قبل"}
            </button>
            {prevFrame && <span className="chip">ادامه از صحنهٔ {prevFrame.from_scene_index} <img src={prevFrame.url} alt="" /></span>}
          </div>
        )}
        <div className="gen-row">
          <div><label>مدت</label>
            <select value={seconds} onChange={(e) => setSeconds(Number(e.target.value))}>
              {[2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} ثانیه</option>)}
            </select>
          </div>
          <div><label>صدا</label>
            <select value={audio ? "1" : "0"} onChange={(e) => setAudio(e.target.value === "1")}>
              <option value="1">با صدا</option><option value="0">بدون صدا</option>
            </select>
          </div>
          <button className="btn primary" onClick={doRender} disabled={busy === "render" || !sc.look_frame_url}>
            {busy === "render" ? "…" : "ساخت ویدیو (i2v)"}
          </button>
        </div>
        {!sc.look_frame_url && <p className="hint">اول فریم نگاه را بساز؛ ویدیو از همان شروع می‌شود.</p>}
        {render && (
          <div className="render-box">
            <div className="row"><span className={`test ${render.status === "succeeded" ? "ok" : "bad"}`}>{render.status}</span>
              {["queued", "running"].includes(render.status) && <button className="link danger" onClick={async () => setRender(await api.cancelRender(render.id))}>لغو</button>}
            </div>
            {render.video_url && <video src={render.video_url} controls playsInline />}
            {render.error && <p className="hint">{render.error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

function RenderView({ projectId }: { projectId?: string }) {
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [final, setFinal] = useState<any>(null);
  const [exported, setExported] = useState<any>(null);
  const [busy, setBusy] = useState(false);
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
        <button className="btn primary" disabled={busy || !projectId} onClick={async () => {
          setBusy(true); setErr("");
          try { setFinal(await api.finalCut(projectId!, {})); }
          catch (e: any) { setErr(String(e.message || e)); }
          finally { setBusy(false); }
        }}>{busy ? "در حال تدوین…" : "تدوین نهایی صحنه‌ها"}</button>
      </div>
      <div className="panel" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div><strong>نسخهٔ کامل با دوبله و زیرنویس</strong><p className="hint" style={{ margin: "4px 0 0" }}>دیالوگ‌ها با صدای کاراکترها خوانده و روی ویدیو میکس می‌شوند؛ SRT هم ساخته می‌شود.</p></div>
        <button className="btn primary" disabled={busy || !projectId} onClick={async () => {
          setBusy(true); setErr("");
          try { setExported(await api.exportAV(projectId!, {})); }
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

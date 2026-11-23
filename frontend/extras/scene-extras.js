/* Shahnameh Studio — scene prompts (separate keyframe / video) + character name.
 * - Character header shows the English prompt name.
 * - Scene keyframe panel gets:
 *     Persian description
 *     Flux keyframe prompt  (still image)
 *     LTX-2.5 video prompt  (motion, chronological, camera)
 *   with an AI rewrite button and auto-save.
 * Version: 2026-11-20
 */
(() => {
  const VERSION = "20261120-5";
  if (window.__shahnamehSceneExtras === VERSION) return;
  window.__shahnamehSceneExtras = VERSION;

  const CSS = `
  #nf-fa-wrap{margin-top:12px}
  #nf-fa-wrap textarea{line-height:1.85;min-height:82px}
  #nf-fa-wrap .nf-actions{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap}
  #nf-tr-msg{font-size:12px}
  #nf-tr-msg.err{color:#f0b4b4}
  #nf-tr-msg.ok{color:#9fd9d3}
  #nf-fa-wrap .nf-two{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
  #nf-fa-wrap .nf-tip{font-size:11px;margin:4px 0 0}
  #nf-fa-wrap .nf-tag{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:999px;
    border:1px solid var(--line,#2a3039);color:var(--muted,#969da6);margin-inline-start:6px;vertical-align:middle}
  .nf-en{color:var(--gold2,#f0d48a);font-family:inherit;letter-spacing:.2px}
  @media (max-width:900px){#nf-fa-wrap .nf-two{grid-template-columns:1fr}}
  #nf-look-edit{margin-top:8px}
  #nf-inpaint .modal{width:min(980px,100%)}
  #nf-inpaint .mask-stage{max-width:100%}
  `;
  const style = document.createElement("style");
  style.id = "nf-scene-style";
  style.textContent = CSS;
  document.head.appendChild(style);

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

  async function api(path, opts) {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...(opts || {}) });
    if (!r.ok) {
      let d = "";
      try { d = await r.text(); } catch { /* ignore */ }
      throw new Error(d || `${r.status} ${r.statusText}`);
    }
    return r.json();
  }

  let projectId = null;
  let scriptFallback = null;
  let charCache = null;
  let charCacheAt = 0;
  let lastCharName = null;

  async function getProjectId() {
    if (projectId) return projectId;
    const p = (await api("/api/projects")).data?.[0];
    projectId = p?.id || null;
    return projectId;
  }

  async function getScriptId() {
    const sel = document.querySelector(".scenes-view select");
    if (sel && sel.value) return sel.value;
    if (scriptFallback) return scriptFallback;
    const pid = await getProjectId();
    if (!pid) return null;
    const list = (await api(`/api/projects/${pid}/scripts`)).data || [];
    scriptFallback = list[0]?.id || null;
    return scriptFallback;
  }

  function sceneIndex() {
    const no = document.querySelector(".scene-item.active .scene-no");
    if (no) {
      const n = parseInt(no.textContent || "", 10);
      if (!Number.isNaN(n)) return n;
    }
    const h3 = document.querySelector(".scene-detail .char-head h3");
    const m = (h3?.textContent || "").match(/^\s*(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  }

  function keyframePanel() {
    return [...document.querySelectorAll(".scene-detail .panel")]
      .find((p) => (p.querySelector("h3")?.textContent || "").includes("فریم نگاه")) || null;
  }

  let cur = null;          // {key, scriptId, index, scene}
  let pollTimer = null;
  let saveTimer = null;
  let busy = false;
  let lookOverride = null;  // {sceneId, assetId, url}
  const dirty = new Set();

  function setNativeValue(el, value) {
    if (!el || el.value === value) return;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
    if (setter) setter.call(el, value); else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function faDefault(sc) {
    const ov = sc?.style_overrides || {};
    if (ov.visual_prompt_fa) return ov.visual_prompt_fa;
    return [sc?.summary, sc?.action_text].filter(Boolean).join("\n");
  }

  function ensureUI() {
    const panel = keyframePanel();
    if (!panel) return null;
    const candidates = [...panel.querySelectorAll("textarea")].filter((t) => !t.closest("#nf-fa-wrap"));
    const reactTa = candidates.find((t) => /پرامپت/.test(t.previousElementSibling?.textContent || "")) || candidates[0];
    if (!reactTa) return null;
    const reactLabel = reactTa.previousElementSibling && reactTa.previousElementSibling.tagName === "LABEL"
      ? reactTa.previousElementSibling : null;
    // The original single prompt box is replaced by our two explicit boxes.
    reactTa.style.display = "none";
    if (reactLabel) reactLabel.style.display = "none";

    let wrap = panel.querySelector("#nf-fa-wrap");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = "nf-fa-wrap";
      wrap.innerHTML = `
        <label class="nf-label">توصیف صحنه (فارسی)</label>
        <textarea id="nf-fa" rows="3" dir="rtl"
          placeholder="صحنه را فارسی بنویس: مکان، زمان، کنش، حال‌وهوا و حرکت دوربین."></textarea>
        <div class="nf-actions">
          <button class="btn" type="button" id="nf-translate">ساخت هر دو پرامپت انگلیسی با AI</button>
          <span id="nf-tr-msg" class="hint"></span>
        </div>
        <div class="nf-two">
          <div>
            <label class="nf-label">پرامپت فریم اول — Flux <span class="nf-tag">عکس ثابت</span></label>
            <textarea id="nf-key" rows="4" dir="ltr"
              placeholder="Frozen cinematic frame: shot size, subject, wardrobe, environment, lens, lighting..."></textarea>
            <p class="hint nf-tip">ترکیب، نور، لنز و جزئیات ظاهری؛ بدون حرکت دوربین.</p>
          </div>
          <div>
            <label class="nf-label">پرامپت ویدیو — LTX-2.5 <span class="nf-tag">حرکت و دوربین</span></label>
            <textarea id="nf-vid" rows="4" dir="ltr"
              placeholder="Start with the main action: ..."></textarea>
            <p class="hint nf-tip">با کنش اصلی شروع می‌شود؛ حرکت پیوسته، یک حرکت دوربین، بدون کات/دیالوگ.</p>
          </div>
        </div>`;
      panel.insertBefore(wrap, reactLabel || reactTa);
      wrap.querySelector("#nf-translate").addEventListener("click", () => doTranslate("both"));
      wrap.addEventListener("input", (e) => {
        const el = e.target;
        if (!el || el.tagName !== "TEXTAREA") return;
        const id = el.id.replace("nf-", "");
        dirty.add(id);
        if (id === "key") setNativeValue(reactTa, el.value);
        scheduleSave();
      });
      const btns = [...panel.querySelectorAll("button")];
      bindGuard(btns.find((b) => (b.textContent || "").includes("ساخت فریم نگاه")), "key", reactTa);
      bindGuard(btns.find((b) => (b.textContent || "").includes("ساخت ویدیو")), "video", reactTa);
      const compileBtn = btns.find((b) => (b.textContent || "").includes("کامپایل"));
      if (compileBtn) compileBtn.addEventListener("click", () => waitForCompile(compileBtn));
    }
    ensureLookEditButton(panel);
    return { panel, reactTa, wrap };
  }

  function collect(ui) {
    const wrap = ui?.wrap || keyframePanel()?.querySelector("#nf-fa-wrap");
    if (!wrap) return { fa: "", key: "", vid: "" };
    return {
      fa: (wrap.querySelector("#nf-fa")?.value || "").trim(),
      key: (wrap.querySelector("#nf-key")?.value || "").trim(),
      vid: (wrap.querySelector("#nf-vid")?.value || "").trim(),
    };
  }

  function setMsg(text, kind) {
    const msg = keyframePanel()?.querySelector("#nf-tr-msg");
    if (!msg) return;
    msg.className = "hint" + (kind ? " " + kind : "");
    msg.textContent = text || "";
  }

  function updateFields(sc, force) {
    const ui = ensureUI();
    if (!ui || !sc) return;
    if (lookOverride && cur && sc.id === cur.scene.id && sc.look_frame_id &&
        sc.look_frame_id !== lookOverride.assetId) {
      lookOverride = null;  // regenerated on the server
    }
    const ov = sc.style_overrides || {};
    const vals = {
      fa: faDefault(sc),
      key: ov.keyframe_prompt || ov.visual_prompt || "",
      vid: ov.video_prompt || "",
    };
    if (force) dirty.clear();
    for (const [id, val] of Object.entries(vals)) {
      const el = ui.wrap.querySelector(`#nf-${id}`);
      if (el && (force || (!dirty.has(id) && document.activeElement !== el))) el.value = val;
    }
    if (vals.key) setNativeValue(ui.reactTa, vals.key);
    const msg = ui.wrap.querySelector("#nf-tr-msg");
    if (msg && !msg.textContent) {
      msg.textContent = vals.vid ? "" : "پرامپت ویدیو خالی است — دکمهٔ AI را بزن (یا هنگام ساخت ویدیو خودکار ساخته می‌شود).";
    }
  }

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    const sceneId = cur?.scene?.id;
    saveTimer = setTimeout(() => {
      if (cur?.scene?.id === sceneId) savePrompts(false);
    }, 600);
  }

  async function savePrompts(force) {
    if (!cur?.scene?.id) return true;
    if (!force && dirty.size === 0) return true;
    const ui = ensureUI();
    if (!ui) return false;
    const { fa, key, vid } = collect(ui);
    try {
      await api(`/api/scenes/${cur.scene.id}/prompts`, {
        method: "POST",
        body: JSON.stringify({ visual_prompt_fa: fa, keyframe_prompt: key, video_prompt: vid }),
      });
      cur.scene.style_overrides = {
        ...(cur.scene.style_overrides || {}),
        visual_prompt_fa: fa, keyframe_prompt: key, video_prompt: vid, visual_prompt: key,
      };
      dirty.clear();
      return true;
    } catch (e) {
      setMsg("ذخیره نشد: " + String(e.message || e).slice(0, 140), "err");
      return false;
    }
  }

  async function doTranslate(target) {
    target = target || "both";
    if (busy) return false;
    const ui = ensureUI();
    if (!ui || !cur?.scene?.id) { setMsg("صحنه هنوز لود نشده.", "err"); return false; }
    const { fa } = collect(ui);
    if (!fa) { setMsg("اول متن فارسی را بنویس.", "err"); return false; }
    busy = true;
    const btn = ui.wrap.querySelector("#nf-translate");
    if (btn) btn.disabled = true;
    setMsg(target === "video" ? "در حال ساخت پرامپت ویدیو با AI…"
      : target === "keyframe" ? "در حال ساخت پرامپت فریم اول با AI…"
      : "در حال ساخت پرامپت فریم اول و ویدیو با AI…");
    try {
      const res = await api(`/api/scenes/${cur.scene.id}/translate-prompt`, {
        method: "POST",
        body: JSON.stringify({ text: fa, target }),
      });
      ui.wrap.querySelector("#nf-fa").value = fa;
      const ov = { ...(cur.scene.style_overrides || {}), visual_prompt_fa: fa };
      if ((target === "both" || target === "keyframe") && res.keyframe_prompt) {
        ui.wrap.querySelector("#nf-key").value = res.keyframe_prompt;
        setNativeValue(ui.reactTa, res.keyframe_prompt);
        ov.keyframe_prompt = res.keyframe_prompt;
        ov.visual_prompt = res.keyframe_prompt;
        dirty.delete("key");
      }
      if ((target === "both" || target === "video") && res.video_prompt) {
        ui.wrap.querySelector("#nf-vid").value = res.video_prompt;
        ov.video_prompt = res.video_prompt;
        dirty.delete("vid");
      }
      cur.scene.style_overrides = ov;
      dirty.delete("fa");
      setMsg(target === "video" ? "پرامپت ویدیو ساخته و ذخیره شد ✓"
        : target === "keyframe" ? "پرامپت فریم اول ساخته و ذخیره شد ✓"
        : "پرامپت فریم اول و پرامپت ویدیو ساخته و ذخیره شدند ✓", "ok");
      return true;
    } catch (e) {
      setMsg("خطا: " + String(e.message || e).slice(0, 180), "err");
      return false;
    } finally {
      busy = false;
      if (btn) btn.disabled = false;
    }
  }

  async function ensurePrompts(kind, reactTa) {
    const ui = ensureUI();
    if (!ui) return false;
    const { key, vid } = collect(ui);
    if ((kind === "key" && key) || (kind === "video" && vid)) {
      return await savePrompts(true);
    }
    const ok = await doTranslate(kind === "video" ? "video" : "keyframe");
    if (!ok) return false;
    const after = collect(ensureUI() || ui);
    const ready = kind === "key" ? !!after.key : !!after.vid;
    if (ready) setNativeValue(reactTa, after.key || "");
    return ready;
  }

  function bindGuard(btn, kind, reactTa) {
    if (!btn || btn.dataset.nfGuard) return;
    btn.dataset.nfGuard = kind;
    btn.addEventListener("click", async (e) => {
      if (btn.dataset.nfBypass) { delete btn.dataset.nfBypass; return; }
      if (kind === "key") lookOverride = null;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (busy) return;
      const ok = await ensurePrompts(kind, reactTa);
      if (!ok) return;
      btn.dataset.nfBypass = "1";
      btn.click();
    }, true);
  }

  async function refreshSceneFromServer() {
    if (!cur) return null;
    try {
      const full = await api(`/api/scripts/${cur.scriptId}`);
      const sc = (full.scenes || []).find((x) => Number(x.index) === Number(cur.index));
      if (sc) { cur.scene = sc; updateFields(sc, true); return sc; }
    } catch { /* ignore */ }
    return null;
  }

  function waitForCompile(btn) {
    if (pollTimer) clearInterval(pollTimer);
    const started = Date.now();
    let seenBusy = false;
    pollTimer = setInterval(async () => {
      if (Date.now() - started > 90000) { clearInterval(pollTimer); pollTimer = null; return; }
      const busyNow = btn.disabled || (btn.textContent || "").trim() === "…";
      if (busyNow || /در حال/.test(btn.textContent || "")) seenBusy = true;
      if (seenBusy && !busyNow) {
        clearInterval(pollTimer); pollTimer = null;
        const sc = await refreshSceneFromServer();
        const ov = sc?.style_overrides || {};
        setMsg(ov.keyframe_prompt && ov.video_prompt
          ? "پرامپت فارسی، فریم اول و ویدیو ساخته شدند ✓" : "", "ok");
        return;
      }
      if (seenBusy && Date.now() - started > 2500) await refreshSceneFromServer();
    }, 1400);
  }

  async function loadScene(force) {
    const sid = await getScriptId();
    const idx = sceneIndex();
    if (!sid || !idx) return;
    const key = `${sid}:${idx}`;
    if (!force && cur && cur.key === key) { ensureUI(); updateFields(cur.scene, false); return; }
    if (cur && dirty.size) await savePrompts(true);
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    const full = await api(`/api/scripts/${sid}`);
    const sc = (full.scenes || []).find((x) => Number(x.index) === Number(idx));
    if (!sc) return;
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    cur = { key, scriptId: sid, index: idx, scene: sc };
    dirty.clear();
    ensureUI();
    setMsg("");
    updateFields(sc, true);
  }

  function applyLookOverride() {
    if (!lookOverride || !cur || cur.scene.id !== lookOverride.sceneId) return;
    const img = document.querySelector(".scene-detail .look-wrap img");
    if (img && !img.src.includes(lookOverride.assetId)) img.src = lookOverride.url;
  }

  let inpaintEls = null;
  function closeInpaint() { if (inpaintEls) inpaintEls.back.style.display = "none"; }

  function ensureInpaintModal() {
    if (inpaintEls) return inpaintEls;
    const back = document.createElement("div");
    back.id = "nf-inpaint";
    back.className = "modal-backdrop";
    back.style.display = "none";
    back.innerHTML = `
      <div class="modal">
        <div class="char-head">
          <div><h3>ویرایش ناحیه‌ای فریم اول</h3><p class="muted">روی ناحیه‌ای که می‌خواهی عوض شود بکش، بعد توضیح بده.</p></div>
          <button class="link" type="button" id="nf-inpaint-close">بستن</button>
        </div>
        <div class="mask-stage">
          <img id="nf-inpaint-img" alt="" />
          <canvas id="nf-inpaint-mask" style="display:none"></canvas>
          <canvas id="nf-inpaint-view"></canvas>
        </div>
        <div class="row" style="margin-top:12px">
          <div style="max-width:220px">
            <label>ضخامت قلم</label>
            <input id="nf-inpaint-brush" type="range" min="8" max="120" value="40" />
          </div>
          <button class="btn ghost" type="button" id="nf-inpaint-clear">پاک کردن ماسک</button>
        </div>
        <label style="margin-top:10px">تغییر مورد نظر</label>
        <textarea id="nf-inpaint-prompt" rows="2" dir="auto"
          placeholder="مثلاً: ریش پرپشت اضافه کن، همان چهره بماند (انگلیسی بهتر نتیجه می‌دهد)"></textarea>
        <div class="row" style="margin-top:10px">
          <button class="btn primary" type="button" id="nf-inpaint-apply">اعمال ویرایش</button>
          <span class="hint" id="nf-inpaint-msg">فقط ناحیهٔ رنگ‌شده بازسازی می‌شود.</span>
        </div>
      </div>`;
    document.body.appendChild(back);
    const q = (sel) => back.querySelector(sel);
    const els = {
      back, img: q("#nf-inpaint-img"), mask: q("#nf-inpaint-mask"), view: q("#nf-inpaint-view"),
      brush: q("#nf-inpaint-brush"), prompt: q("#nf-inpaint-prompt"),
      apply: q("#nf-inpaint-apply"), msg: q("#nf-inpaint-msg"),
    };
    let drawing = false;
    const size = (w, h) => {
      if (!w || !h) return;
      els.mask.width = w; els.mask.height = h;
      const mc = els.mask.getContext("2d");
      mc.fillStyle = "#000"; mc.fillRect(0, 0, w, h);
      els.view.width = w; els.view.height = h;
      els.view.getContext("2d").clearRect(0, 0, w, h);
    };
    const point = (e) => {
      const r = els.view.getBoundingClientRect();
      return {
        x: (e.clientX - r.left) * (els.view.width / r.width),
        y: (e.clientY - r.top) * (els.view.height / r.height),
        k: els.view.width / r.width,
      };
    };
    const paint = (e) => {
      if (!drawing) return;
      const { x, y, k } = point(e);
      const r = (Number(els.brush.value) / 2) * k;
      const mc = els.mask.getContext("2d");
      mc.fillStyle = "#fff"; mc.beginPath(); mc.arc(x, y, r, 0, Math.PI * 2); mc.fill();
      const vc = els.view.getContext("2d");
      vc.fillStyle = "rgba(214,178,94,0.45)"; vc.beginPath(); vc.arc(x, y, r, 0, Math.PI * 2); vc.fill();
    };
    els.img.addEventListener("load", () => size(els.img.naturalWidth, els.img.naturalHeight));
    els.view.addEventListener("pointerdown", (e) => {
      drawing = true;
      els.view.setPointerCapture(e.pointerId);
      paint(e);
    });
    els.view.addEventListener("pointermove", paint);
    els.view.addEventListener("pointerup", () => { drawing = false; });
    els.view.addEventListener("pointerleave", () => { drawing = false; });
    q("#nf-inpaint-clear").addEventListener("click", () => {
      const mc = els.mask.getContext("2d");
      mc.fillStyle = "#000"; mc.fillRect(0, 0, els.mask.width, els.mask.height);
      els.view.getContext("2d").clearRect(0, 0, els.view.width, els.view.height);
    });
    q("#nf-inpaint-close").addEventListener("click", closeInpaint);
    back.addEventListener("mousedown", (e) => { if (e.target === back) closeInpaint(); });
    els.apply.addEventListener("click", applyInpaint);
    inpaintEls = els;
    return els;
  }

  async function applyInpaint() {
    const els = inpaintEls;
    if (!els || !cur?.scene?.id) return;
    const prompt = els.prompt.value.trim();
    if (!prompt) {
      els.msg.className = "hint err";
      els.msg.textContent = "توضیح تغییر را بنویس.";
      return;
    }
    els.apply.disabled = true;
    els.msg.className = "hint";
    els.msg.textContent = "در حال ویرایش…";
    try {
      const res = await api(`/api/scenes/${cur.scene.id}/look-frame/inpaint`, {
        method: "POST",
        body: JSON.stringify({ mask: els.mask.toDataURL("image/png"), prompt, denoise: 0.9 }),
      });
      cur.scene.look_frame_id = res.look_frame_id;
      lookOverride = { sceneId: cur.scene.id, assetId: res.look_frame_id, url: res.url };
      const pageImg = document.querySelector(".scene-detail .look-wrap img");
      if (pageImg) pageImg.src = res.url + (res.url.includes("?") ? "&" : "?") + "v=" + Date.now();
      setMsg("فریم اول ویرایش شد ✓", "ok");
      els.msg.className = "hint ok";
      els.msg.textContent = "فریم اول ویرایش شد ✓";
      setTimeout(closeInpaint, 700);
    } catch (e) {
      els.msg.className = "hint err";
      els.msg.textContent = "خطا: " + String(e.message || e).slice(0, 180);
    } finally {
      els.apply.disabled = false;
    }
  }

  function ensureLookEditButton(panel) {
    const wrap = panel.querySelector(".look-wrap");
    if (!wrap) return;
    if (panel.querySelector("#nf-look-edit")) return;
    const btn = document.createElement("button");
    btn.id = "nf-look-edit";
    btn.type = "button";
    btn.className = "btn ghost";
    btn.textContent = "ویرایش ناحیه‌ای فریم اول";
    btn.style.marginTop = "8px";
    btn.addEventListener("click", openInpaint);
    wrap.insertAdjacentElement("afterend", btn);
  }

  function openInpaint() {
    if (!cur?.scene?.id) return;
    const pageImg = document.querySelector(".scene-detail .look-wrap img");
    if (!pageImg) return;
    const els = ensureInpaintModal();
    els.prompt.value = "";
    els.msg.className = "hint";
    els.msg.textContent = "فقط ناحیهٔ رنگ‌شده بازسازی می‌شود.";
    els.back.style.display = "grid";
    els.img.src = pageImg.currentSrc || pageImg.src;
    if (els.img.complete && els.img.naturalWidth) {
      els.img.dispatchEvent(new Event("load"));
    }
  }

  async function getCharacters() {
    const pid = await getProjectId();
    if (!pid) return [];
    if (charCache && Date.now() - charCacheAt < 5000) return charCache;
    const list = (await api(`/api/projects/${pid}/characters`)).data || [];
    charCache = list; charCacheAt = Date.now();
    return list;
  }

  async function injectCharacterName() {
    const holder = document.querySelector(".character .char-head > div");
    if (!holder) return;
    const h2 = holder.querySelector("h2");
    if (!h2) return;
    const name = (h2.firstChild?.textContent || "").trim();
    if (!name) return;
    const chars = await getCharacters();
    const ch = chars.find((c) => (c.name || "").trim() === name);
    let el = holder.querySelector("#nf-name-en");
    if (!el) {
      el = document.createElement("p");
      el.id = "nf-name-en";
      el.className = "muted";
      el.style.margin = "6px 0 0";
      el.style.fontSize = "12.5px";
      holder.appendChild(el);
    }
    const html = ch?.name_en
      ? `نام انگلیسی (برای پرامپت): <strong dir="ltr" class="nf-en">${esc(ch.name_en)}</strong>`
      : 'نام انگلیسی (برای پرامپت): <span class="hint">تعیین نشده — از «ویرایش مشخصات» اضافه کنید.</span>';
    if (el.innerHTML !== html) el.innerHTML = html;
    lastCharName = name;
  }

  let scheduled = false;
  function tick() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(async () => {
      scheduled = false;
      try { await injectCharacterName(); } catch { /* ignore */ }
      try { if (document.querySelector(".scene-detail")) { await loadScene(false); applyLookOverride(); } } catch { /* ignore */ }
    });
  }

  const observer = new MutationObserver(tick);
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  setInterval(tick, 2500);
  tick();
})();

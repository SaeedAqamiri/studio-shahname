/* Shahnameh Studio — "New film" UI extension (standalone, no rebuild needed).
 * Adds a visible button in the Script tab header (and a floating fallback on
 * other tabs) that creates a new film/script, assigns the next film_no and
 * optionally generates its scenes with the studio LLM.
 * Version: 2026-11-20
 */
(() => {
  const VERSION = "20261120-3";
  if (window.__shahnamehNewFilm === VERSION) return;
  window.__shahnamehNewFilm = VERSION;

  const CSS = `
  #nf-fab{position:fixed;left:24px;bottom:24px;z-index:10000;background:var(--teal,#3d7f79);color:#fff;
    border:1px solid rgba(255,255,255,.16);border-radius:14px;padding:11px 18px;font:inherit;cursor:pointer;
    box-shadow:0 10px 30px rgba(0,0,0,.4)}
  #nf-fab:hover{filter:brightness(1.08)}
  #nf-modal{position:fixed;inset:0;z-index:10001;display:none;align-items:center;justify-content:center;
    background:rgba(0,0,0,.62);backdrop-filter:blur(3px)}
  #nf-modal.open{display:flex}
  .nf-card{width:min(580px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;
    background:var(--panel,#15181d);color:var(--text,#ece9e2);border:1px solid var(--line,#2a3039);
    border-radius:18px;padding:22px;box-shadow:0 24px 80px rgba(0,0,0,.55);font-family:inherit}
  .nf-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px}
  .nf-head h3{font-size:20px;margin:0;color:var(--gold2,#f0d48a)}
  .nf-x{background:transparent;border:0;color:var(--muted,#969da6);font-size:24px;line-height:1;cursor:pointer;padding:0 4px}
  .nf-hint{color:var(--muted,#969da6);font-size:12.5px;margin:4px 0 16px;line-height:1.8}
  .nf-label{display:block;color:var(--muted,#969da6);font-size:12.5px;margin:12px 0 6px}
  .nf-label span{opacity:.7}
  .nf-input{width:100%;background:var(--bg2,#0f1114);border:1px solid var(--line,#2a3039);
    border-radius:10px;padding:10px 12px;color:var(--text,#ece9e2);outline:none}
  .nf-input:focus{border-color:var(--teal,#3d7f79)}
  textarea.nf-input{resize:vertical;min-height:96px;line-height:1.9}
  .nf-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .nf-check{display:flex;align-items:center;gap:8px;margin-top:14px;font-size:13px;color:var(--text,#ece9e2);cursor:pointer}
  .nf-check input{width:16px;height:16px;accent-color:var(--teal,#3d7f79)}
  .nf-msg{margin-top:12px;font-size:12.5px;line-height:1.9;min-height:0}
  .nf-msg.err{color:#f0b4b4}
  .nf-msg.ok{color:#9fd9d3}
  .nf-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}
  .nf-btn{background:var(--panel2,#1b1f26);border:1px solid var(--line,#2a3039);color:var(--text,#ece9e2);
    border-radius:10px;padding:10px 18px;font:inherit;cursor:pointer}
  .nf-btn:hover:not(:disabled){border-color:var(--teal,#3d7f79)}
  .nf-btn.nf-primary{background:var(--teal,#3d7f79);border-color:transparent;color:#fff}
  .nf-btn:disabled{opacity:.55;cursor:not-allowed}
  @media (max-width:520px){.nf-grid{grid-template-columns:1fr}}
  `;

  const style = document.createElement("style");
  style.id = "nf-style";
  style.textContent = CSS;
  document.head.appendChild(style);

  const fab = document.createElement("button");
  fab.id = "nf-fab";
  fab.type = "button";
  fab.textContent = "＋ فیلم جدید";
  fab.style.display = "none";
  document.body.appendChild(fab);

  const modal = document.createElement("div");
  modal.id = "nf-modal";
  modal.innerHTML = `
    <div class="nf-card" role="dialog" aria-modal="true" aria-labelledby="nf-title">
      <div class="nf-head">
        <h3 id="nf-title">افزودن فیلم جدید</h3>
        <button class="nf-x" type="button" data-nf-close aria-label="بستن">×</button>
      </div>
      <p class="nf-hint" id="nf-hint">یک سناریوی تازه ساخته می‌شود و شمارهٔ فیلم بعدی به آن داده می‌شود.</p>
      <label class="nf-label" for="nf-name">عنوان فیلم</label>
      <input id="nf-name" class="nf-input" placeholder="مثلاً: رستم و اکوان دیو" autocomplete="off" />
      <label class="nf-label" for="nf-treatment">طرح کلی / Treatment <span>(اختیاری)</span></label>
      <textarea id="nf-treatment" class="nf-input" rows="5"
        placeholder="خط داستانی را در چند جمله بنویس؛ اگر تیک «ساخت با AI» بزنید، از همین متن سکانس‌ها ساخته می‌شوند."></textarea>
      <div class="nf-grid">
        <div>
          <label class="nf-label" for="nf-count">تعداد سکانس</label>
          <input id="nf-count" class="nf-input" type="number" min="1" max="30" value="24" />
        </div>
        <div>
          <label class="nf-label" for="nf-tone">لحن</label>
          <input id="nf-tone" class="nf-input" placeholder="epic, cinematic, grounded" autocomplete="off" />
        </div>
      </div>
      <label class="nf-check"><input id="nf-ai" type="checkbox" /> سکانس‌ها را با AI از طرح کلی بساز <span style="opacity:.65">(اختیاری)</span></label>
      <div id="nf-msg" class="nf-msg"></div>
      <div class="nf-actions">
        <button class="nf-btn" type="button" data-nf-close>انصراف</button>
        <button class="nf-btn nf-primary" id="nf-create" type="button">ساخت فیلم</button>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const $ = (sel) => modal.querySelector(sel);
  const nameEl = $("#nf-name");
  const treatmentEl = $("#nf-treatment");
  const countEl = $("#nf-count");
  const toneEl = $("#nf-tone");
  const aiEl = $("#nf-ai");
  const msgEl = $("#nf-msg");
  const hintEl = $("#nf-hint");
  const createBtn = $("#nf-create");
  let busy = false;
  let createdScript = null;

  const setMsg = (text, kind) => {
    msgEl.textContent = text || "";
    msgEl.className = "nf-msg" + (kind ? " " + kind : "");
  };

  async function api(path, opts) {
    const r = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...(opts || {}),
    });
    if (!r.ok) {
      let detail = "";
      try { detail = await r.text(); } catch { /* ignore */ }
      throw new Error(detail || `${r.status} ${r.statusText}`);
    }
    return r.json();
  }

  function open() {
    createdScript = null;
    setMsg("");
    createBtn.textContent = "ساخت فیلم";
    createBtn.disabled = false;
    modal.classList.add("open");
    hintEl.textContent = "یک سناریوی تازه ساخته می‌شود و شمارهٔ فیلم بعدی به آن داده می‌شود.";
    api("/api/projects").then((res) => {
      const p = (res.data || [])[0];
      if (!p) return;
      return api(`/api/projects/${p.id}/scripts`).then((sres) => {
        const n = Math.max(0, ...(sres.data || []).map((s) => Number(s?.meta?.film_no) || 0)) + 1;
        hintEl.textContent = `فیلم شمارهٔ ${n} برای پروژهٔ «${p.name}» ساخته می‌شود.`;
      });
    }).catch(() => {});
    setTimeout(() => nameEl.focus(), 30);
  }

  function close() {
    if (busy) return;
    modal.classList.remove("open");
  }

  async function create() {
    if (busy) return;
    const title = nameEl.value.trim();
    const treatment = treatmentEl.value.trim();
    const count = Math.max(1, Math.min(30, Number(countEl.value) || 24));
    const tone = toneEl.value.trim();
    if (!title) { setMsg("عنوان فیلم را وارد کنید.", "err"); nameEl.focus(); return; }
    if (aiEl.checked && !treatment) {
      setMsg("برای ساخت سکانس‌ها با AI، طرح کلی را بنویسید یا تیک را بردارید.", "err");
      treatmentEl.focus();
      return;
    }

    busy = true;
    createBtn.disabled = true;
    setMsg("در حال ساخت فیلم…");

    try {
      const projects = (await api("/api/projects")).data || [];
      const project = projects[0];
      if (!project) throw new Error("پروژه‌ای یافت نشد.");

      const scripts = (await api(`/api/projects/${project.id}/scripts`)).data || [];
      const filmNo = Math.max(0, ...scripts.map((s) => Number(s?.meta?.film_no) || 0)) + 1;

      const script = await api(`/api/projects/${project.id}/scripts`, {
        method: "POST",
        body: JSON.stringify({ title, treatment, source: "ui" }),
      });
      createdScript = script;

      await api(`/api/scripts/${script.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          meta: {
            film_no: filmNo,
            duration_sec: Number(project.target_duration_sec) || 600,
            scene_count: count,
            source: "ui",
          },
        }),
      });

      if (aiEl.checked) {
        setMsg(`فیلم ${filmNo} ساخته شد؛ در حال نوشتن ${count} سکانس با AI… (ممکن است یک دقیقه طول بکشد)`);
        await api(`/api/scripts/${script.id}/generate`, {
          method: "POST",
          body: JSON.stringify({ treatment, scene_count: count, tone }),
        });
      }

      setMsg(`فیلم ${filmNo} با موفقیت ساخته شد؛ در حال باز کردن…`, "ok");
      window.location.hash = "script";
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      const detail = String(err?.message || err);
      if (createdScript) {
        createBtn.textContent = "باز کردن فیلم";
        createBtn.disabled = false;
        busy = false;
        setMsg("فیلم ساخته شد، اما ساخت سکانس‌ها با AI کامل نشد: " + detail, "err");
      } else {
        createBtn.disabled = false;
        busy = false;
        setMsg("ساخت فیلم ناموفق بود: " + detail, "err");
      }
    }
  }

  createBtn.addEventListener("click", () => {
    if (createdScript && createBtn.textContent === "باز کردن فیلم") {
      window.location.hash = "script";
      window.location.reload();
      return;
    }
    create();
  });
  modal.querySelectorAll("[data-nf-close]").forEach((b) => b.addEventListener("click", close));
  modal.addEventListener("mousedown", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal.classList.contains("open")) close(); });
  fab.addEventListener("click", open);

  function placeButton() {
    // Show the pill only while the Script tab is mounted; never touch React-managed DOM.
    const onScriptTab = !!document.querySelector(".script-view");
    fab.style.display = onScriptTab ? "block" : "none";
  }

  const observer = new MutationObserver(() => requestAnimationFrame(placeButton));
  observer.observe(document.body, { childList: true, subtree: true });
  setInterval(placeButton, 1200);
  placeButton();
  window.__shahnamehOpenNewFilm = open;
})();

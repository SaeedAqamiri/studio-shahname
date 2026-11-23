# افزودن «فیلم جدید» به UI استودیو

این پوشه یک افزونهٔ مستقل (standalone) به رابط استودیو اضافه می‌کند، بدون نیاز به build دوباره:

- در تب **سناریو**، یک دکمهٔ شناور «＋ فیلم جدید» نمایش داده می‌شود.
- با کلیک، یک فیلم/سناریوی تازه برای پروژه ساخته می‌شود، شمارهٔ بعدی `meta.film_no` به آن داده می‌شود و در لیست فیلم‌ها (همان ۱۱ فیلم فعلی) ظاهر می‌شود.
- اختیاری می‌تواند سکانس‌ها را با AI از «طرح کلی» بسازد.

## فایل‌ها

- `extras/new-film.js` — افزونهٔ «فیلم جدید»
- `extras/scene-extras.js` — افزونهٔ نام انگلیسی کاراکتر + پرامپت فارسی صحنه
- `dist/assets/*.js` — همان فایل‌ها که توسط UI لود می‌شوند
- `dist/index.html` — دو تگ `<script>` به انتهای body اضافه شده است

## افزونهٔ صحنه‌ها و کاراکترها (`scene-extras.js`)

- در صفحهٔ کاراکتر، زیر توضیح، **نام انگلیسی (برای پرامپت)** را نشان می‌دهد (از فیلد `name_en`).
- در صفحهٔ صحنه‌ها، داخل پنل «فریم نگاه»:
  - **توضیح صحنه (فارسی)**
  - **پرامپت فریم اول — Flux** (عکس ثابت: ترکیب، نور، لنز؛ بدون حرکت)
  - **پرامپت ویدیو — LTX-2.5** (حرکت پیوسته، یک حرکت دوربین، بدون کات/دیالوگ)
  - دکمهٔ **«ساخت هر دو پرامپت انگلیسی با AI»** هر دو را از متن فارسی می‌سازد.
  - تکست‌باکس قدیمیِ انگلیسی مخفی می‌شود؛ دکمه‌های «ساخت فریم نگاه» و «ساخت ویدیو» قبل از اجرا پرامپتهای لازم را ذخیره (و در صورت خالی بودن با AI می‌سازند).
  - زیر تصویر فریم نگاه، دکمهٔ **«ویرایش ناحیه‌ای فریم اول»** با ماسک و پرامپت (مثل ویرایش ناحیه‌ای عکس کاراکترها)؛ نتیجه به‌عنوان فریم اول جدید ثبت می‌شود.
- APIهای بک‌اند:
  - `POST /api/scenes/{id}/translate-prompt` با `{"text": "...", "target": "both|keyframe|video"}` → `{"keyframe_prompt", "video_prompt", "english", ...}`
  - `POST /api/scenes/{id}/prompts` برای ذخیرهٔ دستی هر سه فیلد
  - `POST /api/scenes/{id}/look-frame/inpaint` با `{"mask": "data:image/png;base64,...", "prompt": "...", "denoise": 0.9}` → فریم اول جدید
  - `compile` حالا `visual_prompt_fa` + `keyframe_prompt` + `video_prompt` + `negative` + `video_negative` می‌دهد.
  - `visual_prompt` برای سازگاری = `keyframe_prompt` است.
  - در ساخت ویدیو، `upsert_shot` و پایپ‌لاین از `video_prompt` و `video_negative` استفاده می‌کنند؛ look-frame از `keyframe_prompt`.

## بعد از هر build مجدد فرانت‌اند

اگر `frontend/dist` را از نو ساختید (با سورس اصلی)، تگ اسکریپت از `index.html` حذف می‌شود. برای نصب دوباره:

```bash
bash ~/studio/frontend/extras/install.sh
```

یا دستی، این خط را قبل از `</body>` در `dist/index.html` اضافه کنید:

```html
<script defer src="/assets/new-film.js?v=20261120-3"></script>
<script defer src="/assets/scene-extras.js?v=20261120-5"></script>
```

## منطق ساخت فیلم

1. `GET /api/projects` → اولین پروژه
2. `GET /api/projects/{id}/scripts` → محاسبهٔ `max(film_no)+1`
3. `POST /api/projects/{id}/scripts` → ساخت سناریو (title/treatment)
4. `PATCH /api/scripts/{id}` → ثبت `meta: {film_no, duration_sec, scene_count, source:"ui"}`
5. اختیاری: `POST /api/scripts/{id}/generate` → ساخت سکانس‌ها با LLM
6. رفرش UI تا فیلم جدید (که جدیدترین است) باز شود

## نکتهٔ پایپ‌لاین

سرویس `shahnameh-pipeline` فقط شماره‌فیلم‌های داخل `film_pipeline.py` را می‌سازد:

```python
FILM_NUMBERS = [1, 2, 3, 4, 5, 11]
```

یعنی فیلم جدید (مثلاً ۱۲) در استودیو ساخته و قابل ویرایش/رندر دستی است، اما تا وقتی شمارهٔ آن به این لیست اضافه نشود، پایپ‌لاین خودکار سراغش نمی‌رود.

## تست‌های انجام‌شده

- ساخت فیلم + ثبت `film_no` + بازگشت به حالت اولیه (API) ✓
- تولید ۲۴ سکانس با AI (پس از افزایش `max_tokens` به ۱۲۰۰۰ و فشرده‌سازی پرامپت) ✓
- سرو شدن `/assets/new-film.js` و تگ اسکریپت در `/index.html` ✓

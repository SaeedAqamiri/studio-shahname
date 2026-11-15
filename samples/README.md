# Samples

Real outputs from the studio database: the latest four images per character and the full scripts.

- `characters/<name>/character.json` — description, appearance, voice and image metadata (kind, prompt, seed).
- `characters/<name>/01.jpg …` — the latest images, newest first.
- `scripts/<title>.json` — structured scenes (location, time, action, dialogue, cast, compiled prompt).
- `scripts/<title>.md` — the same script as readable Markdown.

Images are downscaled to max 1024 px and stored as JPEG for repository size.

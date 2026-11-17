"""Pacing profiles for the studio.

A profile turns a project brief (format + genre) into concrete numbers:
narrative scene length, shots per scene, and shot length.  The same module is
used by the script generator, the API, and the render pipeline so a project
keeps one rhythm from page to screen.
"""
from __future__ import annotations

from copy import deepcopy

DEFAULT_PROFILE = "epic_historical"

PROFILES: dict[str, dict] = {
    "epic_historical": {
        "label": "حماسی/تاریخی (شاهنامه)",
        "description": "فیلم زنده، قاب‌های wide، long take و نور دراماتیک؛ مناسب شاهنامه و حماسه‌های تاریخی.",
        "format": "live_action",
        "genre": "epic_historical",
        "scene_duration": [20, 30],
        "scene_count": [20, 28],
        "shot_duration": [8, 15],
        "shots_per_scene": [2, 3],
        "avg_shot": "10-14",
        "style_note": "cinematic live action, ancient Persian epic, wide tableaux, long takes, dramatic volumetric light",
        "negative_note": "cartoon, anime, 3d render, CGI, plastic skin",
    },
    "cinematic_realism": {
        "label": "شبه‌واقعی/سینمایی",
        "description": "فیلم زنده با پوشش کلاسیک، نماهای ۵–۱۰ ثانیه، نور طبیعی و بازی طبیعی.",
        "format": "live_action",
        "genre": "drama",
        "scene_duration": [25, 40],
        "scene_count": [15, 24],
        "shot_duration": [5, 10],
        "shots_per_scene": [3, 5],
        "avg_shot": "6-8",
        "style_note": "cinematic realism, natural light, handheld/steadicam coverage, lived-in production design",
        "negative_note": "cartoon, anime, stylized, low quality",
    },
    "action_war": {
        "label": "جنگی/اکشن",
        "description": "برش‌های سریع ۲–۶ ثانیه، دوربین handheld و impact؛ مناسب نبرد، تعقیب و صحنه‌های جنگی.",
        "format": "live_action",
        "genre": "action_war",
        "scene_duration": [15, 25],
        "scene_count": [24, 32],
        "shot_duration": [2, 6],
        "shots_per_scene": [4, 6],
        "avg_shot": "3-5",
        "style_note": "gritty war action, handheld camera, fast cuts, impact, dust, practical effects",
        "negative_note": "slow, static, cartoon, anime, low quality",
    },
    "animation_family": {
        "label": "انیمیشن خانوادگی",
        "description": "انیمیشن با نماهای ۳–۶ ثانیه، خوانایی حرکت و رنگ؛ نزدیک به استاندارد انیمیشن هالیوودی.",
        "format": "animation",
        "genre": "family_animation",
        "scene_duration": [20, 40],
        "scene_count": [15, 24],
        "shot_duration": [3, 6],
        "shots_per_scene": [4, 7],
        "avg_shot": "4-5",
        "style_note": "stylized 3D animation, expressive staging, clear silhouettes, vibrant colors, family-friendly",
        "negative_note": "photorealistic, live action, horror, gore, low quality",
    },
    "animation_epic": {
        "label": "انیمیشن حماسی",
        "description": "انیمیشن با نماهای ۴–۸ ثانیه و قاب‌های حماسی؛ مناسب اقتباس انیمیشنی شاهنامه.",
        "format": "animation",
        "genre": "epic_animation",
        "scene_duration": [20, 30],
        "scene_count": [20, 28],
        "shot_duration": [4, 8],
        "shots_per_scene": [3, 4],
        "avg_shot": "6-7",
        "style_note": "epic stylized animation, painterly Persian epic, dramatic staging, expressive characters",
        "negative_note": "photorealistic, live action, low quality, childish cartoon",
    },
    "drama_slow": {
        "label": "درام/آرته",
        "description": "صحنه‌های ۴۵–۷۵ ثانیه، نماهای ۸–۱۵ ثانیه، سکوت و کلوزآپ.",
        "format": "live_action",
        "genre": "drama",
        "scene_duration": [45, 75],
        "scene_count": [8, 14],
        "shot_duration": [8, 15],
        "shots_per_scene": [3, 5],
        "avg_shot": "10-12",
        "style_note": "slow cinema, long takes, natural light, intimate close-ups, silence",
        "negative_note": "fast cuts, action, cartoon, low quality",
    },
    "documentary": {
        "label": "مستند",
        "description": "صحنه‌های ۴۵–۹۰ ثانیه، نماهای ۵–۱۰ ثانیه، مصاحبه و b-roll.",
        "format": "documentary",
        "genre": "documentary",
        "scene_duration": [45, 90],
        "scene_count": [8, 12],
        "shot_duration": [5, 10],
        "shots_per_scene": [5, 10],
        "avg_shot": "7-8",
        "style_note": "documentary realism, observational camera, natural light, interviews, b-roll",
        "negative_note": "staged, cartoon, low quality",
    },
}

SHOT_PROMPTS = {
    "wide": "wide establishing shot, full environment, the action begins",
    "medium": "medium shot, the action continues, same characters and location",
    "close": "close-up, emotional expression, same characters",
    "insert": "detail insert, hands, object or environment detail",
    "reaction": "reaction shot, face and body language",
    "tracking": "tracking shot, camera moves with the action",
    "impact": "impact shot, collision or action beat",
}

KIND_SETS = {
    "epic_historical": ["wide", "medium", "close", "insert"],
    "cinematic_realism": ["wide", "medium", "close", "insert", "reaction"],
    "action_war": ["wide", "tracking", "impact", "close", "reaction", "insert"],
    "animation_family": ["wide", "medium", "close", "reaction", "insert"],
    "animation_epic": ["wide", "medium", "close", "insert"],
    "drama_slow": ["wide", "medium", "close", "reaction", "insert"],
    "documentary": ["wide", "medium", "close", "insert", "reaction"],
}


def get_profile(profile_id: str | None) -> dict:
    key = profile_id or DEFAULT_PROFILE
    p = deepcopy(PROFILES.get(key) or PROFILES[DEFAULT_PROFILE])
    p["id"] = key if key in PROFILES else DEFAULT_PROFILE
    return p


def list_profiles() -> list[dict]:
    return [{"id": k, **deepcopy(v)} for k, v in PROFILES.items()]


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _even(total: int, n: int, max_shot: int) -> list[int]:
    n = max(1, n)
    while n * max_shot < total:
        n += 1
    base, rem = divmod(total, n)
    parts = [base + 1] * rem + [base] * (n - rem)
    return parts


def split_scene(total: int, profile_id: str | None = None) -> list[dict]:
    """Return [{'kind': ..., 'seconds': int}, ...] for one scene/beat."""
    p = get_profile(profile_id)
    pid = p["id"]
    total = max(1, int(round(total or 20)))
    if pid == "epic_historical":
        if total <= 27:
            first = min(15, max(10, total - 8))
            secs = [first, total - first]
        else:
            first = 15
            second = 9 if total >= 29 else 8
            secs = [first, second, total - first - second]
        kinds = ["wide", "close"] if len(secs) == 2 else ["wide", "medium", "close"]
    elif pid == "cinematic_realism":
        n = _clamp(round(total / 7), 3, 5)
        secs = _even(total, n, 10)
        kinds = KIND_SETS[pid]
    elif pid == "action_war":
        n = _clamp(round(total / 4), 4, 6)
        secs = _even(total, n, 6)
        kinds = KIND_SETS[pid]
    elif pid == "animation_family":
        n = _clamp(round(total / 5), 4, 7)
        secs = _even(total, n, 6)
        kinds = KIND_SETS[pid]
    elif pid == "animation_epic":
        n = _clamp(round(total / 6), 3, 4)
        secs = _even(total, n, 8)
        kinds = KIND_SETS[pid]
    elif pid == "drama_slow":
        n = _clamp(round(total / 12), 3, 5)
        secs = _even(total, n, 15)
        kinds = KIND_SETS[pid]
    elif pid == "documentary":
        n = _clamp(round(total / 8), 5, 10)
        secs = _even(total, n, 10)
        kinds = KIND_SETS[pid]
    else:
        return split_scene(total, DEFAULT_PROFILE)
    out = []
    for i, s in enumerate(secs):
        out.append({"kind": kinds[i % len(kinds)], "seconds": int(s)})
    return out


def scene_count_suggestion(target_seconds: int, profile_id: str | None = None) -> int:
    p = get_profile(profile_id)
    lo, hi = p["scene_duration"]
    avg = (lo + hi) / 2
    n = int(round((target_seconds or 600) / avg))
    return _clamp(n, 3, 40)


def shot_prompt(kind: str) -> str:
    return SHOT_PROMPTS.get(kind, SHOT_PROMPTS["medium"])


def pacing_brief(profile_id: str | None = None, target_seconds: int = 600) -> str:
    p = get_profile(profile_id)
    return (
        f"Format: {p['format']}; genre: {p['genre']}. "
        f"Narrative scene length: {p['scene_duration'][0]}-{p['scene_duration'][1]} seconds; "
        f"scene count for a {target_seconds}s film: about {scene_count_suggestion(target_seconds, p['id'])}. "
        f"Shots per scene: {p['shots_per_scene'][0]}-{p['shots_per_scene'][1]}; "
        f"shot length: {p['shot_duration'][0]}-{p['shot_duration'][1]} seconds (average {p['avg_shot']}s). "
        f"Visual rhythm: {p['style_note']}."
    )

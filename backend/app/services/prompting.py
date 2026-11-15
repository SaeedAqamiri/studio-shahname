from __future__ import annotations

from .. import config
from ..models import Character, Project


def style_bible(project: Project | None) -> dict:
    base = dict(config.STYLE_DEFAULT)
    if project and project.style_bible:
        base.update(project.style_bible)
    return base


def character_prompt(project: Project | None, character: Character, extra: str = "", framing: str = "portrait") -> str:
    st = style_bible(project)
    ap = character.appearance or {}
    bits = [st.get("art_direction", "")]
    if framing == "portrait":
        bits.append("character portrait, three-quarter view, facing camera, neutral background")
    elif framing == "full":
        bits.append("full body character design sheet, front view, neutral background")
    elif framing == "turnaround":
        bits.append("character turnaround sheet, front and side views, neutral background")
    bits.append(character.name_en or character.name)
    if character.description:
        bits.append(character.description)
    for key in ("age", "build", "face", "hair", "beard", "eyes", "skin", "clothing", "armor", "accessories", "signature"):
        if ap.get(key):
            bits.append(f"{key}: {ap[key]}")
    if extra:
        bits.append(extra)
    bits.append(f"lighting: {st.get('lighting', '')}")
    bits.append(f"palette: {st.get('palette', '')}")
    bits.append(f"camera: {st.get('lens', '')}")
    return ", ".join(b for b in bits if b)


def character_negative(project: Project | None, character: Character | None = None) -> str:
    st = style_bible(project)
    neg = st.get("negative", config.STYLE_DEFAULT["negative"])
    if character and character.negative:
        neg = neg + ", " + character.negative
    return neg


def scene_prompt(project: Project | None, scene, cast_lines: list[str], extra: str = "") -> str:
    st = style_bible(project)
    bits = [st.get("art_direction", ""), scene.heading, scene.location, scene.time_of_day, scene.action_text, scene.summary]
    bits.extend(cast_lines)
    if extra:
        bits.append(extra)
    bits.append(f"lighting: {st.get('lighting', '')}")
    bits.append(f"palette: {st.get('palette', '')}")
    bits.append(f"camera: {st.get('lens', '')}")
    return ", ".join(b for b in bits if b)

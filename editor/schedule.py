"""Lekce: the lesson cards and the photo gallery on the homepage.

Everything lives in one folder, content/lekce/: the file lekce.yaml with
the texts, and the gallery photos next to it. The rules for what is valid
live in build.py (load_schedule), so the editor reuses them.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

import build

INTRO_MAX = 200
MAX_LESSONS = 30
MAX_PHOTOS = 60
FIELD_LIMITS = {"day": 40, "time": 40, "place": 100, "address": 150}
FIELD_NAMES = {"day": "nadpis", "time": "čas", "place": "místo", "address": "adresu"}


def read(text: str | None) -> dict:
    """lekce.yaml as a dict with intro, lessons and gallery (empty if missing)."""
    data = yaml.safe_load(text) if text else None
    data = data if isinstance(data, dict) else {}
    return {
        "intro": str(data.get("intro") or ""),
        "lessons": [l for l in (data.get("lessons") or []) if isinstance(l, dict)],
        "gallery": [g for g in (data.get("gallery") or []) if isinstance(g, dict)],
    }


def check_lessons(raw: list) -> tuple[list[dict], list[str]]:
    """Clean the lesson cards from the form. Returns (lessons, Czech error messages)."""
    lessons, errors = [], []
    if len(raw) > MAX_LESSONS:
        errors.append(f"Lekcí může být nejvýš {MAX_LESSONS}.")
    for n, item in enumerate(raw[:MAX_LESSONS], start=1):
        item = item if isinstance(item, dict) else {}
        lesson = {key: " ".join(str(item.get(key) or "").split()) for key in FIELD_LIMITS}
        for key, limit in FIELD_LIMITS.items():
            if not lesson[key]:
                errors.append(f"Lekce {n}: doplňte {FIELD_NAMES[key]}.")
            elif len(lesson[key]) > limit:
                errors.append(f"Lekce {n}: {FIELD_NAMES[key]} může mít nejvýš {limit} znaků.")
        note = build.clean_note(str(item.get("note") or ""))
        if note:
            lesson["note"] = note
        lessons.append(lesson)
    return lessons, errors


def compose(intro: str, lessons: list[dict], gallery: list[dict]) -> str:
    data = {"intro": intro, "lessons": lessons, "gallery": gallery}
    return ("# Lekce: edited in the editor (Lekce page). The site is built from this file.\n"
            + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000))


def check_with_build(yaml_text: str, photo_names: list[str]) -> None:
    """Run the build's own validation. Raises build.BuildError."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / build.LESSONS_FILE).write_text(yaml_text, encoding="utf-8")
        for name in photo_names:
            (folder / name).touch()            # the build only checks they exist
        build.load_schedule(folder)

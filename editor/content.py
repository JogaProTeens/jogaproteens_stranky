"""Turning the editor form into a post folder, and back.

The rules for what a valid post is live in build.py. This module reuses
them, so the editor can never save something the build would reject.
"""
from __future__ import annotations

import datetime as dt
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import nh3
import yaml

import build                       # the site's own build script

COVER_FILES = ("cover.webp", "cover-card.webp", "og.jpg")
FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*$")
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.(webp|jpe?g|png|gif)$", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE)


@dataclass
class PostSummary:
    folder: str
    title: str
    date: dt.date
    draft: bool
    slug: str


@dataclass
class LoadedPost:
    folder: str
    meta: dict
    body: str
    files: list[str] = field(default_factory=list)


# ---------- names ----------

def slugify(title: str, max_length: int = 60) -> str:
    """'Dech před testem!' -> 'dech-pred-testem'."""
    ascii_text = (unicodedata.normalize("NFKD", title)
                  .encode("ascii", "ignore").decode().lower())
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug or "clanek"


def unique_slug(base: str, taken: set[str]) -> str:
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


# ---------- reading ----------

def parse(folder: str, text: str, files: list[str]) -> LoadedPost:
    meta, body = build.split_front_matter(text, Path(folder, "index.md"))
    return LoadedPost(folder=folder, meta=meta, body=body.strip(), files=files)


def summarise(post: LoadedPost) -> PostSummary:
    date = post.meta.get("date")
    return PostSummary(
        folder=post.folder,
        title=str(post.meta.get("title", post.folder)),
        date=date if isinstance(date, dt.date) else dt.date.min,
        draft=bool(post.meta.get("draft", False)),
        slug=str(post.meta.get("slug", "")),
    )


# ---------- the body text ----------

def sanitise(html: str) -> str:
    """Keep only the formatting the site supports."""
    html = html.replace("&nbsp;", " ").replace(" ", " ")
    html = nh3.clean(html, tags=build.ALLOWED_TAGS, attributes=build.ALLOWED_ATTRIBUTES,
                     url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer")
    html = re.sub(r'<img(?![^>]*\bsrc="[^"]+")[^>]*>', "", html)  # images left without a source
    html = re.sub(r"(<p>(\s|<br>)*</p>\s*)+$", "", html)           # empty lines at the end
    return html.strip()


def resolve_images(html: str, folder: str, uploads: dict[str, bytes],
                   existing: set[str], process) -> tuple[str, dict[str, bytes], set[str]]:
    """Point every <img> in the body at a file in the post folder.

    src="upload/3"            a photo just added: processed, saved under a new name
    src="/media/<folder>/x"   a photo shown in the editor: becomes "x"
    src="x"                   already a file of this post: kept
    anything else             dropped, apart from ordinary https links
    Returns the new HTML, the new files to save and every file still in use.
    """
    new_files: dict[str, bytes] = {}
    used: set[str] = set()
    media_prefix = f"/media/{folder}/"

    def fix(match: re.Match) -> str:
        src = match.group(2)
        if src.startswith("upload/") and src in uploads:
            name, data = process(uploads[src])
            new_files[name] = data
            used.add(name)
            return match.group(1) + name + match.group(3)
        if src.startswith(media_prefix):
            src = src[len(media_prefix):]
        if src in existing:
            used.add(src)
            return match.group(1) + src + match.group(3)
        if src.startswith("https://"):
            return match.group(0)
        return match.group(1) + match.group(3)       # empty src, removed by sanitise()

    return IMG_SRC_RE.sub(fix, html), new_files, used


def show_images_in_editor(html: str, folder: str) -> str:
    """The reverse: relative file names become /media/ links the editor can load."""
    def fix(match: re.Match) -> str:
        src = match.group(2)
        if FILE_RE.match(src):
            return f"{match.group(1)}/media/{folder}/{src}{match.group(3)}"
        return match.group(0)
    return IMG_SRC_RE.sub(fix, html)


# ---------- writing ----------

def compose(meta: dict, body: str) -> str:
    """The index.md text: details block, then the body HTML."""
    details = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False,
                             default_flow_style=False, width=1000)
    return f"---\n{details}---\n{body}\n"


def check_with_build(folder: str, index_md: str, cover_name: str) -> None:
    """Run the build's own validation on the post. Raises build.BuildError."""
    with tempfile.TemporaryDirectory() as tmp:
        post_dir = Path(tmp, folder)
        post_dir.mkdir()
        (post_dir / "index.md").write_text(index_md, encoding="utf-8")
        (post_dir / cover_name).touch()          # the build only checks it exists
        build.load_post(post_dir)

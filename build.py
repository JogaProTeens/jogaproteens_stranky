"""Build jogaproteens.cz into _site/.

    python build.py            build the public site (drafts left out)
    python build.py --drafts   also include drafts, for previewing locally

Pipeline: copy static/ -> read and validate every post in content/posts/
-> render pages from templates/ -> write sitemap.xml.
The build stops with a clear message instead of publishing something broken.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

import markdown
import nh3
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).parent
POSTS_DIR = ROOT / "content" / "posts"
OUT = ROOT / "_site"
SITE_URL = "https://jogaproteens.cz"
CAROUSEL_LIMIT = 12          # newest posts shown on the homepage
HEADLINE_MAX = 160           # characters

MONTHS_CS = ["ledna", "února", "března", "dubna", "května", "června",
             "července", "srpna", "září", "října", "listopadu", "prosince"]

# HTML allowed in a post body. Anything else (scripts, styles, fonts pasted
# from Word, event handlers) is stripped by nh3 before it reaches the site.
ALLOWED_TAGS = {"p", "br", "h2", "h3", "strong", "b", "em", "i", "u", "s",
                "a", "ul", "ol", "li", "blockquote", "img", "figure",
                "figcaption", "hr"}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"},
                      "img": {"src", "alt", "width", "height"}}

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED = ("title", "slug", "date", "headline", "cover", "cover_alt", "orientation")


class BuildError(Exception):
    """A problem in the content that must be fixed before publishing."""


@dataclass
class Post:
    folder: Path
    slug: str
    title: str
    date: dt.date
    headline: str
    cover: str
    cover_alt: str
    orientation: str          # "portrait" (2:3) or "landscape" (3:2)
    body_html: str
    video_embed: str | None
    draft: bool

    @property
    def url(self) -> str:
        return f"/inspirace/{self.slug}/"


# ---------- reading and validating posts ----------

def split_front_matter(text: str, source: Path) -> tuple[dict, str]:
    """Separate the YAML details block from the body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        raise BuildError(f"{source}: must start with a '---' details block")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise BuildError(f"{source}: the details block is not valid")
    return data, match.group(2)


def video_embed_url(url: str, source: Path) -> str:
    """Turn a YouTube or Vimeo page link into a privacy-friendly embed URL."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    video_id = None
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host == "youtube.com":
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/")):
            video_id = parsed.path.split("/")[2]
    elif host == "vimeo.com" and parsed.path.strip("/").isdigit():
        return f"https://player.vimeo.com/video/{parsed.path.strip('/')}"
    if video_id and re.fullmatch(r"[\w-]{6,20}", video_id):
        return f"https://www.youtube-nocookie.com/embed/{video_id}"
    raise BuildError(f"{source}: video must be a YouTube or Vimeo link, got {url!r}")


def clean_body(raw: str) -> str:
    """Markdown or HTML in, sanitised HTML out."""
    html = markdown.markdown(raw, extensions=["extra", "sane_lists"])
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )


def load_post(folder: Path) -> Post:
    path = folder / "index.md"
    source = path.relative_to(ROOT)          # short path for error messages
    data, body = split_front_matter(path.read_text(encoding="utf-8"), source)

    missing = [key for key in REQUIRED if not data.get(key)]
    if missing:
        raise BuildError(f"{source}: missing {', '.join(missing)}")

    slug = str(data["slug"])
    if not SLUG_RE.match(slug):
        raise BuildError(f"{source}: slug {slug!r} may only use a-z, 0-9 and hyphens")
    if not isinstance(data["date"], dt.date):
        raise BuildError(f"{source}: date must look like 2026-10-08")
    if data["orientation"] not in ("portrait", "landscape"):
        raise BuildError(f"{source}: orientation must be portrait or landscape")
    if len(str(data["headline"])) > HEADLINE_MAX:
        raise BuildError(f"{source}: headline is longer than {HEADLINE_MAX} characters")
    if not (folder / data["cover"]).is_file():
        raise BuildError(f"{source}: cover image {data['cover']!r} not found in the folder")

    video = data.get("video")
    return Post(
        folder=folder,
        slug=slug,
        title=str(data["title"]),
        date=data["date"],
        headline=str(data["headline"]),
        cover=str(data["cover"]),
        cover_alt=str(data["cover_alt"]),
        orientation=data["orientation"],
        body_html=clean_body(body),
        video_embed=video_embed_url(str(video), source) if video else None,
        draft=bool(data.get("draft", False)),
    )


def load_posts(include_drafts: bool) -> list[Post]:
    if not POSTS_DIR.exists():
        return []
    posts = [load_post(f) for f in sorted(POSTS_DIR.iterdir())
             if (f / "index.md").is_file()]
    slugs = [p.slug for p in posts]
    duplicates = {s for s in slugs if slugs.count(s) > 1}
    if duplicates:
        raise BuildError(f"two posts share the slug {', '.join(sorted(duplicates))}")
    visible = [p for p in posts if include_drafts or not p.draft]
    return sorted(visible, key=lambda p: (p.date, p.slug), reverse=True)


# ---------- rendering ----------

def czech_date(value: dt.date) -> str:
    """2026-10-08 -> '8. října 2026'. No system locale needed."""
    return f"{value.day}. {MONTHS_CS[value.month - 1]} {value.year}"


def make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=True,             # escapes titles and other text
        undefined=StrictUndefined,   # a template typo fails the build
        keep_trailing_newline=True,
    )
    env.filters["cs_date"] = czech_date
    env.globals["site_url"] = SITE_URL
    return env


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_sitemap(posts: list[Post]) -> None:
    today = dt.date.today().isoformat()
    entries = [(f"{SITE_URL}/", today)]
    if posts:
        entries.append((f"{SITE_URL}/inspirace/", posts[0].date.isoformat()))
    entries += [(f"{SITE_URL}{p.url}", p.date.isoformat()) for p in posts]
    rows = "\n".join(
        f"  <url><loc>{escape(loc)}</loc><lastmod>{mod}</lastmod></url>"
        for loc, mod in entries
    )
    write(OUT / "sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          f"{rows}\n</urlset>\n")


def build(include_drafts: bool = False) -> None:
    posts = load_posts(include_drafts)   # validate before touching _site/

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "static", OUT)

    env = make_env()
    write(OUT / "index.html", env.get_template("index.html").render(
        posts=posts[:CAROUSEL_LIMIT],
        has_more=len(posts) > CAROUSEL_LIMIT,
    ))
    write(OUT / "inspirace" / "index.html",
          env.get_template("archive.html").render(posts=posts))

    post_template = env.get_template("post.html")
    for i, post in enumerate(posts):
        target = OUT / "inspirace" / post.slug
        shutil.copytree(post.folder, target, ignore=shutil.ignore_patterns("index.md"))
        write(target / "index.html", post_template.render(
            post=post,
            newer=posts[i - 1] if i > 0 else None,
            older=posts[i + 1] if i + 1 < len(posts) else None,
        ))

    write_sitemap(posts)
    drafts = sum(p.draft for p in posts)
    print(f"Built {OUT} with {len(posts)} post(s)"
          + (f", {drafts} draft(s) included" if drafts else ""))


if __name__ == "__main__":
    try:
        build(include_drafts="--drafts" in sys.argv)
    except BuildError as error:
        print(f"BUILD FAILED: {error}")
        sys.exit(1)

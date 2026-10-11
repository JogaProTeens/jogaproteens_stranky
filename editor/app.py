"""Petra's editor for the Inspirace posts.

Run it from the project folder:
    uvicorn editor.app:app --reload --port 8001
then open http://localhost:8001
"""
from __future__ import annotations

import datetime as dt
import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

import build
from editor import images
from editor.config import REPO_ROOT, load_settings
from editor.content import (COVER_FILES, FILE_RE, FOLDER_RE, check_with_build, compose,
                            parse, resolve_images, sanitise, show_images_in_editor,
                            slugify, summarise, unique_slug)
from editor.store import GitHubStore, LocalStore, Store, StoreError

HERE = Path(__file__).parent
TITLE_MAX = 120
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

settings = load_settings()


def make_store() -> Store:
    if settings.store == "github":
        return GitHubStore(settings.github_token, settings.github_repo, settings.github_branch)
    return LocalStore(REPO_ROOT)


store: Store = make_store()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if isinstance(store, GitHubStore):
        await store.client.aclose()


app = FastAPI(title="Editor Jóga pro teens", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.mount("/fonts", StaticFiles(directory=REPO_ROOT / "static" / "fonts"), name="fonts")

templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["cs_date"] = build.czech_date
templates.env.globals.update(site_url=build.SITE_URL, settings=settings,
                             headline_max=build.HEADLINE_MAX, title_max=TITLE_MAX)


@app.middleware("http")
async def same_site_only(request: Request, call_next):
    """Refuse form posts that come from another website (CSRF protection)."""
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        if (origin and urlparse(origin).netloc != request.headers.get("host")) \
                or fetch_site not in (None, "same-origin", "none"):
            return PlainTextResponse("Požadavek z cizí stránky byl odmítnut.", status_code=403)
    return await call_next(request)


@app.exception_handler(StoreError)
async def store_error_page(request: Request, error: StoreError):
    return templates.TemplateResponse(request, "error.html", {"message": str(error)},
                                      status_code=502)


async def load_post(folder: str):
    if not FOLDER_RE.match(folder):
        raise StoreError("Takový článek neexistuje.")
    snap = await store.snapshot()
    if folder not in snap.folders():
        raise StoreError("Takový článek neexistuje. Možná už byl smazaný.")
    text = (await store.read(f"{folder}/index.md")).decode("utf-8")
    return parse(folder, text, snap.files_in(folder)), snap


# ---------- pages ----------

@app.get("/")
async def post_list(request: Request):
    snap = await store.snapshot()
    folders = snap.folders()
    texts = await store.read_many([f"{f}/index.md" for f in folders])
    posts = []
    for folder, text in zip(folders, texts):
        try:
            posts.append(summarise(parse(folder, text.decode("utf-8"), [])))
        except build.BuildError:
            continue                    # a broken file: the build will report it
    posts.sort(key=lambda p: (p.date, p.folder), reverse=True)
    q = request.query_params
    saved = q.get("ulozeno", "")
    commit = q.get("commit", "")
    return templates.TemplateResponse(request, "list.html", {
        "posts": posts,
        "saved": saved if FOLDER_RE.match(saved) else "",
        "deleted": q.get("smazano") == "1",
        "draft": q.get("koncept") == "1",
        "commit": commit if SHA_RE.match(commit) else "",
    })


@app.get("/novy")
async def new_post(request: Request):
    return templates.TemplateResponse(request, "edit.html", {
        "post": None, "folder": "", "meta": {"date": dt.date.today(), "orientation": "portrait"},
        "body": "", "cover_url": "",
    })


@app.get("/upravit/{folder}")
async def edit_post(request: Request, folder: str):
    post, _ = await load_post(folder)
    body = show_images_in_editor(build.clean_body(post.body), folder)
    return templates.TemplateResponse(request, "edit.html", {
        "post": post, "folder": folder, "meta": post.meta, "body": body,
        "cover_url": f"/media/{folder}/{quote(str(post.meta.get('cover', '')))}",
    })


@app.get("/media/{folder}/{name}")
async def media(folder: str, name: str):
    if not (FOLDER_RE.match(folder) and FILE_RE.match(name)):
        return PlainTextResponse("Nenalezeno", status_code=404)
    try:
        data = await store.read(f"{folder}/{name}")
    except StoreError:
        return PlainTextResponse("Nenalezeno", status_code=404)
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/stav/{commit}")
async def deploy_status(commit: str):
    if not SHA_RE.match(commit):
        return JSONResponse({"state": None}, status_code=400)
    return {"state": await store.build_status(commit)}


# ---------- saving ----------

def text_field(form, name: str) -> str:
    value = form.get(name)
    return value.strip() if isinstance(value, str) else ""


async def file_field(form, name: str) -> bytes | None:
    value = form.get(name)
    if isinstance(value, UploadFile) and value.filename:
        data = await value.read()
        return data or None
    return None


@app.post("/ulozit")
async def save_post(request: Request):
    """Answers with JSON, because the page sends the form with JavaScript."""
    try:
        form = await request.form(max_files=60, max_fields=40, max_part_size=2 * 1024 * 1024)
        return await save(form)
    except StoreError as error:
        return JSONResponse({"ok": False, "errors": [str(error)]}, status_code=502)


async def save(form) -> dict | JSONResponse:
    errors: list[str] = []

    folder = text_field(form, "folder")
    publish = text_field(form, "action") == "publish"
    title = text_field(form, "title")
    headline = " ".join(text_field(form, "headline").split())
    cover_alt = text_field(form, "cover_alt")
    orientation = text_field(form, "orientation")
    video = text_field(form, "video")
    raw_body = form.get("body") if isinstance(form.get("body"), str) else ""

    if not title:
        errors.append("Doplňte název článku.")
    elif len(title) > TITLE_MAX:
        errors.append(f"Název může mít nejvýš {TITLE_MAX} znaků.")
    if not headline:
        errors.append("Doplňte úvodní text.")
    elif len(headline) > build.HEADLINE_MAX:
        errors.append(f"Úvodní text může mít nejvýš {build.HEADLINE_MAX} znaků.")
    try:
        date = dt.date.fromisoformat(text_field(form, "date"))
    except ValueError:
        date = None
        errors.append("Vyberte datum.")
    if orientation not in images.RATIOS:
        errors.append("Vyberte, jestli je titulní fotka na výšku, nebo na šířku.")
    if not cover_alt:
        errors.append("Popište titulní fotku (pro nevidomé a vyhledávače).")
    if video:
        try:
            build.video_embed_url(video, Path("video"))
        except build.BuildError:
            errors.append("Video musí být odkaz na YouTube nebo Vimeo.")

    # The post as it is now (when editing)
    old = None
    snap = await store.snapshot()
    if folder:
        old, snap = await load_post(folder)

    # Cover photo
    cover_data = await file_field(form, "cover")
    cover_files: dict[str, bytes] = {}
    if cover_data and orientation in images.RATIOS:
        try:
            cover_files = images.cover_files(cover_data, orientation)
        except images.ImageError as error:
            errors.append(f"Titulní fotka: {error}")
    elif not cover_data:
        if old is None:
            errors.append("Vyberte titulní fotku.")
        elif orientation != old.meta.get("orientation"):
            errors.append("Pro změnu tvaru nahrajte titulní fotku znovu.")

    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    # Name of the post: fixed when it is first saved, so links never break
    if old:
        slug = str(old.meta["slug"])
    else:
        taken = {f[11:] for f in snap.folders()}
        slug = unique_slug(slugify(title), taken)
        folder = f"{date.isoformat()}-{slug}"

    # Body text and the photos inside it
    uploads = {}
    for key, value in form.multi_items():
        if key.startswith("upload/") and isinstance(value, UploadFile):
            uploads[key] = await value.read()
    try:
        html, body_files, used = resolve_images(
            raw_body, folder, uploads, set(old.files) if old else set(), images.body_photo)
    except images.ImageError as error:
        return JSONResponse({"ok": False, "errors": [f"Fotka v textu: {error}"]}, status_code=400)
    body = sanitise(html)
    if not re.sub(r"<[^>]+>", "", body).strip() and "<img" not in body:
        return JSONResponse({"ok": False, "errors": ["Napište text článku."]}, status_code=400)

    cover = "cover.webp" if cover_files else str(old.meta["cover"])
    meta = {"title": title, "slug": slug, "date": date, "headline": headline,
            "cover": cover, "cover_alt": cover_alt, "orientation": orientation}
    if video:
        meta["video"] = video
    if not publish:
        meta["draft"] = True
    index_md = compose(meta, body)

    try:
        check_with_build(folder, index_md, cover)
    except build.BuildError as error:
        return JSONResponse({"ok": False, "errors": [f"Kontrola webu neprošla: {error}"]},
                            status_code=400)

    # One commit: the text, new photos, and old photos nobody uses any more
    put = {f"{folder}/index.md": index_md.encode("utf-8")}
    put |= {f"{folder}/{name}": data for name, data in (cover_files | body_files).items()}
    keep = {"index.md", cover, *COVER_FILES, *used}
    delete = [f"{folder}/{name}" for name in (old.files if old else [])
              if name not in keep and FILE_RE.match(name)]
    verb = "Publikováno" if publish else "Koncept"
    commit = await store.commit(f"{verb}: {title}", put, delete)

    target = f"/?ulozeno={folder}" + ("" if publish else "&koncept=1")
    if commit:
        target += f"&commit={commit}"
    return {"ok": True, "redirect": target}


@app.post("/smazat/{folder}")
async def delete_post(folder: str):
    post, snap = await load_post(folder)
    files = [f"{folder}/{name}" for name in snap.files_in(folder)]
    commit = await store.commit(f"Smazáno: {post.meta.get('title', folder)}", {}, files)
    target = "/?smazano=1" + (f"&commit={commit}" if commit else "")
    return RedirectResponse(target, status_code=303)

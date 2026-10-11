"""Tests for the editor. Run from the project folder with:  pytest"""
from __future__ import annotations

import asyncio
import datetime as dt
import base64
import hashlib
import io
import json
import os

import httpx
import pytest
from PIL import Image

# Tests never touch GitHub and ignore whatever is in your .env
os.environ.update(EDITOR_STORE="local", EDITOR_PASSWORD_HASH="", SESSION_SECRET="")

from editor import app as editor_app           # noqa: E402
from editor import auth, content, images       # noqa: E402
from editor.config import Settings             # noqa: E402
from editor.store import GitHubStore, LocalStore, StoreError, safe_path  # noqa: E402


def photo(size=(3000, 2000), rotate=False, gps=False) -> bytes:
    img = Image.new("RGB", size, (200, 170, 150))
    exif = Image.Exif()
    if rotate:
        exif[0x0112] = 6                        # phone held upright
    if gps:
        exif[0x8825] = {1: "N", 2: (50.0, 5.0, 0.0)}
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


# ---------- names and text ----------

@pytest.mark.parametrize("title, slug", [
    ("Dech před testem!", "dech-pred-testem"),
    ("Jóga a spánek: jak usnout dřív", "joga-a-spanek-jak-usnout-driv"),
    ("ŘEŘICHA, ŽÁBY a ůly", "rericha-zaby-a-uly"),
    ("???", "clanek"),
])
def test_slugify(title, slug):
    assert content.slugify(title) == slug


def test_unique_slug_adds_a_number():
    assert content.unique_slug("dech", {"dech", "dech-2"}) == "dech-3"


def test_sanitise_removes_scripts_and_word_junk():
    dirty = '<p style="font-family:Calibri">Ahoj&nbsp;<script>alert(1)</script><a href="javascript:x">x</a></p><p><br></p>'
    clean = content.sanitise(dirty)
    assert "script" not in clean and "javascript" not in clean and "Calibri" not in clean
    assert clean.startswith("<p>Ahoj ")
    assert not clean.endswith("<p><br></p>")


def test_resolve_images():
    html = ('<p><img src="upload/0"><img src="/media/2026-01-01-a/img-old.webp">'
            '<img src="data:image/png;base64,AAAA"><img src="https://example.com/x.jpg"></p>')
    out, new, used = content.resolve_images(
        html, "2026-01-01-a", {"upload/0": b"raw"}, {"img-old.webp"},
        process=lambda data: ("img-new.webp", b"processed"))
    out = content.sanitise(out)
    assert new == {"img-new.webp": b"processed"}
    assert used == {"img-new.webp", "img-old.webp"}
    assert out == ('<p><img src="img-new.webp"><img src="img-old.webp">'
                   '<img src="https://example.com/x.jpg"></p>')


def test_compose_is_accepted_by_the_build():
    meta = {"title": "Ahoj: svět", "slug": "ahoj-svet", "date": dt.date(2026, 10, 8),
            "headline": "Krátce.", "cover": "cover.webp", "cover_alt": "Popis", "orientation": "portrait"}
    content.check_with_build("2026-10-08-ahoj-svet", content.compose(meta, "<p>Text</p>"), "cover.webp")


# ---------- photos ----------

def test_cover_is_upright_cropped_and_without_metadata():
    files = images.cover_files(photo((4000, 3000), rotate=True, gps=True), "portrait")
    cover = Image.open(io.BytesIO(files["cover.webp"]))
    assert cover.size == (1066, 1600)               # upright 2:3, long edge 1600
    assert not cover.getexif()                       # no GPS, no camera data
    assert Image.open(io.BytesIO(files["og.jpg"])).size == (1200, 630)
    assert Image.open(io.BytesIO(files["cover-card.webp"])).height == 760


def test_small_photo_is_not_enlarged():
    name, data = images.body_photo(photo((800, 600)))
    assert Image.open(io.BytesIO(data)).size == (800, 600)
    assert name.startswith("img-") and name.endswith(".webp")


def test_not_a_photo():
    with pytest.raises(images.ImageError):
        images.cover_files(b"not an image", "portrait")


# ---------- paths ----------

@pytest.mark.parametrize("bad", ["../secret", "a/../../b", "/etc/passwd", ".git/config", ""])
def test_safe_path_refuses_escapes(bad):
    with pytest.raises(StoreError):
        safe_path(bad)


# ---------- the web app with a local folder ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(editor_app, "store", LocalStore(tmp_path))
    return TestClient(editor_app.app), tmp_path / "content" / "posts"


def form(**overrides):
    data = {"folder": "", "action": "publish", "title": "Dech před testem", "headline": "Krátce o dechu.",
            "date": "2026-10-08", "orientation": "landscape", "cover_alt": "Dívky na louce",
            "video": "", "body": "<p>Text <strong>článku</strong>.</p>"}
    data.update(overrides)
    return data


def test_create_edit_delete(client):
    http, posts = client
    r = http.post("/ulozit", data=form(), files={"cover": ("a.jpg", photo(), "image/jpeg")})
    assert r.json()["ok"], r.json()
    folder = posts / "2026-10-08-dech-pred-testem"
    assert sorted(p.name for p in folder.iterdir()) == ["cover-card.webp", "cover.webp", "index.md", "og.jpg"]

    # Same title again gets its own address
    r = http.post("/ulozit", data=form(), files={"cover": ("a.jpg", photo(), "image/jpeg")})
    assert (posts / "2026-10-08-dech-pred-testem-2").is_dir()

    # Edit: add a photo to the text, save as draft
    r = http.post("/ulozit", data=form(folder=folder.name, action="draft",
                                       body='<p>Nový text</p><p><img src="upload/0"></p>'),
                  files={"upload/0": ("foto-0", photo((900, 600)), "image/jpeg")})
    assert r.json()["ok"], r.json()
    text = (folder / "index.md").read_text()
    assert "draft: true" in text and "Nový text" in text
    body_images = [p.name for p in folder.glob("img-*.webp")]
    assert len(body_images) == 1

    # Edit again without the photo: the unused file is removed
    r = http.post("/ulozit", data=form(folder=folder.name, body="<p>Bez fotky</p>"))
    assert r.json()["ok"]
    assert not list(folder.glob("img-*.webp"))

    # Delete
    r = http.post(f"/smazat/{folder.name}", follow_redirects=False)
    assert r.status_code == 303
    assert not folder.exists()


def test_errors_are_in_czech(client):
    http, _ = client
    r = http.post("/ulozit", data=form(title="", headline="x" * 200, video="https://example.com"))
    errors = r.json()["errors"]
    assert r.status_code == 400
    assert "Doplňte název článku." in errors
    assert any("160" in e for e in errors)
    assert "Video musí být odkaz na YouTube nebo Vimeo." in errors
    assert "Vyberte titulní fotku." in errors


def test_posts_from_another_site_are_refused(client):
    http, _ = client
    r = http.post("/ulozit", data=form(), headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ---------- login ----------

PASSWORD = "spravne-heslo-123"


@pytest.fixture
def locked_client(client, monkeypatch):
    """The app as on Render: every page needs the password."""
    http, posts = client
    monkeypatch.setattr(editor_app, "settings", Settings(
        store="local", github_token=None, github_repo="o/r", github_branch="main",
        password_hash=auth.hash_password(PASSWORD), session_secret="x" * 32))
    monkeypatch.setattr(editor_app, "login_guard", auth.LoginGuard())
    return http, posts


def test_pages_need_login(locked_client):
    http, _ = locked_client
    r = http.get("/upravit/2026-01-01-a", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/prihlaseni?dalsi=/upravit/2026-01-01-a"
    assert http.post("/ulozit", data=form()).status_code == 401
    assert http.get("/media/2026-01-01-a/cover.webp").status_code == 401
    assert http.get("/healthz").text == "ok"
    assert http.get("/static/editor.css").status_code == 200


def test_login_and_logout(locked_client):
    http, _ = locked_client
    r = http.post("/prihlaseni", data={"password": "spatne", "dalsi": "/novy"})
    assert r.status_code == 401 and "Heslo nesedí." in r.text
    r = http.post("/prihlaseni", data={"password": PASSWORD, "dalsi": "/novy"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/novy"
    assert http.get("/").status_code == 200
    assert "Odhlásit" in http.get("/").text
    http.post("/odhlasit")
    assert http.get("/", follow_redirects=False).status_code == 303


def test_login_does_not_redirect_to_other_sites(locked_client):
    http, _ = locked_client
    for target in ("https://evil.example", "//evil.example", "/\\evil.example"):
        r = http.post("/prihlaseni", data={"password": PASSWORD, "dalsi": target}, follow_redirects=False)
        assert r.headers["location"] == "/"


def test_new_password_logs_everyone_out(locked_client, monkeypatch):
    http, _ = locked_client
    http.post("/prihlaseni", data={"password": PASSWORD})
    assert http.get("/", follow_redirects=False).status_code == 200
    new = editor_app.settings.__class__(**{**editor_app.settings.__dict__,
                                          "password_hash": auth.hash_password("nove-heslo-456")})
    monkeypatch.setattr(editor_app, "settings", new)
    assert http.get("/", follow_redirects=False).status_code == 303


def test_lockout_after_five_wrong_passwords(locked_client):
    http, _ = locked_client
    for _ in range(5):
        http.post("/prihlaseni", data={"password": "spatne"})
    r = http.post("/prihlaseni", data={"password": PASSWORD})
    assert r.status_code == 429 and "Příliš mnoho pokusů" in r.text


def test_guard_unlocks_after_the_wait_and_counts_all_devices():
    now = [1000.0]
    guard = auth.LoginGuard(max_failures=5, lock_seconds=900, global_max=20, clock=lambda: now[0])
    for _ in range(5):
        guard.failed("1.1.1.1")
    assert guard.seconds_locked("1.1.1.1") == 900
    assert guard.seconds_locked("2.2.2.2") == 0
    now[0] += 901
    assert guard.seconds_locked("1.1.1.1") == 0
    for i in range(20):                      # someone rotating IP addresses
        guard.failed(f"10.0.0.{i}")
    assert guard.seconds_locked("3.3.3.3") > 0


def test_github_mode_refuses_to_start_without_login(tmp_path, monkeypatch):
    from editor.config import load_settings
    env = tmp_path / ".env"
    env.write_text("EDITOR_STORE=github\nGITHUB_TOKEN=x\n")
    monkeypatch.delenv("EDITOR_PASSWORD_HASH")
    monkeypatch.delenv("SESSION_SECRET")
    monkeypatch.delenv("EDITOR_STORE")
    with pytest.raises(RuntimeError, match="editor.auth"):
        load_settings(env)


# ---------- GitHub, against a fake GitHub ----------

class FakeGitHub:
    """Just enough of GitHub's git API to test the commit logic."""

    def __init__(self, files: dict[str, bytes]):
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.commits: dict[str, dict] = {}
        tree = self._tree({p: self._blob(d) for p, d in files.items()})
        self.head = self._commit(tree, [])
        self.race = 0                        # how many ref updates to refuse

    def _sha(self, *parts) -> str:
        return hashlib.sha1(repr(parts).encode()).hexdigest()

    def _blob(self, data: bytes) -> str:
        sha = self._sha("blob", data)
        self.blobs[sha] = data
        return sha

    def _tree(self, entries: dict[str, str]) -> str:
        sha = self._sha("tree", sorted(entries.items()))
        self.trees[sha] = dict(entries)
        return sha

    def _commit(self, tree: str, parents: list[str]) -> str:
        sha = self._sha("commit", tree, parents, len(self.commits))
        self.commits[sha] = {"tree": tree, "parents": parents}
        return sha

    def files(self) -> dict[str, bytes]:
        tree = self.trees[self.commits[self.head]["tree"]]
        return {p: self.blobs[s] for p, s in tree.items()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/repos/o/r", 1)[1]
        body = json.loads(request.content) if request.content else {}
        if request.method == "GET" and path == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if request.method == "GET" and path.startswith("/git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": self.commits[path.rsplit("/", 1)[1]]["tree"]}})
        if request.method == "GET" and path.startswith("/git/trees/"):
            tree = self.trees[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"truncated": False, "tree": [
                {"path": p, "type": "blob", "sha": s} for p, s in tree.items()]})
        if request.method == "GET" and path.startswith("/git/blobs/"):
            data = self.blobs[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"content": base64.encodebytes(data).decode()})
        if request.method == "POST" and path == "/git/blobs":
            return httpx.Response(201, json={"sha": self._blob(base64.b64decode(body["content"]))})
        if request.method == "POST" and path == "/git/trees":
            entries = dict(self.trees[body["base_tree"]])
            for e in body["tree"]:
                if e["sha"] is None:
                    assert e["path"] in entries, "GitHub refuses to delete a missing path"
                    entries.pop(e["path"])
                else:
                    entries[e["path"]] = e["sha"]
            return httpx.Response(201, json={"sha": self._tree(entries)})
        if request.method == "POST" and path == "/git/commits":
            return httpx.Response(201, json={"sha": self._commit(body["tree"], body["parents"])})
        if request.method == "PATCH" and path == "/git/refs/heads/main":
            new = body["sha"]
            if self.race:                        # someone pushed in between
                self.race -= 1
                other = self._commit(self.commits[self.head]["tree"], [self.head])
                self.trees[self.commits[other]["tree"]]["content/posts/x/index.md"] = self._blob(b"---\n---\n")
                self.head = other
            if self.commits[new]["parents"] != [self.head]:
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            self.head = new
            return httpx.Response(200, json={"object": {"sha": new}})
        return httpx.Response(404)


def github(fake: FakeGitHub) -> GitHubStore:
    return GitHubStore("token", "o/r", "main", transport=httpx.MockTransport(fake.handler))


def test_github_commit_is_atomic_and_survives_a_race():
    fake = FakeGitHub({"content/posts/a/index.md": b"old", "content/posts/a/old.webp": b"x",
                       "index.html": b"<html>"})
    fake.race = 1
    store = github(fake)

    async def run():
        snap = await store.snapshot()
        assert snap.files_in("a") == ["index.md", "old.webp"]
        return await store.commit("Test", {"a/index.md": b"new", "a/img.webp": b"y"},
                                  ["a/old.webp", "a/never-existed.webp"])
    sha = asyncio.run(run())

    files = fake.files()
    assert sha == fake.head
    assert files["content/posts/a/index.md"] == b"new"
    assert "content/posts/a/old.webp" not in files
    assert files["index.html"] == b"<html>"            # the rest of the site untouched
    assert "content/posts/x/index.md" in files         # the other person's change kept


def test_github_bad_token_gives_a_clear_message():
    store = GitHubStore("bad", "o/r", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(StoreError, match="token"):
        asyncio.run(store.snapshot())

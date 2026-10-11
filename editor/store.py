"""Where posts are read from and saved to.

Two stores share one interface, so the rest of the editor never needs to
know which one it talks to:

  LocalStore   files in content/posts/ on this computer (for trying things out)
  GitHubStore  the repository on GitHub; every save is one atomic commit

All paths passed in and out are relative to content/posts/,
for example "2026-10-08-dech-pred-testem/index.md".
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

import httpx

POSTS_PATH = "content/posts"


class StoreError(RuntimeError):
    """Saving or loading failed. The message is shown to Petra."""


@dataclass
class Snapshot:
    """Every file under content/posts/ at one moment."""
    files: set[str]

    def folders(self) -> list[str]:
        return sorted({p.split("/")[0] for p in self.files if p.endswith("/index.md")
                       and p.count("/") == 1})

    def files_in(self, folder: str) -> list[str]:
        prefix = folder + "/"
        return sorted(p[len(prefix):] for p in self.files if p.startswith(prefix))


class Store(Protocol):
    async def snapshot(self) -> Snapshot: ...
    async def read(self, path: str) -> bytes: ...
    async def read_many(self, paths: list[str]) -> list[bytes]: ...
    async def commit(self, message: str, put: dict[str, bytes], delete: list[str]) -> str | None: ...
    async def build_status(self, commit: str) -> str | None: ...


def safe_path(path: str) -> str:
    """Refuse anything that could step outside content/posts/."""
    parts = PurePosixPath(path).parts
    if not parts or any(p in ("", ".", "..") or p.startswith(".") for p in parts) or path.startswith("/"):
        raise StoreError(f"Neplatná cesta: {path}")
    return path


# ---------- local folder ----------

class LocalStore:
    def __init__(self, repo_root: Path):
        self.root = repo_root / POSTS_PATH

    async def snapshot(self) -> Snapshot:
        if not self.root.exists():
            return Snapshot(set())
        return Snapshot({p.relative_to(self.root).as_posix()
                         for p in self.root.rglob("*") if p.is_file()
                         and not p.name.startswith(".")})

    async def read(self, path: str) -> bytes:
        file = self.root / safe_path(path)
        if not file.is_file():
            raise StoreError(f"Soubor {path} neexistuje.")
        return file.read_bytes()

    async def read_many(self, paths: list[str]) -> list[bytes]:
        return [await self.read(p) for p in paths]

    async def commit(self, message: str, put: dict[str, bytes], delete: list[str]) -> None:
        for path, data in put.items():
            file = self.root / safe_path(path)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        for path in delete:
            file = self.root / safe_path(path)
            file.unlink(missing_ok=True)
            if file.parent != self.root and not any(file.parent.iterdir()):
                file.parent.rmdir()            # remove the emptied post folder
        return None

    async def build_status(self, commit: str) -> None:
        return None


# ---------- GitHub ----------

class GitHubStore:
    """Talks to the GitHub REST API with a fine-grained token.

    A save never pushes over someone else's work: the branch is only moved
    forward from the commit it currently points to. If it moved in the
    meantime (you pushed from VS Code), the commit is rebuilt on top of the
    new state and tried again.
    """

    API = "https://api.github.com"
    RETRIES = 3

    def __init__(self, token: str, repo: str, branch: str = "main",
                 transport: httpx.AsyncBaseTransport | None = None):
        self.repo = repo
        self.branch = branch
        self.client = httpx.AsyncClient(
            base_url=f"{self.API}/repos/{repo}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30, transport=transport)
        self._blob_cache: dict[str, bytes] = {}   # blob sha -> content; shas never change
        self._shas: dict[str, str] = {}           # path -> blob sha from the last snapshot

    async def _call(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise StoreError("GitHub teď neodpovídá. Zkuste to za chvíli znovu.") from None
        if response.status_code == 401:
            raise StoreError("Přístupový token pro GitHub je neplatný nebo vypršel.")
        if response.status_code in (403, 404) and not url.startswith("/git/refs"):
            raise StoreError("Token nemá přístup k repozitáři (nebo byl překročen limit GitHubu).")
        return response

    @staticmethod
    def _ok(response: httpx.Response) -> dict:
        if response.is_error:
            raise StoreError(f"GitHub vrátil chybu {response.status_code}.")
        return response.json()

    async def _head(self) -> tuple[str, str]:
        """(commit sha, tree sha) the branch points to right now."""
        ref = self._ok(await self._call("GET", f"/git/ref/heads/{self.branch}"))
        commit_sha = ref["object"]["sha"]
        commit = self._ok(await self._call("GET", f"/git/commits/{commit_sha}"))
        return commit_sha, commit["tree"]["sha"]

    async def _tree(self, tree_sha: str) -> dict[str, str]:
        data = self._ok(await self._call("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"}))
        if data.get("truncated"):
            raise StoreError("Repozitář je příliš velký na načtení najednou.")
        prefix = POSTS_PATH + "/"
        return {item["path"][len(prefix):]: item["sha"] for item in data["tree"]
                if item["type"] == "blob" and item["path"].startswith(prefix)}

    async def snapshot(self) -> Snapshot:
        _, tree_sha = await self._head()
        self._shas = await self._tree(tree_sha)
        return Snapshot(set(self._shas))

    async def read(self, path: str) -> bytes:
        safe_path(path)
        if path not in self._shas:
            await self.snapshot()
        sha = self._shas.get(path)
        if sha is None:
            raise StoreError(f"Soubor {path} neexistuje.")
        if sha not in self._blob_cache:
            blob = self._ok(await self._call("GET", f"/git/blobs/{sha}"))
            self._blob_cache[sha] = base64.b64decode(blob["content"])
        return self._blob_cache[sha]

    async def read_many(self, paths: list[str]) -> list[bytes]:
        """Read several files at once (used for the post list)."""
        limit = asyncio.Semaphore(8)

        async def one(path: str) -> bytes:
            async with limit:
                return await self.read(path)
        return await asyncio.gather(*(one(p) for p in paths))

    async def commit(self, message: str, put: dict[str, bytes], delete: list[str]) -> str:
        # 1. Upload each new file once. Blobs stay valid across retries.
        blobs = {}
        for path, data in put.items():
            blob = self._ok(await self._call("POST", "/git/blobs", json={
                "content": base64.b64encode(data).decode(), "encoding": "base64"}))
            blobs[safe_path(path)] = blob["sha"]

        for _ in range(self.RETRIES):
            # 2. Start from wherever the branch is right now.
            parent, base_tree = await self._head()
            existing = await self._tree(base_tree)
            entries = [{"path": f"{POSTS_PATH}/{p}", "mode": "100644", "type": "blob", "sha": s}
                       for p, s in blobs.items()]
            entries += [{"path": f"{POSTS_PATH}/{safe_path(p)}", "mode": "100644",
                         "type": "blob", "sha": None}
                        for p in delete if p in existing and p not in blobs]
            # 3. One tree and one commit holding every change.
            tree = self._ok(await self._call("POST", "/git/trees",
                                             json={"base_tree": base_tree, "tree": entries}))
            commit = self._ok(await self._call("POST", "/git/commits", json={
                "message": message, "tree": tree["sha"], "parents": [parent]}))
            # 4. Move the branch forward. force=False refuses if it moved meanwhile.
            moved = await self._call("PATCH", f"/git/refs/heads/{self.branch}",
                                     json={"sha": commit["sha"], "force": False})
            if moved.status_code == 200:
                return commit["sha"]
            if moved.status_code != 422:
                raise StoreError(f"GitHub odmítl uložení (chyba {moved.status_code}).")
        raise StoreError("Někdo jiný právě ukládal. Zkuste to prosím znovu.")

    async def build_status(self, commit: str) -> str:
        """'waiting', 'building', 'done' or 'failed' for the deploy of this commit."""
        data = self._ok(await self._call("GET", "/actions/runs",
                                         params={"head_sha": commit, "per_page": 5}))
        runs = data.get("workflow_runs", [])
        if not runs:
            return "waiting"
        run = runs[0]
        if run["status"] != "completed":
            return "building"
        return "done" if run["conclusion"] == "success" else "failed"

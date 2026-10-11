"""Editor settings, read from environment variables or a local .env file.

    EDITOR_STORE    "local" (default) writes posts into this folder,
                    "github" saves them straight to GitHub as commits
    GITHUB_TOKEN    fine-grained token, only needed for "github"
    GITHUB_REPO     owner/name of the repository
    GITHUB_BRANCH   branch the site is built from

The .env file is listed in .gitignore, so the token never reaches GitHub.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    store: str
    github_token: str | None
    github_repo: str
    github_branch: str


def read_env_file(path: Path) -> dict[str, str]:
    """Parse simple KEY=value lines. Blank lines and # comments are skipped."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(env_file: Path = REPO_ROOT / ".env") -> Settings:
    values = read_env_file(env_file) | os.environ   # real env vars win
    store = values.get("EDITOR_STORE", "local").lower()
    if store not in ("local", "github"):
        raise RuntimeError("EDITOR_STORE must be 'local' or 'github'")
    token = values.get("GITHUB_TOKEN") or None
    if store == "github" and not token:
        raise RuntimeError("EDITOR_STORE=github needs GITHUB_TOKEN in .env")
    return Settings(
        store=store,
        github_token=token,
        github_repo=values.get("GITHUB_REPO", "JogaProTeens/jogaproteens_stranky"),
        github_branch=values.get("GITHUB_BRANCH", "main"),
    )

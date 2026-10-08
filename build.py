"""Build the static site into _site/ from templates/ and static/."""
from pathlib import Path
import shutil

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).parent
OUT = ROOT / "_site"


def main() -> None:
    # Start from a clean folder so deleted files never linger online.
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "static", OUT)

    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=True,             # escapes user text, blocks injected HTML
        undefined=StrictUndefined,   # a typo in a template fails the build loudly
        keep_trailing_newline=True,  # output matches the source byte for byte
    )
    html = env.get_template("index.html").render()
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"Built {OUT}")


if __name__ == "__main__":
    main()
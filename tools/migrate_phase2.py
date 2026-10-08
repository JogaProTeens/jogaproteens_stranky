"""One-time Phase 2 migration. Run once from the project root:

    python tools/migrate_phase2.py

1. Moves the page's CSS out of templates/index.html into static/css/site.css,
   so post pages can share it.
2. Swaps the Inspirace placeholder box for the blog carousel include.
3. Removes static/sitemap.xml, because build.py now generates it.

It refuses to run twice and changes nothing if something looks unexpected.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "templates" / "index.html"
CSS_OUT = ROOT / "static" / "css" / "site.css"
OLD_SITEMAP = ROOT / "static" / "sitemap.xml"

PLACEHOLDER = re.compile(
    r'\s*<div class="cms-slot">\s*<span class="cms-label">Připravujeme</span>\s*'
    r'<p>Obsah této sekce bude spravovaný.*?</p>\s*</div>',
    re.DOTALL,
)


def fail(message: str) -> None:
    print(f"STOP: {message}\nNothing was changed.")
    sys.exit(1)


def main() -> None:
    html = INDEX.read_text(encoding="utf-8")

    if CSS_OUT.exists() or "/css/site.css" in html:
        fail("this migration has already been run.")

    # The page has exactly one <style> block; everything inside it moves out.
    styles = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    if len(styles) != 1:
        fail(f"expected 1 <style> block in index.html, found {len(styles)}.")
    css = styles[0].strip("\n")

    # Inside /css/site.css a relative font path would point to /css/fonts/.
    css = css.replace('url("fonts/', 'url("/fonts/')

    if len(PLACEHOLDER.findall(html)) != 1:
        fail("could not find the Inspirace 'Připravujeme' box exactly once.")

    html = re.sub(
        r"<style>.*?</style>",
        '<link rel="stylesheet" href="/css/site.css">\n'
        '<link rel="stylesheet" href="/css/blog.css">',
        html,
        flags=re.DOTALL,
    )
    html = PLACEHOLDER.sub('\n    {% include "_inspirace.html" %}', html)

    CSS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CSS_OUT.write_text(css + "\n", encoding="utf-8")
    INDEX.write_text(html, encoding="utf-8")
    if OLD_SITEMAP.exists():
        OLD_SITEMAP.unlink()

    print(f"Moved {len(css.splitlines())} lines of CSS to static/css/site.css")
    print("Inspirace now includes templates/_inspirace.html")
    print("Removed static/sitemap.xml (build.py generates it now)")


if __name__ == "__main__":
    main()

"""The repository's own promises: images carry nothing personal, docs don't dead-end.

Two things that silently rot in any project and actively hurt this one:

* **Showcase images.** They are generated, and generation once leaked a username and real
  MCP server names (``fix`` reads your home directory regardless of ``--data-dir``).
  Every committed SVG is scanned here for home-directory paths.
* **Doc links.** The README moved most of its detail into ``docs/``, and the README is
  also what PyPI renders, so its links are absolute GitHub URLs. Every relative link,
  every absolute link into this repo, and every ``#anchor`` must land on something real.

These files are not in the source distribution, so the module skips when run from one.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "showcase"
DOCS = [
    ROOT / "README.md",
    ROOT / "SHOWCASE.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").glob("*.md")),
]
REPO = "Priyanshu-byte-coder/contextrot"

if not ASSETS.is_dir():  # pragma: no cover — running from an sdist
    pytest.skip("repository-only files are not in the source distribution", allow_module_level=True)

# Absolute paths into somebody's home directory. The synthetic corpus lives under
# /home/dev/, so that one is allowed.
_HOME_PATH = re.compile(r"[A-Za-z]:\\+Users\\+|/Users/[^/\s]+/|/home/(?!dev/)[^/\s<]+/")

# Markdown links and HTML src/href attributes.
_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
_HTML_LINK = re.compile(r'(?:src|href|srcset)="([^"]+)"')


def _svgs() -> list[Path]:
    return sorted(ASSETS.glob("*.svg"))


@pytest.mark.parametrize("svg", _svgs(), ids=lambda p: p.name)
def test_showcase_svg_is_well_formed(svg: Path) -> None:
    ET.parse(svg)


@pytest.mark.parametrize("svg", _svgs(), ids=lambda p: p.name)
def test_showcase_svg_contains_no_home_directory(svg: Path) -> None:
    text = re.sub(r"<[^>]+>", "", svg.read_text(encoding="utf-8"))
    match = _HOME_PATH.search(text)
    assert match is None, f"{svg.name} contains a home-directory path: {match.group(0)!r}"


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _anchors(md: Path) -> set[str]:
    out: set[str] = set()
    for line in md.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#{1,6}\s+(.*)", line)
        if m:
            out.add(_slug(m.group(1)))
    return out


def _links(md: Path) -> list[str]:
    text = md.read_text(encoding="utf-8")
    # Code blocks hold example output, not links.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return _MD_LINK.findall(text) + _HTML_LINK.findall(text)


def _resolve(md: Path, link: str) -> tuple[Path, str] | None:
    """(file, anchor) for a link that points into this repo, else None."""
    for prefix in (
        f"https://github.com/{REPO}/blob/main/",
        f"https://raw.githubusercontent.com/{REPO}/main/",
    ):
        if link.startswith(prefix):
            path, _, anchor = link[len(prefix):].partition("#")
            return ROOT / path, anchor
    if re.match(r"[a-z]+://|mailto:", link):
        return None  # elsewhere on the web; not ours to check offline
    path, _, anchor = link.partition("#")
    target = md if not path else (md.parent / path)
    return target, anchor


@pytest.mark.parametrize("md", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_link_in_the_docs_resolves(md: Path) -> None:
    broken = []
    for link in _links(md):
        resolved = _resolve(md, link)
        if resolved is None:
            continue
        target, anchor = resolved
        if not target.exists():
            shown = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target
            broken.append(f"{link} -> missing {shown}")
            continue
        if anchor and target.suffix == ".md" and anchor not in _anchors(target):
            broken.append(f"{link} -> no heading #{anchor} in {target.name}")
    assert not broken, "\n".join(broken)


def test_the_readme_links_work_on_pypi_too() -> None:
    """PyPI renders README.md out of context, so relative links there break."""
    relative = [
        link
        for link in _links(ROOT / "README.md")
        if not re.match(r"[a-z]+://|#|mailto:", link)
    ]
    assert not relative, f"relative links in README.md break on PyPI: {relative}"


def test_every_showcase_image_is_used_somewhere() -> None:
    """An image nothing links to is a stale screenshot waiting to mislead someone."""
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in DOCS)
    unused = [p.name for p in ASSETS.iterdir() if p.name not in corpus]
    assert not unused, f"unreferenced showcase images: {unused}"

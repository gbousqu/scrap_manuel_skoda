"""
Assemble le manuel HTML local et génère un PDF complet via Playwright.

Document HTML unique : sommaire cliquable + liens internes entre chapitres.

Usage :
    python build_manual_pdf.py --manual elroq
    python build_manual_pdf.py --manual elroq --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from manual_paths import ManualPaths, VIEWER_DIR, add_manual_arg, resolve_manual_paths

# Rempli dans main() selon --manual
_paths: ManualPaths | None = None

SCALE_IMAGES_JS = """
async () => {
  function getDensityFactor(src) {
    const match = (src || "").match(/_(1x|2x|3x)\\.(png|svg|jpe?g|webp)/i);
    return match ? parseInt(match[1], 10) : 1;
  }
  function isFixedIcon(img) {
    const role = img.getAttribute("data-role");
    return img.classList.contains("icon") || role === "icon" || role === "safety-alert-symbol";
  }
  function isSymbolImage(img) {
    return img.classList.contains("symbol") || img.getAttribute("data-role") === "symbol";
  }
  function isBlockImage(img) {
    return img.classList.contains("blockimage");
  }

  const imgs = Array.from(document.querySelectorAll("img"));
  document.querySelectorAll("a.fancybox[data-href] img").forEach((img) => {
    if (!img.getAttribute("src")) {
      img.setAttribute("src", img.closest("a").getAttribute("data-href"));
    }
  });
  for (const img of imgs) {
    if (!img.getAttribute("src") && img.dataset.src) {
      img.setAttribute("src", img.dataset.src);
    }
  }

  await Promise.all(
    imgs.map((img) => {
      if (img.complete) return Promise.resolve();
      return new Promise((resolve) => {
        img.addEventListener("load", resolve, { once: true });
        img.addEventListener("error", resolve, { once: true });
      });
    })
  );

  for (const img of imgs) {
    if (isFixedIcon(img) || isBlockImage(img) || isSymbolImage(img)) continue;
    if (!img.naturalWidth) continue;

    const src = img.currentSrc || img.src || img.dataset.src || "";
    const density = getDensityFactor(src);
    const inFigure = !!img.closest("figure, [data-type='illu']");

    if (img.naturalWidth >= 600) continue;

    if (inFigure && density > 1 && img.naturalWidth < 600) {
      const displayW = Math.round(img.naturalWidth / density);
      img.style.width = `${displayW}px`;
      img.style.height = "auto";
      img.style.maxWidth = "100%";
    }
  }
}
"""


from playwright.async_api import async_playwright

COMBINED_HTML_NAME = "manual_full.html"
CSS_FILE = VIEWER_DIR / "pdf-print.css"


def mp() -> ManualPaths:
    if _paths is None:
        raise RuntimeError("Manuel non configuré — utilisez --manual")
    return _paths


def write_status(state: str, **extra) -> None:
    payload = {
        "state": state,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    mp().pdf_status.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def chapter_anchor(index: int) -> str:
    return f"ch-{index:04d}"


def build_topic_anchor_map(topics: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for i, topic in enumerate(topics, start=1):
        topic_id = topic.get("topicId")
        if topic_id:
            mapping[topic_id] = chapter_anchor(i)
    return mapping


def strip_chapter_header(raw: str) -> str:
    raw = re.sub(r"^<!--.*?-->\s*", "", raw, count=1, flags=re.DOTALL)
    raw = re.sub(r"^<h1>.*?</h1>\s*", "", raw, count=1, flags=re.DOTALL | re.IGNORECASE)
    return raw.strip()


def fix_lazy_images(body: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r'\ssrc="[^"]+"', tag):
            return tag
        data_src = re.search(r'data-src="([^"]+)"', tag)
        if not data_src:
            return tag
        return tag.replace("<img", f'<img src="{data_src.group(1)}"', 1)

    return re.sub(r"<img\b[^>]*>", repl, body)


def rewrite_internal_links(body: str, topic_to_anchor: dict[str, str]) -> str:
    """Convertit #topic/{id} en ancres PDF #ch-NNNN."""
    for topic_id, anchor in topic_to_anchor.items():
        body = body.replace(f"#topic/{topic_id}", f"#{anchor}")
        body = body.replace(f"#topic/{topic_id.lower()}", f"#{anchor}")

    def fix_bare_hash(match: re.Match[str]) -> str:
        topic_id = match.group(1)
        anchor = topic_to_anchor.get(topic_id)
        return f'href="#{anchor}"' if anchor else match.group(0)

    body = re.sub(
        r'href="#"([^>]*?)data-topic-id="([^"]+)"',
        lambda m: (
            f'href="#{topic_to_anchor[m.group(2)]}"{m.group(1)}data-topic-id="{m.group(2)}"'
            if topic_to_anchor.get(m.group(2))
            else m.group(0)
        ),
        body,
    )
    body = re.sub(
        r'data-topic-id="([^"]+)"([^>]*?)href="#"(?!topic/)',
        fix_bare_hash,
        body,
    )
    return body


def prepare_chapter_html(raw: str, topic_to_anchor: dict[str, str]) -> str:
    body = strip_chapter_header(raw)
    body = fix_lazy_images(body)
    body = rewrite_internal_links(body, topic_to_anchor)
    return body


def render_toc_nodes(
    nodes: list[dict],
    topic_to_anchor: dict[str, str],
    depth: int = 0,
) -> str:
    """Reproduit la structure du sidebar (dossiers + chapitres cliquables)."""
    parts: list[str] = []

    for node in nodes:
        title = html.escape(node.get("title") or "")
        children = node.get("children") or []
        node_depth = node.get("depth", depth)
        topic_id = node.get("topicId")
        anchor = topic_to_anchor.get(topic_id) if topic_id else None
        has_children = bool(children)

        if has_children:
            if anchor:
                parts.append(
                    f'<li class="pdf-toc-item depth-{node_depth}">'
                    f'<a href="#{anchor}">{title}</a><ul>'
                )
            else:
                parts.append(
                    f'<li class="pdf-toc-folder depth-{node_depth}">'
                    f'<span class="pdf-toc-label">{title}</span><ul>'
                )
            parts.append(render_toc_nodes(children, topic_to_anchor, node_depth + 1))
            parts.append("</ul></li>")
        elif anchor:
            parts.append(
                f'<li class="pdf-toc-item depth-{node_depth}">'
                f'<a href="#{anchor}">{title}</a></li>'
            )

    return "".join(parts)


def build_toc_html(manifest: dict, topic_to_anchor: dict[str, str]) -> str:
    tree = manifest.get("tree") or []
    if not tree:
        return ""

    items = render_toc_nodes(tree, topic_to_anchor)
    return f"""
    <nav class="pdf-toc" id="sommaire">
      <h2>Sommaire</h2>
      <ul class="pdf-toc-root">{items}</ul>
    </nav>"""


def load_print_css() -> str:
    if CSS_FILE.exists():
        return CSS_FILE.read_text(encoding="utf-8")
    return ""


def build_full_html(manifest: dict, topics: list[dict], topic_to_anchor: dict[str, str]) -> str:
    title = manifest.get("title") or "Manuel Škoda"
    release_label = manifest.get("releaseDateLabel")
    css = load_print_css()
    sections: list[str] = []

    for i, topic in enumerate(topics, start=1):
        chapter_file = topic.get("file")
        if not chapter_file:
            continue
        path = mp().chapters / chapter_file
        if not path.exists():
            raise FileNotFoundError(f"Chapitre introuvable : {path}")

        anchor = chapter_anchor(i)
        body = prepare_chapter_html(path.read_text(encoding="utf-8"), topic_to_anchor)
        breadcrumb = html.escape(" › ".join(topic.get("path") or [topic.get("title", "")]))
        chapter_title = html.escape(topic.get("title") or "")

        sections.append(
            f"""<section class="pdf-chapter" id="{anchor}">
  <header class="pdf-chapter-head">
    <p class="pdf-breadcrumb">{breadcrumb}</p>
    <h2>{chapter_title}</h2>
  </header>
  <div class="pdf-chapter-body">{body}</div>
</section>"""
        )

        if i % 50 == 0 or i == len(topics):
            write_status(
                "building",
                phase="html",
                progress=i,
                total=len(topics),
                message=f"Assemblage HTML… {i}/{len(topics)}",
            )

    toc = build_toc_html(manifest, topic_to_anchor)
    edition_line = (
        f'<p>Édition du {html.escape(release_label)}</p>' if release_label else ""
    )
    cover = f"""
    <header class="pdf-cover" id="couverture">
      <h1>{html.escape(title)}</h1>
      <p>Manuel d'utilisation — version locale</p>
      {edition_line}
      <p class="pdf-meta">{len(topics)} chapitres · <a href="#sommaire">Sommaire</a></p>
    </header>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>{html.escape(title)} — PDF</title>
  <style>{css}</style>
</head>
<body>
  <article id="manual-pdf">{cover}{toc}{"".join(sections)}</article>
</body>
</html>"""


async def render_pdf(html_path: Path, pdf_path: Path) -> None:
    write_status("building", phase="pdf", progress=0, total=1, message="Rendu PDF…")
    file_url = html_path.resolve().as_uri()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(file_url, wait_until="load", timeout=300_000)
        await page.evaluate(SCALE_IMAGES_JS)
        await page.emulate_media(media="print")
        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "12mm", "right": "12mm", "bottom": "14mm", "left": "12mm"},
            display_header_footer=True,
            header_template="<span></span>",
            footer_template=(
                '<div style="width:100%;font-size:8px;color:#666;text-align:center;'
                'font-family:Segoe UI,sans-serif;">'
                '<span class="pageNumber"></span> / <span class="totalPages"></span>'
                "</div>"
            ),
        )
        await browser.close()


async def render_full_manual(manifest: dict, topics: list[dict]) -> None:
    paths = mp()
    paths.print_dir.mkdir(parents=True, exist_ok=True)
    combined_html = paths.print_dir / COMBINED_HTML_NAME
    topic_to_anchor = build_topic_anchor_map(topics)

    write_status("building", phase="html", progress=0, total=len(topics), message="Assemblage HTML…")
    combined_html.write_text(
        build_full_html(manifest, topics, topic_to_anchor),
        encoding="utf-8",
    )

    tmp_path = paths.pdf.with_suffix(".tmp.pdf")
    await render_pdf(combined_html, tmp_path)

    try:
        if paths.pdf.exists():
            paths.pdf.unlink()
        tmp_path.replace(paths.pdf)
    except OSError as exc:
        raise OSError(
            f"Impossible d'écraser {paths.pdf.name} — fermez le PDF s'il est ouvert dans un lecteur."
        ) from exc


def main() -> int:
    global _paths

    parser = argparse.ArgumentParser(description="Génère le PDF complet du manuel local.")
    add_manual_arg(parser)
    parser.add_argument("--limit", type=int, default=0, help="Limiter le nombre de chapitres (test)")
    args = parser.parse_args()

    try:
        _paths = resolve_manual_paths(args.manual)
        manifest_file = _paths.manifest
        pdf_file = _paths.pdf

        if not manifest_file.exists():
            raise FileNotFoundError("manifest.json introuvable — scrapez d'abord le manuel.")

        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        topics = manifest.get("flatTopics") or []
        if not topics:
            raise RuntimeError("Aucun chapitre dans manifest.json")
        if args.limit > 0:
            topics = topics[: args.limit]

        total = len(topics)
        asyncio.run(render_full_manual(manifest, topics))

        size_mb = pdf_file.stat().st_size / (1024 * 1024)
        write_status(
            "done",
            file=pdf_file.name,
            sizeMb=round(size_mb, 2),
            chapters=total,
            message="PDF prêt.",
        )
        print(f"PDF généré : {pdf_file} ({size_mb:.1f} Mo, {total} chapitres)")
        return 0
    except Exception as exc:
        if _paths is not None:
            write_status("error", message=str(exc))
        print(f"Erreur PDF : {exc}", file=sys.stderr)
        return 1
    finally:
        if _paths is not None and _paths.pdf_lock.exists():
            _paths.pdf_lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())

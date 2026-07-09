"""
Post-traitement des chapitres déjà scrapés : images, liens, index de recherche, manifest.

Usage :
    python postprocess_manual.py --manual elroq
    python postprocess_manual.py --manual elroq --limit 10
    python postprocess_manual.py --manual elroq --links-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

from manual_paths import ManualPaths, add_manual_arg, resolve_manual_paths, viewer_url
from manual_postprocess import (
    LinkResolver,
    add_breadcrumb_paths,
    build_manifest,
    build_search_index,
    parse_topic_trees,
    process_html,
    write_manifest,
    write_search_index,
)
from scrape_manual_skoda import (
    BASE_URL,
    MANUAL_API_BASE,
    MANUAL_LANG_LABEL,
    accept_cookies,
    fetch_topic,
    fill_vin_form,
    launch_scraper_browser,
    resolve_vin,
)


def load_root_trees(paths: ManualPaths) -> tuple[list, list]:
    sommaire_tree = paths.root / "sommaire_tree.json"
    if sommaire_tree.exists():
        tree = json.loads(sommaire_tree.read_text(encoding="utf-8"))
        sommaire = paths.root / "sommaire.json"
        if sommaire.exists():
            flat = json.loads(sommaire.read_text(encoding="utf-8"))
            return flat, tree
        return [], tree

    if paths.manifest.exists():
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        tree = manifest.get("tree") or []
        flat = manifest.get("flatTopics") or []
        if tree:
            return flat, tree

    for json_file in sorted(paths.network_log.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if data.get("trees"):
                return parse_topic_trees(data["trees"])
        except Exception:
            continue

    raise FileNotFoundError(
        "Arborescence introuvable. Conservez sommaire_tree.json ou relancez le scrape."
    )


async def load_root_trees_async(paths: ManualPaths, page=None) -> tuple[list, list]:
    try:
        return load_root_trees(paths)
    except FileNotFoundError:
        pass

    if page is not None:
        search_url = (
            f"{MANUAL_API_BASE}/web/V6/search"
            f"?query=&facetfilters=topic-type_|_welcome&lang=fr_FR&page=0&pageSize=20"
        )
        response = await page.context.request.get(search_url)
        if response.ok:
            data = await response.json()
            root_id = data["results"][0]["topicId"]
            topic_data = await fetch_topic(page, root_id)
            flat, tree = parse_topic_trees(topic_data.get("trees") or [])
            if flat:
                return flat, tree

    raise FileNotFoundError(
        "Arborescence introuvable. Conservez sommaire_tree.json ou relancez le scrape."
    )


async def postprocess(paths: ManualPaths, limit: int = 0, links_only: bool = False):
    paths.media.mkdir(exist_ok=True)

    async with async_playwright() as p:
        context, page = await launch_scraper_browser(p, headless=True)

        print("Authentification VIN pour télécharger les images…")
        await page.goto(BASE_URL, wait_until="networkidle")
        await accept_cookies(page)
        vin = await resolve_vin(page, interactive=False)
        await fill_vin_form(page, vin, MANUAL_LANG_LABEL)

        flat_topics, tree = await load_root_trees_async(paths, page)
        add_breadcrumb_paths(tree)

        if paths.scraped_index.exists():
            scraped_index = json.loads(paths.scraped_index.read_text(encoding="utf-8"))
        else:
            scraped_index = []
            for i, ch in enumerate(sorted(paths.chapters.glob("*.html")), start=1):
                m = re.search(r"topicId:\s*([a-f0-9_]+)", ch.read_text(encoding="utf-8")[:300])
                if m:
                    scraped_index.append({
                        "index": i,
                        "topicId": m.group(1),
                        "file": f"chapters/{ch.name}",
                        "title": ch.stem,
                    })

        topic_ids = {t["topicId"] for t in flat_topics}
        link_resolver = LinkResolver(tree, flat_topics)
        files = sorted(paths.chapters.glob("*.html"))
        if limit > 0:
            files = files[:limit]

        media_cache: dict[str, str] = {}
        request = page.context.request

        for i, path in enumerate(files, start=1):
            text = path.read_text(encoding="utf-8")
            processed = await process_html(
                text,
                request,
                paths.media,
                media_cache,
                topic_ids,
                link_resolver=link_resolver,
                links_only=links_only,
            )
            path.write_text(processed, encoding="utf-8")
            print(f"[{i}/{len(files)}] {path.name} — {len(media_cache)} images en cache")

        await context.close()

    title = "Manuel Škoda"
    if paths.meta.exists():
        try:
            title = json.loads(paths.meta.read_text(encoding="utf-8")).get("title", title)
        except Exception:
            pass
    elif paths.manifest.exists():
        try:
            title = json.loads(paths.manifest.read_text(encoding="utf-8")).get("title", title)
        except Exception:
            pass

    manifest = build_manifest(tree, flat_topics, scraped_index, vehicle_title=title)
    write_manifest(paths.root, manifest)
    search_index = build_search_index(paths.root, manifest)
    write_search_index(paths.root, search_index)

    (paths.root / "sommaire.json").write_text(
        json.dumps(flat_topics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (paths.root / "sommaire_tree.json").write_text(
        json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nTerminé : {len(files)} chapitres traités, {len(media_cache)} images")
    print(f"Viewer : {viewer_url(paths.slug)}")
    print(f"Manifest : {paths.manifest}")
    print(f"Recherche : {paths.search_index} ({search_index['topicCount']} pages)")


def main():
    parser = argparse.ArgumentParser()
    add_manual_arg(parser)
    parser.add_argument("--limit", type=int, default=0, help="Limiter le nombre de fichiers")
    parser.add_argument("--links-only", action="store_true", help="Réécrire les liens sans retélécharger les images")
    args = parser.parse_args()
    paths = resolve_manual_paths(args.manual)
    asyncio.run(postprocess(paths, limit=args.limit, links_only=args.links_only))


if __name__ == "__main__":
    main()

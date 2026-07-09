"""Traitement HTML, médias et manifest pour le manuel scrapé."""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

MEDIA_URL_RE = re.compile(
    r"https://digital-manual\.skoda-auto\.com/default/public/media\?[^\"'<>\s]+",
    re.IGNORECASE,
)
TOPIC_ID_IN_LINK_RE = re.compile(r"([a-f0-9]{32}_\d+_fr_FR)")
TOPICLINK_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bclass="[^"]*topiclink[^"]*"[^>]*>.*?</a>',
    re.DOTALL | re.IGNORECASE,
)
TABLE_CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
DD_BLOCK_RE = re.compile(r"<dd\b[^>]*>(.*?)</dd>", re.DOTALL | re.IGNORECASE)

# Libellés du lien ou du contexte → titres dans l'arborescence
TITLE_ALIASES: dict[str, str] = {}


def clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title).strip()


def normalize_title(title: str) -> str:
    text = re.sub(r"\s+", " ", clean_title(title)).lower()
    return text.replace("–", "-").replace("—", "-").replace("’", "'")


def _register_aliases() -> None:
    pairs = [
        ("Raclette", "Grattoir dans le capot arrière"),
        ("Pare-soleil pour les vitres arrière", "Pare-soleils pour les portes arrière"),
        ("Phonebox", "Phone box"),
        ("USB avant/arrière", "Ports USB"),
        ("Capteurs et caméras", "Maintenir les capteurs et les caméras en bon état de marche"),
        (
            "Fonction allumage automatique des phares",
            "Fonction de commutation automatique des phares",
        ),
        ("Assistant de feux de route", "Assistant de feux de route Light Assist"),
        ("Œillet de remorquage et remorquage", "Remorquage"),
        ("Sécurité enfants dans la porte", "Protection pour les enfants aux portes arrières"),
        ("Coffre - à commande électrique", "Coffre – à commande électrique"),
        (
            "Coffre - à commande manuelle",
            "Capot du coffre à bagages - à commande manuelle",
        ),
        ("Climatisation automatique Climatronic", "Climatiseur automatique Climatronic"),
        (
            "Régulateur automatique d'espacement (ACC)",
            "Régulateur de distance automatique (ACC)",
        ),
        ("Antibrouillard arrière", "Feux de brouillard arrière"),
        ("In-Car Shop", "Shop"),
        ("À propos des témoins de contrôle", "Témoins de contrôle"),
        (
            "Affichage tête haute avec réalité augmentée",
            "Affichage Head-up avec réalité augmentée",
        ),
        ("Feux de route et appel de phare", "Feu de route et appel de phare"),
        ("Mettre le contact", "Mettre/couper le contact"),
        ("Mise à jour du système en ligne", "Mise à jour du système"),
        ("Services Škoda Connect", "Services du Škoda Connect"),
        ("Câble de recharge universel", "Câble de recharge universel Mode 2"),
        ("Câble de recharge, mode 2", "Câble de recharge Mode 2"),
        ("Câble de recharge, mode 3", "Câble de recharge Mode 3"),
        ("Recharge avec courant alternatif (AC)", "Charge avec courant alternatif (AC)"),
        ("Centre de commande", "Commande Infodivertissement"),
        ("Espace sous le capot avant", "Espace sous le rabat avant"),
        ("du régulateur de vitesse", "Régulateur de vitesse"),
        ("Volant", "Volant de direction"),
        (
            "Vue d'ensemble de l'équipement de l'habitacle avant",
            "Équipement intérieur à l'avant",
        ),
        (
            "Vue d'ensemble de l'équipement de l'habitacle arrière",
            "Équipement intérieur arrière",
        ),
        (
            "Assistant d'aide au stationnement Pilote de stationnement",
            "Aide au stationnement Park Pilot",
        ),
    ]
    for alias, target in pairs:
        TITLE_ALIASES[normalize_title(alias)] = normalize_title(target)


_register_aliases()


def _strip_trailing_link_text(text: str, link_text: str) -> str:
    link_clean = clean_title(link_text)
    if link_clean and text.endswith(link_clean):
        return text[: -len(link_clean)].strip(" .–—-")
    return text


def extract_table_row_label(body_html: str, anchor_pos: int) -> str | None:
    """Libellé canonique (colonne centrale) d'une ligne de tableau contenant le lien."""
    row_start = body_html.rfind("<tr", 0, anchor_pos)
    if row_start < 0:
        return None
    row_end = body_html.find("</tr>", anchor_pos)
    if row_end < 0:
        return None
    cells = TABLE_CELL_RE.findall(body_html[row_start : row_end + 5])
    if len(cells) < 2:
        return None
    label = clean_title(cells[1])
    return label or None


def extract_paragraph_hint(body_html: str, anchor_pos: int, link_text: str) -> str | None:
    """Texte du paragraphe parent, sans le libellé du lien."""
    p_start = body_html.rfind("<p", 0, anchor_pos)
    if p_start < 0:
        return None
    p_end = body_html.find("</p>", anchor_pos)
    if p_end < 0:
        return None
    text = clean_title(body_html[p_start : p_end + 4])
    text = _strip_trailing_link_text(text, link_text)
    return text or None


def extract_dd_hint(body_html: str, anchor_pos: int, link_text: str) -> str | None:
    """Texte de la légende (<dd>) contenant le lien."""
    dd_start = body_html.rfind("<dd", 0, anchor_pos)
    if dd_start < 0:
        return None
    dd_end = body_html.find("</dd>", anchor_pos)
    if dd_end < 0:
        return None
    match = DD_BLOCK_RE.search(body_html[dd_start : dd_end + 5])
    if not match:
        return None
    text = _strip_trailing_link_text(clean_title(match.group(1)), link_text)
    return text or None


def collect_link_hints(body_html: str, anchor_pos: int, link_text: str) -> list[str]:
    hints: list[str] = []
    for hint in (
        extract_table_row_label(body_html, anchor_pos),
        extract_dd_hint(body_html, anchor_pos, link_text),
        extract_paragraph_hint(body_html, anchor_pos, link_text),
    ):
        if hint and hint not in hints:
            hints.append(hint)
    return hints


class LinkResolver:
    """Résout les liens dynamiques topiclink via le texte du lien et l'arborescence."""

    def __init__(self, tree: list[dict], flat_topics: list[dict]):
        self.by_title: dict[str, list[str]] = defaultdict(list)
        for topic in flat_topics:
            self.by_title[normalize_title(topic["title"])].append(topic["topicId"])

        self.folder_target: dict[str, str] = {}
        self._index_folders(tree)

        self.all_targets: dict[str, str] = dict(self.folder_target)
        for key, ids in self.by_title.items():
            self.all_targets.setdefault(key, ids[0])

    @staticmethod
    def _first_topic_id(node: dict) -> str | None:
        if node.get("topicId"):
            return node["topicId"]
        for child in node.get("children") or []:
            found = LinkResolver._first_topic_id(child)
            if found:
                return found
        return None

    def _index_folders(self, nodes: list[dict]) -> None:
        for node in nodes:
            if not node.get("topicId"):
                first = self._first_topic_id(node)
                if first:
                    self.folder_target[normalize_title(node["title"])] = first
            self._index_folders(node.get("children") or [])

    def _resolve_title(self, title: str) -> str | None:
        key = TITLE_ALIASES.get(normalize_title(title), normalize_title(title))
        if key in self.by_title:
            return self.by_title[key][0]
        if key in self.folder_target:
            return self.folder_target[key]
        return self._fuzzy_resolve(title)

    def _fuzzy_resolve(self, title: str) -> str | None:
        key = normalize_title(title)
        if len(key) < 8:
            return None

        substring_hits: list[tuple[int, str]] = []
        token_hits: list[tuple[float, int, str]] = []
        query_tokens = {w for w in re.findall(r"\w{4,}", key)}

        for norm_title, topic_id in self.all_targets.items():
            if key == norm_title:
                return topic_id
            if key in norm_title or norm_title in key:
                substring_hits.append((len(norm_title), topic_id))
                continue
            if not query_tokens:
                continue
            title_tokens = {w for w in re.findall(r"\w{4,}", norm_title)}
            overlap = query_tokens & title_tokens
            if len(overlap) >= 2:
                score = len(overlap) / len(query_tokens)
                token_hits.append((score, len(norm_title), topic_id))

        if substring_hits:
            substring_hits.sort(key=lambda item: item[0])
            return substring_hits[0][1]

        if token_hits:
            token_hits.sort(key=lambda item: (-item[0], item[1]))
            best_score = token_hits[0][0]
            if best_score >= 0.5:
                return token_hits[0][2]
        return None

    def resolve(
        self,
        link_text: str,
        href: str,
        known_topic_ids: set[str],
        hints: list[str] | None = None,
    ) -> str | None:
        show_match = TOPIC_ID_IN_LINK_RE.search(href or "")
        if show_match and show_match.group(1) in known_topic_ids:
            return show_match.group(1)

        seen: set[str] = set()
        for candidate in (hints or []) + [link_text]:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            target = self._resolve_title(candidate)
            if target:
                return target
        return None


def rewrite_topic_links(
    body_html: str,
    resolver: LinkResolver,
    known_topic_ids: set[str],
) -> str:
    """Réécrit les ancres topiclink en liens locaux #topic/{id}."""

    def repl_anchor(match: re.Match) -> str:
        anchor = match.group(0)
        text_match = re.search(r"<span[^>]*>(.*?)</span>", anchor, re.DOTALL)
        link_text = text_match.group(1) if text_match else ""
        href_match = re.search(r'href="([^"]*)"', anchor)
        href = href_match.group(1) if href_match else "#"
        hints = collect_link_hints(body_html, match.start(), link_text)

        target = resolver.resolve(link_text, href, known_topic_ids, hints=hints)
        if not target:
            return anchor

        if href_match:
            anchor = re.sub(r'(?<![\w-])href="[^"]*"', f'href="#topic/{target}"', anchor)
        else:
            anchor = anchor.replace("<a ", f'<a href="#topic/{target}" ', 1)

        if "data-topic-id=" not in anchor:
            anchor = anchor.replace("<a ", f'<a data-topic-id="{target}" ', 1)

        # Idempotent : corrige data-class si une ancienne réécriture l'a touché
        anchor = re.sub(r'data-class="local-topic-link\s+', 'data-class="', anchor)
        if 'class="local-topic-link' not in anchor:
            anchor = re.sub(r'(?<![\w-])class="', 'class="local-topic-link ', anchor, count=1)
        return anchor

    return TOPICLINK_ANCHOR_RE.sub(repl_anchor, body_html)


def parse_topic_trees(trees: list) -> tuple[list[dict], list[dict]]:
    """Retourne (liste plate avec topicId, arbre nested pour le viewer)."""
    flat: list[dict] = []

    def walk(nodes: list, depth: int = 0) -> list[dict]:
        nested: list[dict] = []
        for node in nodes:
            topic_id = node.get("linkTarget")
            title = clean_title(node.get("label") or "")
            children_raw = node.get("children") or []
            children = walk(children_raw, depth + 1)

            entry: dict = {"title": title, "depth": depth, "children": children}
            if topic_id:
                entry["topicId"] = topic_id
                flat.append({"title": title, "topicId": topic_id, "depth": depth})
            nested.append(entry)
        return nested

    nested = walk(trees)
    if len(nested) == 1 and not nested[0].get("topicId") and nested[0].get("children"):
        return flat, nested[0]["children"]
    return flat, nested


def add_breadcrumb_paths(nodes: list, trail: list[str] | None = None) -> None:
    trail = trail or []
    for node in nodes:
        path = trail + [node["title"]]
        node["path"] = path
        if node.get("children"):
            add_breadcrumb_paths(node["children"], path)


def media_filename(url: str) -> str:
    clean = html.unescape(url).replace("&amp;", "&")
    qs = parse_qs(urlparse(clean).query)
    key = qs.get("key", ["unknown"])[0]
    return re.sub(r"[^\w.\-]", "_", unquote(key))


def extract_media_urls(text: str) -> set[str]:
    urls = set()
    for match in MEDIA_URL_RE.finditer(text):
        urls.add(html.unescape(match.group(0)).replace("&amp;", "&"))
    return urls


async def download_media(request, url: str, media_dir: Path, cache: dict[str, str]) -> str:
    """Télécharge une image et retourne le chemin relatif depuis chapters/."""
    if url in cache:
        return cache[url]

    filename = media_filename(url)
    dest = media_dir / filename
    rel = f"../media/{filename}"

    if not dest.exists():
        response = await request.get(url)
        if not response.ok:
            raise RuntimeError(f"Média {response.status}: {url}")
        dest.write_bytes(await response.body())

    cache[url] = rel
    return rel


async def process_html(
    body_html: str,
    request,
    media_dir: Path,
    media_cache: dict[str, str],
    known_topic_ids: set[str],
    link_resolver: LinkResolver | None = None,
    links_only: bool = False,
) -> str:
    """Télécharge les images et réécrit les liens internes."""
    if not links_only:
        for url in extract_media_urls(body_html):
            if "../media/" in url:
                continue
            try:
                local = await download_media(request, url, media_dir, media_cache)
            except Exception as exc:
                print(f"  [media] ignoré {url}: {exc}")
                continue
            body_html = body_html.replace(url, local)
            body_html = body_html.replace(url.replace("&", "&amp;"), local)

    if link_resolver:
        body_html = rewrite_topic_links(body_html, link_resolver, known_topic_ids)

    body_html = re.sub(
        r'(<img\b(?![^>]*\bsrc=)[^>]*)\bdata-src="([^"]+)"',
        r'\1src="\2" data-src="\2"',
        body_html,
    )
    body_html = re.sub(r'(\ssrc="[^"]+")\s+src="[^"]+"', r"\1", body_html)

    return body_html


def build_manifest(
    tree: list[dict],
    flat_topics: list[dict],
    scraped_index: list[dict],
    vehicle_title: str = "Škoda Elroq",
) -> dict:
    file_by_topic = {
        item["topicId"]: Path(item["file"]).name
        for item in scraped_index
    }
    paths_by_topic: dict[str, list[str]] = {}

    def walk(nodes: list, trail: list[str] | None = None):
        trail = trail or []
        for node in nodes:
            path = trail + [node["title"]]
            if node.get("topicId"):
                paths_by_topic[node["topicId"]] = path
            walk(node.get("children") or [], path)

    walk(tree)

    flat_with_meta = []
    for item in flat_topics:
        tid = item["topicId"]
        flat_with_meta.append({
            **item,
            "file": file_by_topic.get(tid),
            "path": paths_by_topic.get(tid, [item["title"]]),
        })

    return {
        "title": vehicle_title,
        "locale": "fr_FR",
        "tree": tree,
        "flatTopics": flat_with_meta,
        "topicCount": len(flat_with_meta),
        "scrapedCount": len(scraped_index),
    }


def write_manifest(output_dir: Path, manifest: dict) -> Path:
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


SEARCH_WORD_RE = re.compile(r"[\wÀ-ÿ]+(?:-[\wÀ-ÿ]+)*", re.UNICODE)


def html_to_plain_text(raw_html: str) -> str:
    """Extrait le texte visible d'un chapitre HTML."""
    text = re.sub(r"<!--.*?-->", " ", raw_html, flags=re.S)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip().lower()


def build_search_index(output_dir: Path, manifest: dict) -> dict:
    """Index plein texte pour la recherche du viewer."""
    chapters_dir = output_dir / "chapters"
    topics: list[dict] = []
    term_set: set[str] = set()

    for item in manifest.get("flatTopics") or []:
        filename = item.get("file")
        topic_id = item.get("topicId")
        if not filename or not topic_id:
            continue
        chapter_path = chapters_dir / Path(filename).name
        if not chapter_path.exists():
            continue

        plain = html_to_plain_text(chapter_path.read_text(encoding="utf-8"))
        title = item.get("title") or ""
        topics.append({
            "topicId": topic_id,
            "title": title,
            "path": item.get("path") or [title],
            "text": plain,
        })

        for source in (plain, title.lower(), " ".join(item.get("path") or []).lower()):
            for word in SEARCH_WORD_RE.findall(source):
                if len(word) >= 3:
                    term_set.add(word)

    return {
        "version": 1,
        "topicCount": len(topics),
        "terms": sorted(term_set),
        "topics": topics,
    }


def write_search_index(output_dir: Path, index: dict) -> Path:
    path = output_dir / "search_index.json"
    path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return path

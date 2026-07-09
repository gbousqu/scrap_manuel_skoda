"""Chemins et registre des manuels scrapés (un dossier par modèle)."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MANUALS_DIR = PROJECT_ROOT / "manuals"
INDEX_FILE = MANUALS_DIR / "index.json"
VIEWER_DIR = PROJECT_ROOT / "viewer"
PDF_ENV_BAT = PROJECT_ROOT / "pdf_env.bat"
PDF_PYTHON_PATH = PROJECT_ROOT / "pdf_python_path.txt"
PDF_ENV_JSON = PROJECT_ROOT / "pdf_env.json"


@dataclass
class ManualPaths:
    slug: str
    root: Path

    @property
    def chapters(self) -> Path:
        return self.root / "chapters"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def network_log(self) -> Path:
        return self.root / "network_log"

    @property
    def print_dir(self) -> Path:
        return self.root / "print"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def search_index(self) -> Path:
        return self.root / "search_index.json"

    @property
    def scraped_index(self) -> Path:
        return self.root / "scraped_index.json"

    @property
    def meta(self) -> Path:
        return self.root / "meta.json"

    @property
    def pdf(self) -> Path:
        return self.root / "manual.pdf"

    @property
    def pdf_status(self) -> Path:
        return self.root / "pdf_build_status.json"

    @property
    def pdf_lock(self) -> Path:
        return self.root / "pdf_build.lock"

    @property
    def pdf_log(self) -> Path:
        return self.root / "pdf_build.log"

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.chapters.mkdir(exist_ok=True)
        self.media.mkdir(exist_ok=True)
        self.network_log.mkdir(exist_ok=True)


def model_type_to_slug(model_type: str) -> str:
    """Elroq_PY → elroq."""
    base = (model_type or "unknown").split("_")[0]
    slug = re.sub(r"[^a-z0-9]+", "", base.lower())
    return slug or "unknown"


def vehicle_title_from_model(model_type: str) -> str:
    name = (model_type or "unknown").split("_")[0]
    if name:
        name = name[0].upper() + name[1:].lower()
    return f"Škoda {name}" if name else "Manuel Škoda"


def load_index() -> dict:
    if not INDEX_FILE.exists():
        return {"version": 1, "saves": {}, "lastOpened": None}
    data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    if "saves" not in data:
        data["saves"] = {}
    return data


def save_index(data: dict) -> None:
    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_manual_slugs() -> list[str]:
    index = load_index()
    slugs = set(index.get("saves", {}).keys())
    if MANUALS_DIR.is_dir():
        for path in MANUALS_DIR.iterdir():
            if path.is_dir() and (path / "manifest.json").exists():
                slugs.add(path.name)
    return sorted(slugs)


def get_manual_paths(slug: str) -> ManualPaths:
    slug = slug.strip().lower()
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise ValueError(f"Identifiant manuel invalide : {slug!r}")
    return ManualPaths(slug=slug, root=MANUALS_DIR / slug)


def resolve_manual_slug(manual: str | None = None) -> str:
    if manual:
        return manual.strip().lower()
    env = os.environ.get("SCRAPER_MANUAL", "").strip().lower()
    if env:
        return env
    index = load_index()
    last = index.get("lastOpened")
    if last:
        return last
    slugs = list_manual_slugs()
    if len(slugs) == 1:
        return slugs[0]
    if slugs:
        names = ", ".join(slugs)
        raise SystemExit(
            f"Plusieurs manuels disponibles ({names}). "
            "Précisez --manual <slug> ou $env:SCRAPER_MANUAL."
        )
    raise SystemExit(
        "Aucun manuel trouvé dans manuals/. Lancez d'abord scrape_manual_skoda.py."
    )


def resolve_manual_paths(manual: str | None = None) -> ManualPaths:
    return get_manual_paths(resolve_manual_slug(manual))


def add_manual_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manual",
        metavar="SLUG",
        help="Identifiant du manuel (ex. elroq, octavia). Défaut : SCRAPER_MANUAL ou lastOpened.",
    )


def register_save(
    slug: str,
    *,
    title: str,
    vin: str,
    model_type: str,
    locale: str = "fr_FR",
    topic_count: int = 0,
) -> ManualPaths:
    paths = get_manual_paths(slug)
    paths.ensure_dirs()
    now = datetime.now(timezone.utc).isoformat()

    meta = {
        "id": slug,
        "slug": slug,
        "title": title,
        "vin": vin.upper(),
        "modelType": model_type,
        "locale": locale,
        "updatedAt": now,
        "topicCount": topic_count,
    }
    if paths.meta.exists():
        try:
            old = json.loads(paths.meta.read_text(encoding="utf-8"))
            meta["createdAt"] = old.get("createdAt", now)
        except Exception:
            meta["createdAt"] = now
    else:
        meta["createdAt"] = now
    paths.meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    index = load_index()
    rel = paths.root.relative_to(PROJECT_ROOT).as_posix()
    index.setdefault("saves", {})[slug] = {
        "title": title,
        "path": rel,
        "vin": vin.upper(),
        "modelType": model_type,
        "updatedAt": now,
        "topicCount": topic_count,
    }
    index["lastOpened"] = slug
    save_index(index)
    return paths


def viewer_url(slug: str | None = None) -> str:
    base = "http://localhost/applis/scrap_manuel_skoda/viewer/"
    if slug:
        return f"{base}read.html?manual={slug}"
    return base

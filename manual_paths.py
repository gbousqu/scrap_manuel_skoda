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
        """PDF nommé manual_{slug}.pdf (ex. manual_elroq_2025-11-24.pdf)."""
        dated = self.root / f"manual_{self.slug}.pdf"
        legacy = self.root / "manual.pdf"
        if dated.exists():
            return dated
        if legacy.exists():
            return legacy
        return dated

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


EFFECTIVE_FROM_RE = re.compile(r"vw-effective-from[^>]*>([^<]+)", re.I)
DATE_DMY_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def parse_effective_from(abstract_text: str) -> str | None:
    """Extrait la date d'édition (vw-effective-from) au format ISO YYYY-MM-DD."""
    match = EFFECTIVE_FROM_RE.search(abstract_text or "")
    if not match:
        return None
    raw = match.group(1).strip()
    dm = DATE_DMY_RE.fullmatch(raw)
    if dm:
        day, month, year = dm.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return re.sub(r"[^0-9-]", "-", raw).strip("-") or None


def format_release_date_dmy(iso_date: str | None) -> str | None:
    """2025-11-24 → 24.11.2025 (affichage Škoda)."""
    if not iso_date:
        return None
    parts = iso_date.split("-")
    if len(parts) != 3:
        return iso_date
    year, month, day = parts
    return f"{int(day):02d}.{int(month):02d}.{year}"


def build_manual_slug(model_slug: str, release_date: str | None = None) -> str:
    """Identifiant unique : modèle + date d'édition (ex. elroq_2025-11-24)."""
    model_slug = (model_slug or "unknown").strip().lower()
    if release_date:
        return f"{model_slug}_{release_date}"
    return model_slug


FULL_MANUAL_SLUG_RE = re.compile(r"^([a-z0-9]+)_(\d{4}-\d{2}-\d{2})$")


def parse_forced_model_slug(forced_slug: str) -> str:
    """Accepte elroq ou elroq_2025-11-24 → elroq."""
    forced = (forced_slug or "").strip().lower()
    match = FULL_MANUAL_SLUG_RE.match(forced)
    if match:
        return match.group(1)
    return forced


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
        help="Identifiant du manuel (ex. elroq, elroq_2025-11-24). Défaut : SCRAPER_MANUAL ou lastOpened.",
    )


def register_save(
    slug: str,
    *,
    title: str,
    vin: str,
    model_type: str,
    locale: str = "fr_FR",
    topic_count: int = 0,
    release_date: str | None = None,
    model_slug: str | None = None,
) -> ManualPaths:
    paths = get_manual_paths(slug)
    paths.ensure_dirs()
    now = datetime.now(timezone.utc).isoformat()
    resolved_model_slug = model_slug or model_type_to_slug(model_type)

    meta = {
        "id": slug,
        "slug": slug,
        "title": title,
        "vin": vin.upper(),
        "modelType": model_type,
        "modelSlug": resolved_model_slug,
        "releaseDate": release_date,
        "releaseDateLabel": format_release_date_dmy(release_date),
        "pdfFile": f"manual_{slug}.pdf",
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
        "modelSlug": resolved_model_slug,
        "releaseDate": release_date,
        "releaseDateLabel": format_release_date_dmy(release_date),
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

"""
Scraper pour les manuels utilisateur Škoda (manual.skoda-auto.com)

Usage :
    python scrape_manual_skoda.py
    python scrape_manual_skoda.py --manual elroq

Interface web :
    http://localhost/applis/scrap_manuel_skoda/viewer/

Déroulement :
    1. Le navigateur Chromium s'ouvre sur le portail Škoda.
    2. L'utilisateur saisit le VIN ou choisit un modèle (sans automatisation).
    3. Quand l'URL est …/show/…, le modal « Lancer le scraping » apparaît.
    4. Téléchargement des chapitres dans manuals/{modèle}_{date}/.

Variables d'environnement optionnelles :
    SCRAPER_MANUAL=elroq  — forcer le dossier de sauvegarde
    SCRAPER_AUTO_START=1  — auto-clique le modal après 3 s
    SCRAPER_LIMIT=10      — limite le nombre de chapitres téléchargés
"""

import argparse
import asyncio
import html as html_module
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, expect

from manual_paths import (
    ManualPaths,
    PROJECT_ROOT,
    add_manual_arg,
    build_manual_slug,
    format_release_date_dmy,
    model_type_to_slug,
    parse_effective_from,
    parse_forced_model_slug,
    register_save,
    vehicle_title_from_model,
    viewer_url,
)
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

# URL d'entrée : portail manuels Škoda (VIN + langue -> manuel digital)
BASE_URL = "https://www.skoda.fr/apps/manuals"
VIN_STORAGE_KEY = "skoda_scraper_vin"
USER_DATA_DIR = Path(".scraper_browser_data")

MANUAL_LANG_LABEL = "Français"
LOCALE = "fr_FR"
MANUAL_API_BASE = "https://digital-manual.skoda-auto.com/api"
TOPIC_ID_RE = re.compile(r"/show/([a-f0-9]+_\d+_fr_FR)")
MANUAL_VISIBLE_RE = re.compile(
    r"digital-manual\.skoda-auto\.com/w/[^/]+/show/[a-f0-9]",
    re.I,
)
SCRAPER_STATUS_FILE = PROJECT_ROOT / "scraper_status.json"
SCRAPER_LOCK_FILE = PROJECT_ROOT / "scraper.lock"

_paths: ManualPaths | None = None
_network_log_dir: Path | None = None


def is_manual_visible(url: str) -> bool:
    return bool(MANUAL_VISIBLE_RE.search(url))


def write_scraper_status(state: str, **extra) -> None:
    payload = {
        "state": state,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    SCRAPER_STATUS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def paths() -> ManualPaths:
    if _paths is None:
        raise RuntimeError("Dossier de sauvegarde non configuré")
    return _paths


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def _read_lock_pid() -> int | None:
    if not SCRAPER_LOCK_FILE.exists():
        return None
    try:
        raw = SCRAPER_LOCK_FILE.read_text(encoding="utf-8").strip()
        return int(raw.split()[0])
    except (ValueError, OSError):
        return None


def acquire_scraper_lock() -> None:
    pid = _read_lock_pid()
    if pid and _is_pid_running(pid):
        raise SystemExit(
            f"Un scraping est déjà en cours (PID {pid}). "
            "Lancez stop_scraper.bat ou redémarrez WAMP si le navigateur n'apparaît pas."
        )
    if SCRAPER_LOCK_FILE.exists():
        SCRAPER_LOCK_FILE.unlink()
    SCRAPER_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


async def launch_scraper_browser(playwright, *, headless: bool = False):
    """Contexte Chromium persistant ; profil alternatif si le principal est verrouillé."""
    USER_DATA_DIR.mkdir(exist_ok=True)
    profile = USER_DATA_DIR
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            context = await playwright.chromium.launch_persistent_context(
                str(profile),
                headless=headless,
                timeout=30_000,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            if profile != USER_DATA_DIR:
                print(f"Profil alternatif : {profile}")
            return context, page
        except Exception as exc:
            last_error = exc
            msg = str(exc)
            if attempt == 0 and (
                "ProcessSingleton" in msg
                or "profile" in msg.lower()
                or "utilisé" in msg.lower()
            ):
                profile = USER_DATA_DIR.parent / f".scraper_browser_data_{os.getpid()}"
                print(
                    "Profil navigateur verrouillé (scraper fantôme ?). "
                    f"Tentative avec {profile.name}…"
                )
                continue
            raise

    raise last_error or RuntimeError("Impossible d'ouvrir le navigateur")


async def get_stored_vin(page) -> str | None:
    """Lit le VIN mémorisé dans localStorage (origine skoda.fr)."""
    vin = await page.evaluate(
        f"""() => {{
            try {{
                const v = localStorage.getItem({json.dumps(VIN_STORAGE_KEY)});
                if (!v) return null;
                const n = v.trim().toUpperCase();
                return /^[A-Z0-9]{{17}}$/.test(n) ? n : null;
            }} catch {{
                return null;
            }}
        }}"""
    )
    return vin


async def save_vin_to_storage(page, vin: str) -> None:
    await page.evaluate(
        f"""([key, value]) => {{
            localStorage.setItem(key, value);
        }}""",
        [VIN_STORAGE_KEY, vin.upper()],
    )


async def prompt_vin_modal(page, default_vin: str = "") -> str:
    """Modal de saisie du VIN ; enregistre le choix dans localStorage."""
    vin_ready = asyncio.Event()
    result: dict[str, str] = {}

    async def on_vin_submit(vin: str):
        result["vin"] = vin.strip().upper()
        vin_ready.set()

    await page.expose_function("onVinSubmit", on_vin_submit)

    await page.evaluate(
        """([defaultVin, storageKey]) => {
        if (document.getElementById('scraper-vin-overlay')) return;

        const overlay = document.createElement('div');
        overlay.id = 'scraper-vin-overlay';
        overlay.style.cssText = [
            'position:fixed', 'inset:0', 'background:rgba(0,0,0,0.55)',
            'display:flex', 'align-items:center', 'justify-content:center',
            'z-index:999999'
        ].join(';');

        const box = document.createElement('div');
        box.style.cssText = [
            'background:#fff', 'padding:32px 40px', 'border-radius:12px',
            'max-width:440px', 'width:90%', 'font-family:sans-serif',
            'box-shadow:0 8px 32px rgba(0,0,0,0.25)'
        ].join(';');

        const title = document.createElement('h2');
        title.textContent = 'Scraper Skoda';
        title.style.margin = '0 0 8px';

        const msg = document.createElement('p');
        msg.textContent = 'Saisissez le numéro VIN de votre véhicule (17 caractères).';
        msg.style.cssText = 'margin:0 0 16px;color:#444;font-size:14px;line-height:1.4';

        const input = document.createElement('input');
        input.type = 'text';
        input.maxLength = 17;
        input.placeholder = 'Ex. TMBNH7NY1TF139075';
        input.value = defaultVin || '';
        input.autocomplete = 'off';
        input.spellcheck = false;
        input.style.cssText = [
            'display:block', 'width:100%', 'box-sizing:border-box',
            'padding:10px 12px', 'font-size:16px', 'letter-spacing:0.05em',
            'border:1px solid #ccc', 'border-radius:8px', 'margin-bottom:8px',
            'font-family:monospace', 'text-transform:uppercase'
        ].join(';');
        input.addEventListener('input', () => {
            input.value = input.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
            error.textContent = '';
        });

        const error = document.createElement('p');
        error.style.cssText = 'margin:0 0 16px;color:#c0392b;font-size:13px;min-height:18px';

        const btn = document.createElement('button');
        btn.textContent = 'Continuer';
        btn.style.cssText = [
            'width:100%', 'padding:12px 28px', 'font-size:16px', 'cursor:pointer',
            'border:none', 'border-radius:24px', 'background:#0e3a2f', 'color:#fff'
        ].join(';');

        const submit = () => {
            const v = input.value.trim().toUpperCase();
            if (!/^[A-Z0-9]{17}$/.test(v)) {
                error.textContent = 'Le VIN doit comporter exactement 17 caractères alphanumériques.';
                input.focus();
                return;
            }
            try {
                localStorage.setItem(storageKey, v);
            } catch (e) {}
            window.onVinSubmit(v);
            overlay.remove();
        };

        btn.onclick = submit;
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submit();
        });

        box.append(title, msg, input, error, btn);
        overlay.appendChild(box);
        document.body.appendChild(overlay);
        input.focus();
        input.select();
    }""",
        [default_vin, VIN_STORAGE_KEY],
    )

    print("Modal VIN affiché — saisissez votre numéro VIN pour continuer.")
    await vin_ready.wait()
    vin = result["vin"]
    print(f"VIN enregistré : {vin[:4]}…{vin[-4:]}")
    return vin


async def resolve_vin(page, *, interactive: bool) -> str:
    """
    Retourne le VIN à utiliser :
    SCRAPER_VIN (env) > localStorage > modal (si interactive) > erreur.
    """
    env_vin = os.environ.get("SCRAPER_VIN", "").strip().upper()
    if env_vin:
        if not re.fullmatch(r"[A-Z0-9]{17}", env_vin):
            raise ValueError("SCRAPER_VIN doit contenir exactement 17 caractères alphanumériques.")
        await save_vin_to_storage(page, env_vin)
        print("VIN pris depuis SCRAPER_VIN.")
        return env_vin

    stored = await get_stored_vin(page)
    if stored and not interactive:
        print(f"VIN mémorisé : {stored[:4]}…{stored[-4:]}")
        return stored

    if interactive:
        return await prompt_vin_modal(page, default_vin=stored or "")

    raise SystemExit(
        "Aucun VIN enregistré. Lancez d'abord scrape_manual_skoda.py pour le saisir, "
        "ou définissez la variable d'environnement SCRAPER_VIN."
    )


async def log_json_responses(page):
    """Enregistre les réponses JSON dans network_log/ (debug API)."""

    async def on_response(response):
        log_dir = _network_log_dir
        if log_dir is None:
            return
        ctype = response.headers.get("content-type", "")
        if "json" not in ctype:
            return
        try:
            data = await response.json()
        except Exception:
            return
        fname = re.sub(r"[^a-zA-Z0-9]", "_", response.url)[:150] + ".json"
        (log_dir / fname).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("JSON capturé:", response.url)

    page.on("response", on_response)


async def inject_navigation_hint(page) -> None:
    """Bandeau discret : l'utilisateur navigue lui-même sur le portail Škoda."""
    await page.evaluate(
        """() => {
        if (document.getElementById('scraper-hint-bar')) return;
        const bar = document.createElement('div');
        bar.id = 'scraper-hint-bar';
        bar.style.cssText = [
            'position:fixed', 'bottom:0', 'left:0', 'right:0', 'z-index:999998',
            'background:#0e3a2f', 'color:#fff', 'padding:10px 16px',
            'font:14px/1.4 Segoe UI,sans-serif', 'text-align:center',
            'box-shadow:0 -2px 12px rgba(0,0,0,0.2)'
        ].join(';');
        bar.textContent = 'Scraper Škoda — saisissez votre VIN ou choisissez un modèle, puis ouvrez le manuel. Le téléchargement démarrera quand le manuel s\\'affichera.';
        document.body.appendChild(bar);
    }"""
    )


async def remove_navigation_hint(page) -> None:
    await page.evaluate(
        "() => { document.getElementById('scraper-hint-bar')?.remove(); }"
    )


async def wait_for_manual_visible(page) -> None:
    """Attend que l'utilisateur ouvre le manuel (URL …/show/…)."""
    write_scraper_status(
        "waiting_manual",
        message="Navigateur ouvert — saisissez le VIN ou choisissez un modèle sur le portail Škoda.",
    )
    ready = asyncio.Event()

    def on_navigated(frame):
        if frame != page.main_frame:
            return
        url = frame.url or ""
        if is_manual_visible(url):
            ready.set()

    page.on("framenavigated", on_navigated)

    if not is_manual_visible(page.url):
        await inject_navigation_hint(page)

    while not ready.is_set():
        url = page.url
        if is_manual_visible(url):
            break
        write_scraper_status(
            "waiting_manual",
            message="En attente du manuel (URL …/show/…) — saisissez le VIN ou sélectionnez un modèle.",
            url=url[:120],
        )
        try:
            await asyncio.wait_for(ready.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

    page.remove_listener("framenavigated", on_navigated)
    await remove_navigation_hint(page)
    url = page.url
    write_scraper_status("manual_ready", message="Manuel détecté.", url=url)
    print(f"Manuel visible : {url}")


async def detect_vehicle_from_manual_page(
    page, forced_slug: str | None = None
) -> dict:
    """Déduit modèle, date d'édition et dossier de sauvegarde depuis le manuel ouvert."""
    root_id = await get_root_topic_id(page)
    data = await fetch_topic(page, root_id)
    abstract = data.get("abstractText") or ""
    match = re.search(r"vw-modell-bez[^>]*>([^<]+)", abstract)
    title = html_module.unescape(match.group(1).strip()) if match else "Manuel Škoda"
    release_date = parse_effective_from(abstract)
    release_date_label = format_release_date_dmy(release_date)
    vin = (await get_stored_vin(page)) or os.environ.get("SCRAPER_VIN", "").strip().upper()

    model_type: str
    if forced_slug:
        model_slug = parse_forced_model_slug(forced_slug)
        model_type = model_slug
    elif vin and re.fullmatch(r"[A-Z0-9]{17}", vin):
        try:
            info = await fetch_vehicle_info(page, vin)
            model_type = info.get("modelType") or ""
            model_slug = model_type_to_slug(model_type)
            title = info.get("title") or title
        except RuntimeError:
            name = re.sub(r"^Škoda\s+", "", title, flags=re.I).strip()
            model_slug = model_type_to_slug(f"{name}_PY")
            model_type = name
    else:
        name = re.sub(r"^Škoda\s+", "", title, flags=re.I).strip()
        model_slug = model_type_to_slug(f"{name}_PY")
        model_type = name

    slug = build_manual_slug(model_slug, release_date)
    return {
        "slug": slug,
        "modelSlug": model_slug,
        "title": title,
        "modelType": model_type,
        "vin": vin,
        "releaseDate": release_date,
        "releaseDateLabel": release_date_label,
    }


async def accept_cookies(page):
    """Ferme le bandeau OneTrust s'il est affiché."""
    banner = page.locator("#onetrust-banner-sdk")
    try:
        await banner.wait_for(state="visible", timeout=10000)
    except Exception:
        print("Pas de bandeau cookies (déjà accepté ou absent).")
        return

    accept_btn = page.locator("#onetrust-accept-btn-handler")
    if await accept_btn.count() == 0:
        accept_btn = page.get_by_role("button", name="Tout accepter")

    await accept_btn.click()
    await banner.wait_for(state="hidden", timeout=10000)
    print("Cookies acceptés.")


async def fill_vin_form(page, vin, lang_label):
    """Remplit le formulaire VIN + langue et navigue vers le manuel."""
    await page.get_by_text("Saisissez le code VIN").wait_for(timeout=20000)

    vin_input = page.locator("input.MuiInput-input:not(.MuiSelect-nativeInput)").first

    try:
        async with page.expect_response(
            lambda r: "Languages" in r.url and vin in r.url, timeout=20000
        ):
            await vin_input.fill(vin)
    except Exception:
        await vin_input.fill(vin)
        await page.wait_for_timeout(2000)

    lang_trigger = page.locator(".MuiSelect-select").first
    await lang_trigger.click()

    option = page.get_by_role("option", name=lang_label)
    if await option.count() == 0:
        option = page.get_by_role("listbox").get_by_text(lang_label, exact=True)
    await option.click()

    submit_btn = page.get_by_role("button", name="Afficher")
    await submit_btn.wait_for(state="visible", timeout=10000)
    await expect(submit_btn).to_be_enabled(timeout=10000)

    await page.evaluate(
        "() => { const w = document.getElementById('meedeal-widget'); if (w) w.style.display = 'none'; }"
    )
    await submit_btn.scroll_into_view_if_needed()

    try:
        async with page.expect_navigation(timeout=30000):
            await submit_btn.click()
    except Exception:
        await submit_btn.click(force=True)

    await page.wait_for_url(
        re.compile(r"/Detail|digital-manual\.skoda-auto\.com"), timeout=30000
    )
    await page.wait_for_load_state("networkidle")
    print(f"Manuel chargé : {page.url}")


async def show_scraping_modal_and_wait(page):
    """Injecte un modal et bloque jusqu'au clic sur « Lancer le scraping »."""
    scraping_started = asyncio.Event()

    async def on_scraping_start():
        scraping_started.set()

    await page.expose_function("onScrapingStart", on_scraping_start)

    await page.evaluate(
        """() => {
        if (document.getElementById('scraper-modal-overlay')) return;

        const overlay = document.createElement('div');
        overlay.id = 'scraper-modal-overlay';
        overlay.style.cssText = [
            'position:fixed', 'inset:0', 'background:rgba(0,0,0,0.55)',
            'display:flex', 'align-items:center', 'justify-content:center',
            'z-index:999999'
        ].join(';');

        const box = document.createElement('div');
        box.style.cssText = [
            'background:#fff', 'padding:32px 40px', 'border-radius:12px',
            'max-width:420px', 'text-align:center', 'font-family:sans-serif',
            'box-shadow:0 8px 32px rgba(0,0,0,0.25)'
        ].join(';');

        const title = document.createElement('h2');
        title.textContent = 'Scraper Skoda';
        title.style.margin = '0 0 12px';

        const msg = document.createElement('p');
        msg.textContent = 'Le manuel est affiché. Cliquez pour télécharger la version locale (chapitres + images).';
        msg.style.margin = '0 0 24px';

        const btn = document.createElement('button');
        btn.textContent = 'Lancer le scraping';
        btn.style.cssText = [
            'padding:12px 28px', 'font-size:16px', 'cursor:pointer',
            'border:none', 'border-radius:24px', 'background:#0e3a2f', 'color:#fff'
        ].join(';');
        btn.onclick = () => {
            window.onScrapingStart();
            overlay.remove();
        };

        box.append(title, msg, btn);
        overlay.appendChild(box);
        document.body.appendChild(overlay);
    }"""
    )

    print("Modal affiché — cliquez sur « Lancer le scraping » pour continuer.")

    if os.environ.get("SCRAPER_AUTO_START"):
        async def _auto_click():
            await asyncio.sleep(3)
            await page.locator("#scraper-modal-overlay button").click()

        asyncio.create_task(_auto_click())

    await scraping_started.wait()
    print("Scraping déclenché par l'utilisateur.")


async def fetch_vehicle_info(page, vin: str, forced_slug: str | None = None) -> dict:
    """Détermine modèle et slug depuis l'API VIN Škoda."""
    if forced_slug:
        return {
            "modelType": forced_slug,
            "slug": forced_slug,
            "title": vehicle_title_from_model(f"{forced_slug}_X"),
        }

    request = page.context.request
    api_urls = [
        f"https://www.skoda.fr/apps/manuals/995/fr_FR/api/Models/vin/{vin}",
        f"{BASE_URL}/995/fr_FR/api/Models/vin/{vin}",
    ]
    for url in api_urls:
        try:
            response = await request.get(url)
            if not response.ok:
                continue
            data = await response.json()
            results = data.get("results") or []
            if not results:
                continue
            model_type = results[0].get("modelType") or results[0].get("titleResourceKey") or ""
            slug = model_type_to_slug(model_type)
            return {
                "modelType": model_type,
                "slug": slug,
                "title": vehicle_title_from_model(model_type),
            }
        except Exception:
            continue

    raise RuntimeError(
        f"Impossible de déterminer le modèle pour le VIN {vin[:4]}…{vin[-4:]}. "
        "Utilisez --manual <slug> pour forcer le dossier."
    )


def _topic_id_from_url(url: str) -> str | None:
    match = TOPIC_ID_RE.search(url)
    return match.group(1) if match else None


async def get_root_topic_id(page) -> str:
    """Retourne l'ID du topic racine (arborescence complète)."""
    topic_id = _topic_id_from_url(page.url)
    if topic_id:
        return topic_id

    request = page.context.request
    search_url = (
        f"{MANUAL_API_BASE}/web/V6/search"
        f"?query=&facetfilters=topic-type_|_welcome&lang={LOCALE}&page=0&pageSize=20"
    )
    response = await request.get(search_url)
    data = await response.json()
    return data["results"][0]["topicId"]


async def get_chapter_tree(page, root_topic_id: str):
    """
    Extrait l'arborescence depuis le champ API ``trees`` du topic racine.

    Retourne (liste plate, arbre nested).
    """
    data = await fetch_topic(page, root_topic_id)
    trees = data.get("trees") or []
    if not trees:
        raise RuntimeError("Champ 'trees' absent dans la réponse API du topic racine")

    flat_topics, nested_tree = parse_topic_trees(trees)
    add_breadcrumb_paths(nested_tree)
    print(f"{len(flat_topics)} topics dans l'arborescence API")
    return flat_topics, nested_tree


async def fetch_topic(page, topic_id: str) -> dict:
    """Récupère le contenu d'un topic via l'API vw-topic."""
    url = (
        f"{MANUAL_API_BASE}/vw-topic/V1/topic"
        f"?key={topic_id}&displaytype=desktop&language={LOCALE}"
    )
    response = await page.context.request.get(url)
    if not response.ok:
        raise RuntimeError(f"API {response.status} pour {topic_id}")
    return await response.json()


async def scrape_chapter(
    page,
    topic: dict,
    index: int,
    media_cache: dict,
    known_topic_ids: set[str],
    link_resolver: LinkResolver,
):
    """Télécharge et sauvegarde le HTML d'un chapitre (images + liens locaux)."""
    topic_id = topic["topicId"]
    title = topic["title"]

    data = await fetch_topic(page, topic_id)
    topic_type = data.get("topicType", "text")
    body_html = data.get("bodyHtml", "")

    if topic_type == "tree":
        print(f"[{index}] {title} — topic tree (ignoré)")
        return None

    body_html = await process_html(
        body_html,
        page.context.request,
        paths().media,
        media_cache,
        known_topic_ids,
        link_resolver=link_resolver,
    )

    safe_title = re.sub(r"[^a-zA-Z0-9]+", "_", title)[:80]
    out_path = paths().chapters / f"{index:04d}_{safe_title}.html"
    out_path.write_text(
        f"<!-- topicId: {topic_id} | type: {topic_type} -->\n"
        f"<h1>{title}</h1>\n{body_html}",
        encoding="utf-8",
    )
    print(f"[{index}] {title} ({topic_type}) -> {out_path}")
    return {
        "index": index,
        "title": title,
        "topicId": topic_id,
        "topicType": topic_type,
        "file": out_path.name,
        "depth": topic.get("depth"),
    }


async def scrape_all_chapters(page, chapters: list, known_topic_ids: set[str], link_resolver: LinkResolver):
    """Parcourt l'arborescence et sauvegarde chaque chapitre."""
    limit = int(os.environ.get("SCRAPER_LIMIT", "0"))
    if limit > 0:
        chapters = chapters[:limit]
        print(f"Limite SCRAPER_LIMIT={limit}")

    total = len(chapters)
    write_scraper_status("scraping", progress=0, total=total, message="Téléchargement des chapitres…")

    media_cache: dict[str, str] = {}
    scraped = []
    for i, chapter in enumerate(chapters, start=1):
        try:
            result = await scrape_chapter(
                page, chapter, i, media_cache, known_topic_ids, link_resolver
            )
            if result:
                scraped.append(result)
        except Exception as exc:
            print(f"Erreur sur '{chapter['title']}': {exc}")
        if i % 10 == 0 or i == total:
            write_scraper_status(
                "scraping",
                progress=i,
                total=total,
                message=f"Téléchargement… {i}/{total}",
            )

    print(f"Images téléchargées : {len(media_cache)}")
    return scraped


async def main():
    global _paths, _network_log_dir

    acquire_scraper_lock()

    parser = argparse.ArgumentParser(description="Scraper manuel Škoda")
    add_manual_arg(parser)
    args = parser.parse_args()

    try:
        write_scraper_status("starting", message="Ouverture du navigateur Chromium…")
        async with async_playwright() as p:
            context, page = await launch_scraper_browser(p, headless=False)
            await log_json_responses(page)

            await page.goto(BASE_URL, wait_until="domcontentloaded")
            await wait_for_manual_visible(page)

            vehicle = await detect_vehicle_from_manual_page(page, forced_slug=args.manual)
            slug = vehicle["slug"]
            _paths = register_save(
                slug,
                title=vehicle["title"],
                vin=vehicle.get("vin") or "",
                model_type=vehicle["modelType"],
                release_date=vehicle.get("releaseDate"),
                model_slug=vehicle.get("modelSlug"),
            )
            _paths.ensure_dirs()
            _network_log_dir = _paths.network_log
            date_hint = vehicle.get("releaseDateLabel") or vehicle.get("releaseDate") or "?"
            print(f"Sauvegarde : manuals/{slug}/ ({vehicle['title']}, édition {date_hint})")

            await show_scraping_modal_and_wait(page)

            root_id = await get_root_topic_id(page)
            print(f"Topic racine : {root_id}")

            chapters, tree = await get_chapter_tree(page, root_id)
            known_topic_ids = {c["topicId"] for c in chapters}
            link_resolver = LinkResolver(tree, chapters)

            (paths().root / "sommaire.json").write_text(
                json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (paths().root / "sommaire_tree.json").write_text(
                json.dumps(tree, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            scraped = await scrape_all_chapters(page, chapters, known_topic_ids, link_resolver)
            paths().scraped_index.write_text(
                json.dumps(scraped, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            manifest = build_manifest(
                tree,
                chapters,
                scraped,
                vehicle_title=vehicle["title"],
                release_date=vehicle.get("releaseDate"),
                release_date_label=vehicle.get("releaseDateLabel"),
            )
            write_manifest(paths().root, manifest)
            search_index = build_search_index(paths().root, manifest)
            write_search_index(paths().root, search_index)

            register_save(
                slug,
                title=vehicle["title"],
                vin=vehicle.get("vin") or "",
                model_type=vehicle["modelType"],
                release_date=vehicle.get("releaseDate"),
                model_slug=vehicle.get("modelSlug"),
                topic_count=len(scraped),
            )

            write_scraper_status(
                "done",
                slug=slug,
                title=vehicle["title"],
                releaseDate=vehicle.get("releaseDate"),
                topicCount=len(scraped),
                message="Scraping terminé.",
                viewerUrl=viewer_url(slug),
            )

            print(f"\nTerminé : {len(scraped)} chapitres dans {paths().chapters}/")
            print(f"Viewer : {viewer_url(slug)}")
            print(f"Recherche : {paths().search_index} ({search_index['topicCount']} pages)")

            await context.close()
    except Exception as exc:
        write_scraper_status("error", message=str(exc))
        raise
    finally:
        if SCRAPER_LOCK_FILE.exists():
            SCRAPER_LOCK_FILE.unlink()


if __name__ == "__main__":
    asyncio.run(main())
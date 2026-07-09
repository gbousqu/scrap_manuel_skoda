"""
Configuration locale du projet (une fois par machine).

1. Python + Playwright pour WAMP/Apache (export PDF et lancement des scripts via PHP)
2. Tâche planifiée Windows pour ouvrir Chromium visible depuis le viewer

Usage :
    python setup_local_env.py
    python setup_local_env.py --skip-task
    python setup_local_env.py --skip-pdf
    python setup_local_env.py --user MonCompteWindows
"""
from __future__ import annotations

import argparse
import getpass
import json
import shutil
import site
import subprocess
import sys
from pathlib import Path

from manual_paths import PDF_ENV_BAT, PDF_ENV_JSON, PDF_PYTHON_PATH, PROJECT_ROOT

RUNNER = PROJECT_ROOT / "run_scrape.bat"
TASK_NAME = "SkodaManualScraper"
SCRAPER_TASK_CONFIG = PROJECT_ROOT / "scraper_task.json"


def pick_python() -> Path:
    candidates = [
        Path(r"C:\Python313\python.exe"),
        Path(sys.executable),
    ]
    which = shutil.which("python")
    if which:
        candidates.append(Path(which))

    seen: set[Path] = set()
    for raw in candidates:
        path = raw.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            subprocess.run(
                [str(path), "-c", "import playwright"],
                check=True,
                capture_output=True,
            )
            return path
        except Exception:
            continue
    raise SystemExit(
        "Aucun Python avec Playwright trouvé.\n"
        "  pip install playwright\n"
        "  playwright install chromium"
    )


def configure_pdf_env(python: Path) -> None:
    home = Path.home()
    user_site = site.getusersitepackages()
    browsers = home / "AppData" / "Local" / "ms-playwright"

    env = {
        "python": str(python),
        "pythonpath": user_site,
        "userprofile": str(home),
        "playwright_browsers_path": str(browsers),
    }

    PDF_PYTHON_PATH.write_text(str(python) + "\n", encoding="utf-8")
    PDF_ENV_JSON.write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")

    bat_lines = [
        "@echo off",
        f'set "USERPROFILE={home}"',
        f'set "PYTHONPATH={user_site}"',
        f'set "PLAYWRIGHT_BROWSERS_PATH={browsers}"',
        "",
    ]
    PDF_ENV_BAT.write_text("\n".join(bat_lines), encoding="utf-8")

    print("--- Python / Playwright (WAMP) ---")
    print(f"Python          : {python}")
    print(f"PYTHONPATH      : {user_site}")
    print(f"USERPROFILE     : {home}")
    print(f"Navigateurs     : {browsers}")
    print(f"Fichiers écrits : {PDF_ENV_BAT}, {PDF_ENV_JSON}")


def register_scraper_task(username: str | None = None) -> None:
    user = username or getpass.getuser()
    if not RUNNER.is_file():
        raise SystemExit(f"Fichier introuvable : {RUNNER}")

    tr = str(PROJECT_ROOT / "launch_scrape_task.bat")
    cmd = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/TR",
        tr,
        "/SC",
        "ONCE",
        "/ST",
        "00:00",
        "/SD",
        "01/01/2099",
        "/RU",
        user,
        "/IT",
        "/F",
    ]
    print("\n--- Tâche scraper (navigateur visible) ---")
    print("Enregistrement :", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, result.stderr, file=sys.stderr)
        raise SystemExit(
            f"schtasks a échoué (code {result.returncode}). "
            "Lancez ce script dans un terminal administrateur ou en tant qu'utilisateur courant."
        )

    SCRAPER_TASK_CONFIG.write_text(
        json.dumps(
            {
                "taskName": TASK_NAME,
                "runAs": user,
                "runner": str(RUNNER),
                "projectDir": str(PROJECT_ROOT),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Tâche « {TASK_NAME} » enregistrée pour {user}")
    print(f"Config : {SCRAPER_TASK_CONFIG}")
    print(f"Test   : schtasks /Run /TN {TASK_NAME}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure Python/Playwright pour WAMP et la tâche scraper interactive."
    )
    parser.add_argument(
        "--skip-pdf",
        action="store_true",
        help="Ne pas écrire pdf_env.bat / pdf_python_path.txt",
    )
    parser.add_argument(
        "--skip-task",
        action="store_true",
        help="Ne pas enregistrer la tâche planifiée SkodaManualScraper",
    )
    parser.add_argument(
        "--user",
        metavar="USERNAME",
        help="Compte Windows pour la tâche planifiée (défaut : utilisateur courant)",
    )
    args = parser.parse_args()

    if not args.skip_pdf:
        configure_pdf_env(pick_python())

    if not args.skip_task:
        register_scraper_task(args.user)

    if not args.skip_pdf and not args.skip_task:
        print("\nConfiguration terminée. Le viewer peut lancer le scraping et l'export PDF.")


if __name__ == "__main__":
    main()

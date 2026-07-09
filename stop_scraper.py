"""Arrête les scrapers bloqués et libère le profil navigateur."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
USER_DATA_DIR = PROJECT_ROOT / ".scraper_browser_data"
SCRAPER_LOCK = PROJECT_ROOT / "scraper.lock"
SCRAPER_STATUS = PROJECT_ROOT / "scraper_status.json"
LOG_FILE = PROJECT_ROOT / "scraper_run.log"


def _kill_matching_processes() -> list[int]:
    """Tue les processus python liés au scraper (session utilisateur)."""
    killed: list[int] = []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'scrape_manual_skoda' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                killed.append(int(line))
    except Exception as exc:
        print(f"Arrêt processus : {exc}", file=sys.stderr)
    return killed


def _kill_playwright_chrome() -> None:
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'scraper_browser_data|ms-playwright' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass


def reset_files() -> None:
    if SCRAPER_LOCK.exists():
        SCRAPER_LOCK.unlink()
    SCRAPER_STATUS.write_text(
        json.dumps({"state": "idle", "message": "Arrêté."}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for name in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = USER_DATA_DIR / name
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def main() -> int:
    killed = _kill_matching_processes()
    _kill_playwright_chrome()
    reset_files()
    print(f"Processus arrêtés : {killed or 'aucun (session utilisateur)'}")
    print("État réinitialisé.")
    print()
    print(
        "Si le navigateur ne s'ouvre toujours pas, un scraper tourne peut-être "
        "dans la session Apache (invisible)."
    )
    print("→ Redémarrez WAMP (icône barre des tâches → Restart All Services), puis relancez.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

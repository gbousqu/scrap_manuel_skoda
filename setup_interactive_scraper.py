"""Alias de compatibilité — préférez setup_local_env.py"""
from setup_local_env import register_scraper_task
import sys


if __name__ == "__main__":
    user = sys.argv[1] if len(sys.argv) > 1 else None
    register_scraper_task(user)

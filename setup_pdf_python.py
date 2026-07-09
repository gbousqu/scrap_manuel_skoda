"""Alias de compatibilité — préférez setup_local_env.py"""
from setup_local_env import configure_pdf_env, pick_python


def main() -> None:
    configure_pdf_env(pick_python())


if __name__ == "__main__":
    main()

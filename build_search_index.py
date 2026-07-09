"""Génère search_index.json pour la recherche plein texte du viewer."""

from __future__ import annotations

import argparse
import json

from manual_paths import add_manual_arg, resolve_manual_paths
from manual_postprocess import build_search_index, write_search_index


def main():
    parser = argparse.ArgumentParser()
    add_manual_arg(parser)
    args = parser.parse_args()
    paths = resolve_manual_paths(args.manual)

    if not paths.manifest.exists():
        raise FileNotFoundError("manifest.json introuvable — lancez d'abord le post-traitement.")

    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    index = build_search_index(paths.root, manifest)
    write_search_index(paths.root, index)
    size_mb = paths.search_index.stat().st_size / (1024 * 1024)
    print(
        f"Index écrit : {index['topicCount']} pages, "
        f"{len(index['terms'])} termes, {size_mb:.1f} Mo"
    )


if __name__ == "__main__":
    main()

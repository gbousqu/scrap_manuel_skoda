"""Audit des liens topiclink non résolus (href="#").

Usage :
    python scan_broken_links.py --manual elroq
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict

from manual_paths import add_manual_arg, resolve_manual_paths

ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bclass="[^"]*topiclink[^"]*"[^>]*>.*?</a>', re.I | re.S
)
SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S)
TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S)
P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def table_hint(html: str, pos: int) -> str:
    row_start = html.rfind("<tr", 0, pos)
    if row_start < 0:
        return ""
    row_end = html.find("</tr>", pos)
    if row_end < 0:
        return ""
    row = html[row_start:row_end]
    cells = TD_RE.findall(row)
    return " | ".join(clean(c) for c in cells[:3])


def main():
    parser = argparse.ArgumentParser()
    add_manual_arg(parser)
    args = parser.parse_args()
    paths = resolve_manual_paths(args.manual)
    chapters = paths.chapters

    broken_by_chapter: dict[str, list[str]] = defaultdict(list)
    label_counter: Counter[str] = Counter()

    for path in sorted(chapters.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        for m in ANCHOR_RE.finditer(html):
            tag = m.group(0)
            if 'href="#"' not in tag and "href='#'" not in tag:
                continue
            span = SPAN_RE.search(tag)
            label = clean(span.group(1)) if span else clean(tag)
            if not label:
                label = table_hint(html, m.start()) or "(sans libellé)"
            broken_by_chapter[path.name].append(label)
            label_counter[label] += 1

    total = sum(len(v) for v in broken_by_chapter.values())
    print(f"Manuel : {paths.slug}")
    print(f"Liens cassés : {total} dans {len(broken_by_chapter)} chapitres\n")

    for chapter, labels in sorted(broken_by_chapter.items()):
        print(f"  {chapter} ({len(labels)})")
        for label in labels[:5]:
            print(f"    - {label[:80]}")
        if len(labels) > 5:
            print(f"    … +{len(labels) - 5}")

    if label_counter:
        print("\nLibellés les plus fréquents :")
        for label, count in label_counter.most_common(15):
            print(f"  {count:4d}  {label[:70]}")


if __name__ == "__main__":
    main()

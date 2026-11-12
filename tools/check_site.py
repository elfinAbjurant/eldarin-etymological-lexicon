#!/usr/bin/env python3
"""Check the generated site in ./site.

- Every internal link (page and #fragment) resolves.
- Every search-index URL resolves.
- The JSON-LD export is valid JSON.
- If rdflib is installed (pip install rdflib), both RDF exports parse.

Exit status is 1 if anything fails, so this can run in CI.
"""
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
ID_RE = re.compile(r'id="([^"]+)"')
HREF_RE = re.compile(r'href="([^"#:]*\.html)(?:#([^"]*))?"')


def main():
    if not (SITE / "index.html").exists():
        sys.exit("No site found. Run: python3 lexicon/build_site.py")
    pages = list(SITE.rglob("*.html"))
    ids = {p.resolve(): set(ID_RE.findall(p.read_text(encoding="utf-8"))) for p in pages}
    failures = []

    links = 0
    for p in pages:
        for target, frag in HREF_RE.findall(p.read_text(encoding="utf-8")):
            links += 1
            t = (p.parent / target).resolve()
            if t not in ids or (frag and frag not in ids[t]):
                failures.append(f"broken link in {p.relative_to(SITE)}: {target}#{frag}")
    print(f"{len(pages):,} pages, {links:,} internal links checked")

    rows = json.loads((SITE / "data" / "search-index.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("entries", [])
    for x in rows:
        target, _, frag = x[6].partition("#")
        t = (SITE / target).resolve()
        if t not in ids or (frag and frag not in ids[t]):
            failures.append(f"broken search URL: {x[6]}")
    print(f"{len(rows):,} search-index URLs checked")

    json.loads((SITE / "data" / "lexicon.jsonld").read_text(encoding="utf-8"))
    try:
        import rdflib
    except ImportError:
        print("rdflib not installed; skipping RDF parsing (pip install rdflib)")
    else:
        base = "https://example.org/lexicon/data/"
        for name, fmt in (("lexicon.ttl", "turtle"), ("lexicon.jsonld", "json-ld")):
            g = rdflib.Graph()
            g.parse(SITE / "data" / name, format=fmt, publicID=base + name)
            print(f"{name}: {len(g):,} triples")

    for f in failures[:20]:
        print("FAIL", f)
    if failures:
        sys.exit(f"{len(failures)} problem(s) found")
    print("All checks passed")


if __name__ == "__main__":
    main()

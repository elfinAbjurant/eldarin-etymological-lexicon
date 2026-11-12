#!/usr/bin/env python3
"""
explore.py — Query the lexicon database from the command line.

Examples:
    python3 lexicon/explore.py elen             # look up a word in any language
    python3 lexicon/explore.py galadh --lang s  # restrict to Sindarin
    python3 lexicon/explore.py --stats          # summary statistics
"""
import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "lexicon.db"

# Recursive common table expression: walk derived_from links back to the root.
ANCESTRY_SQL = """
WITH RECURSIVE ancestry(entry_id, depth, path) AS (
    SELECT ?, 0, ',' || ? || ','
    UNION ALL
    SELECT l.to_id, a.depth + 1, a.path || l.to_id || ','
    FROM links l JOIN ancestry a ON l.from_id = a.entry_id
    WHERE l.rel_type = 'derived_from'
      AND instr(a.path, ',' || l.to_id || ',') = 0   -- avoid cycles
      AND a.depth < 10
)
SELECT MIN(a.depth) AS depth, e.form, g.name AS language, e.gloss
FROM ancestry a
JOIN entries e   ON e.entry_id = a.entry_id
JOIN languages g ON g.lang_code = e.lang_code
WHERE a.depth > 0
GROUP BY a.entry_id
ORDER BY depth;
"""

LINKED_SQL = """
SELECT DISTINCT e.form, g.name AS language, e.gloss, g.sort_order, e.sort_key
FROM links l
JOIN entries e   ON e.entry_id = CASE WHEN l.from_id = :id THEN l.to_id ELSE l.from_id END
JOIN languages g ON g.lang_code = e.lang_code
WHERE l.rel_type = :rel AND (l.from_id = :id OR (:symmetric AND l.to_id = :id))
ORDER BY g.sort_order, e.sort_key;
"""


def show(conn, entry):
    print(f"\n{entry['form']}  ({entry['language']}, {entry['speech']})  “{entry['gloss'] or ''}”")
    rows = conn.execute(ANCESTRY_SQL, (entry["entry_id"], entry["entry_id"])).fetchall()
    if rows:
        print("  Etymology:")
        for r in rows:
            print(f"    {'  ' * (r['depth'] - 1)}← {r['form']} ({r['language']}) “{r['gloss'] or ''}”")
    for label, rel, sym in [("Cognates", "cognate", True), ("Built from", "has_element", False)]:
        rows = conn.execute(LINKED_SQL, {"id": entry["entry_id"], "rel": rel, "symmetric": sym}).fetchall()
        if rows:
            print(f"  {label}: " + "; ".join(f"{r['form']} ({r['language']})" for r in rows))
    n = conn.execute("SELECT COUNT(*) FROM links WHERE to_id=? AND rel_type='has_element'",
                     (entry["entry_id"],)).fetchone()[0]
    if n:
        print(f"  Used in {n} compounds or names")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("word", nargs="?")
    ap.add_argument("--lang", help="language code, e.g. q (Quenya), s (Sindarin), p (Primitive Elvish)")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if args.stats:
        for r in conn.execute("""SELECT g.name, COUNT(*) AS n FROM entries e
                                 JOIN languages g USING (lang_code) GROUP BY g.name ORDER BY n DESC"""):
            print(f"{r['name']:<18}{r['n']:>6}")
        for r in conn.execute("SELECT rel_type, COUNT(*) AS n FROM links GROUP BY rel_type ORDER BY n DESC"):
            print(f"{r['rel_type']:<18}{r['n']:>6}")
        return
    if not args.word:
        ap.print_help()
        return
    sql = """SELECT e.*, g.name AS language FROM entries e JOIN languages g USING (lang_code)
             WHERE (e.form = ? OR e.sort_key = lower(?))""" + (" AND e.lang_code = ?" if args.lang else "")
    params = [args.word, args.word] + ([args.lang] if args.lang else [])
    matches = conn.execute(sql + " ORDER BY g.sort_order", params).fetchall()
    if not matches:
        print("No entry found.")
    for m in matches:
        show(conn, m)


if __name__ == "__main__":
    main()

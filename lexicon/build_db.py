#!/usr/bin/env python3
"""
build_db.py — Load Paul Strack's Eldamo XML data model into a relational SQLite database.

Scope: the Late Period (1950–1973) Elvish languages — Primitive Elvish and its
descendants (Ancient Quenya, Quenya, Vanyarin, Ancient Telerin, Telerin,
Old Sindarin, Sindarin, North Sindarin, Nandorin, Avarin).

Etymological links in Eldamo appear at two levels:
  1. on a <word> element, pointing to another word by language + form (l, v);
  2. on an individual attestation (<ref>), pointing to another attestation by its
     source citation (e.g. "PE17/067.0105").
Both are resolved to entry-to-entry edges in the `relations` table, keeping the
source citation as provenance.

Data: Eldamo © 2008–2026 Paul Strack, CC BY 4.0 — https://eldamo.org
Usage: python3 lexicon/build_db.py [path/to/eldamo-data.xml] [path/to/lexicon.db]
"""

import sqlite3
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XML_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "eldamo-data.xml"
DB_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "lexicon.db"

# Late-period Elvish languages included in this lexicon.
# BCP 47 tags: Quenya and Sindarin have registered ISO 639-3 codes (qya, sjn).
# The others have none, so we use the private-use "art-x-" extension
# (art = artificial language). These tags are written into every HTML lang=""
# attribute and every RDF language-tagged literal.
LANGUAGES = {
    "p":      ("Primitive Elvish", "art-x-prelv",   "Proto-language of all the Elves", 1),
    "aq":     ("Ancient Quenya",   "art-x-aquenya", "Older stage of Quenya",            2),
    "q":      ("Quenya",           "qya",           "High-Elven tongue of the Noldor and Vanyar", 3),
    "van":    ("Vanyarin",         "art-x-vanyar",  "Dialect of Quenya spoken by the Vanyar", 4),
    "at":     ("Ancient Telerin",  "art-x-atelerin","Common ancestor of Telerin and Sindarin", 5),
    "t":      ("Telerin",          "art-x-telerin", "Language of the Teleri of Aman",   6),
    "os":     ("Old Sindarin",     "art-x-osindar", "Older stage of Sindarin",          7),
    "s":      ("Sindarin",         "sjn",           "Grey-elven tongue of Middle-earth", 8),
    "norths": ("North Sindarin",   "art-x-nsindar", "Dialect of Sindarin from the North", 9),
    "nan":    ("Nandorin",         "art-x-nandor",  "Language of the Green-elves",      10),
    "av":     ("Avarin",           "art-x-avarin",  "Languages of the Elves who refused the Summons", 11),
}

# Entry types left out: phonology and grammar notes, phrases and texts are not
# dictionary headwords.
EXCLUDED_SPEECH = {"phonetic-rule", "phoneme", "phonetic-group", "phonetics",
                   "grammar", "phrase", "text"}

# Eldamo relation elements we keep, mapped to our relation types.
REL_TYPES = {"deriv": "derived_from", "element": "has_element",
             "cognate": "cognate", "related": "related", "see": "see_also"}

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE languages (
    lang_code   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    bcp47       TEXT NOT NULL,
    description TEXT,
    parent_code TEXT REFERENCES languages(lang_code),
    sort_order  INTEGER
);

CREATE TABLE categories (
    cat_id      TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    group_label TEXT NOT NULL,
    num         TEXT
);

CREATE TABLE sources (
    prefix      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_type TEXT
);

CREATE TABLE entries (
    entry_id    INTEGER PRIMARY KEY,         -- Eldamo page-id (stable identifier)
    lang_code   TEXT NOT NULL REFERENCES languages(lang_code),
    form        TEXT NOT NULL,               -- headword as written
    sort_key    TEXT NOT NULL,               -- lowercase, diacritics removed
    speech      TEXT,                        -- part of speech
    gloss       TEXT,
    ngloss      TEXT,                        -- extended gloss incl. earlier periods
    cat_id      TEXT REFERENCES categories(cat_id),
    mark        TEXT,                        -- Eldamo editorial mark (†, *, # ...)
    stem        TEXT,
    notes_html  TEXT,
    UNIQUE (lang_code, form)
);

CREATE TABLE attestations (
    att_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES entries(entry_id),
    form        TEXT NOT NULL,
    source      TEXT NOT NULL UNIQUE,        -- e.g. LotR/0377.3306
    source_prefix TEXT,
    gloss       TEXT,
    inflection  TEXT
);

CREATE TABLE relations (
    rel_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id     INTEGER NOT NULL REFERENCES entries(entry_id),
    to_id       INTEGER NOT NULL REFERENCES entries(entry_id),
    rel_type    TEXT NOT NULL CHECK (rel_type IN
                 ('derived_from','has_element','cognate','related','see_also')),
    source      TEXT,                        -- citation for attestation-level links
    UNIQUE (from_id, to_id, rel_type, source)
);

CREATE INDEX idx_entries_lang ON entries(lang_code, sort_key);
CREATE INDEX idx_rel_from ON relations(from_id, rel_type);
CREATE INDEX idx_rel_to   ON relations(to_id, rel_type);
CREATE INDEX idx_att_entry ON attestations(entry_id);

-- One row per distinct link, with the number of supporting citations.
CREATE VIEW links AS
SELECT from_id, to_id, rel_type, COUNT(source) AS citations
FROM relations GROUP BY from_id, to_id, rel_type;
"""


def sort_key(form: str) -> str:
    decomposed = unicodedata.normalize("NFKD", form.lower())
    return "".join(ch for ch in decomposed
                   if ch.isalnum() and not unicodedata.combining(ch))


def main():
    print(f"Reading {XML_PATH} ...")
    root = ET.parse(XML_PATH).getroot()

    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    # Languages (with parent links taken from the XML language tree).
    parents = {}
    def walk(elem, parent=None):
        for lang in elem.findall("language"):
            parents[lang.get("id")] = parent
            walk(lang, lang.get("id"))
    for cat in root.findall("language-cat"):
        walk(cat)
    for code, (name, tag, desc, order) in LANGUAGES.items():
        parent = parents.get(code) if parents.get(code) in LANGUAGES else None
        conn.execute("INSERT INTO languages VALUES (?,?,?,?,?,?)",
                     (code, name, tag, desc, None, order))
    for code in LANGUAGES:
        p = parents.get(code)
        if p in LANGUAGES:
            conn.execute("UPDATE languages SET parent_code=? WHERE lang_code=?", (p, code))

    # Semantic categories and bibliographic sources.
    for group in root.find("cats").findall("cat-group"):
        for cat in group.findall("cat"):
            conn.execute("INSERT INTO categories VALUES (?,?,?,?)",
                         (cat.get("id"), cat.get("label"), group.get("label"), cat.get("num")))
    for src in root.findall("source"):
        conn.execute("INSERT INTO sources VALUES (?,?,?)",
                     (src.get("prefix"), src.get("name"), src.get("type")))
    known_cats = {r[0] for r in conn.execute("SELECT cat_id FROM categories")}

    # Index every word and every attestation in the whole file, so links can be
    # resolved even when they pass through words we do not keep.
    all_words = list(root.iter("word"))
    by_lang_form = {(w.get("l"), w.get("v")): w for w in all_words}
    by_source = {}
    for w in all_words:
        for ref in w.findall("ref"):
            by_source[ref.get("source")] = w

    kept = {}
    for w in all_words:
        if w.get("l") in LANGUAGES and w.get("speech") not in EXCLUDED_SPEECH:
            kept[id(w)] = int(w.get("page-id"))

    # Entries and attestations.
    for w in all_words:
        if id(w) not in kept:
            continue
        notes = w.find("notes")
        cat = w.get("cat") if w.get("cat") in known_cats else None
        conn.execute(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (kept[id(w)], w.get("l"), w.get("v"), sort_key(w.get("v")), w.get("speech"),
             w.get("gloss"), w.get("ngloss"), cat, w.get("mark"), w.get("stem"),
             notes.text if notes is not None else None))
        for ref in w.findall("ref"):
            inflect = "; ".join(i.get("form", "") for i in ref.findall("inflect")) or None
            source = ref.get("source")
            conn.execute(
                "INSERT INTO attestations (entry_id, form, source, source_prefix, gloss, inflection)"
                " VALUES (?,?,?,?,?,?)",
                (kept[id(w)], ref.get("v"), source, source.split("/")[0], ref.get("gloss"), inflect))

    # Relations.
    added = skipped = 0
    def add(src_word, target_word, tag, citation):
        nonlocal added, skipped
        if target_word is None or id(target_word) not in kept or src_word is target_word:
            skipped += 1
            return
        cur = conn.execute(
            "INSERT OR IGNORE INTO relations (from_id, to_id, rel_type, source) VALUES (?,?,?,?)",
            (kept[id(src_word)], kept[id(target_word)], REL_TYPES[tag], citation))
        added += cur.rowcount

    for w in all_words:
        if id(w) not in kept:
            continue
        # 1. Word-level links (by language + form).
        for child in w:
            if child.tag in REL_TYPES:
                target = by_lang_form.get((child.get("l", w.get("l")), child.get("v")))
                add(w, target, child.tag, None)
        # 2. Attestation-level links (by source citation).
        for ref in w.findall("ref"):
            for child in ref:
                if child.tag in REL_TYPES and child.get("source"):
                    add(w, by_source.get(child.get("source")), child.tag, child.get("source"))

    conn.commit()
    n_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    n_att = conn.execute("SELECT COUNT(*) FROM attestations").fetchone()[0]
    n_links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    print(f"Entries: {n_entries:,}  Attestations: {n_att:,}  "
          f"Relation rows: {added:,}  Distinct links: {n_links:,}  "
          f"(skipped {skipped:,} links to out-of-scope words)")
    conn.execute("VACUUM")
    conn.close()
    print(f"Wrote {DB_PATH}")


if __name__ == "__main__":
    main()

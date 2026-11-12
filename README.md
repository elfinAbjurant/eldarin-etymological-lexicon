# Eldarin Etymological Lexicon

An accessible, linked-data dictionary of J.R.R. Tolkien's late-period Elvish languages (Primitive Elvish, Quenya, Sindarin, Telerin and their relatives). It focuses on how words are connected: their roots, derivations, compounds and cognates.

- 7,877 dictionary entries in 11 languages
- 12,613 word-to-word links (derivations, compound elements, cognates, related words)
- 27,457 citations to Tolkien's writings
- Words with more than two links get their own page. Shorter entries appear in full on the alphabetical index pages. All entries carry embedded JSON-LD (OntoLex-Lemon)

Lexical data: [Eldamo](https://eldamo.org) by Paul Strack, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## How it works

```
data/eldamo-data.xml ──build_db.py──▶ data/lexicon.db ──build_site.py──▶ site/  (HTML + RDF + CSV)
                                              │
                                              └──explore.py (command-line queries)
```

All three scripts use only the Python standard library (`sqlite3`, `xml.etree`, `json`, `csv`, `html`).

```bash
python3 lexicon/build_db.py                 # XML → SQLite (about 2 seconds)
python3 lexicon/build_site.py               # SQLite → website in ./site
python3 lexicon/explore.py galadh --lang s  # look up a word and its etymology
python3 -m http.server -d site 8000         # preview at http://localhost:8000
```

To refresh the source data:
`curl -L -o data/eldamo-data.xml https://raw.githubusercontent.com/pfstrack/eldamo/master/src/data/eldamo-data.xml`

## Database design

| Table | Contents |
|---|---|
| `languages` | 11 languages with BCP 47 language tags (`qya`, `sjn`, `art-x-telerin` ...) and a `parent_code` self-reference forming the family tree |
| `entries` | Headwords: form, sort key, part of speech, gloss, semantic category, Eldamo status mark, notes. The primary key is Eldamo's stable page ID |
| `attestations` | Each appearance of a word in a source, with its citation (e.g. `LotR/0377.3306`) and grammatical form |
| `relations` | Typed links between entries: `derived_from`, `has_element`, `cognate`, `related`, `see_also`, each with its supporting citation |
| `categories`, `sources` | Lookup tables for semantic categories and bibliographic sources |
| `links` (view) | One row per distinct link, with a count of supporting citations |

Eldamo records etymological links at two levels: on a word (pointing to another word by language and form) and on individual citations (pointing to another citation by its source reference). `build_db.py` indexes every citation in the file and resolves both kinds into the same `relations` table.

Example: walking an etymology back to its root with a recursive query (from `explore.py`):

```sql
WITH RECURSIVE ancestry(entry_id, depth, path) AS (
    SELECT :id, 0, ',' || :id || ','
    UNION ALL
    SELECT l.to_id, a.depth + 1, a.path || l.to_id || ','
    FROM links l JOIN ancestry a ON l.from_id = a.entry_id
    WHERE l.rel_type = 'derived_from'
      AND instr(a.path, ',' || l.to_id || ',') = 0   -- guard against cycles
)
SELECT ... ;
```

## Linked data

- Each entry has a hash identifier, kept separate from the page that describes it: `entry/<id>.html#entry` for full entries, and `lang/<page>.html#w<id>` for short entries on index pages. Each also has form and sense nodes.
- Model: OntoLex-Lemon (`ontolex:LexicalEntry`, `ontolex:Etymon` for roots, `ontolex:Form`, `ontolex:LexicalSense`), LexInfo parts of speech, `decomp:subterm` for compound elements, and three project properties: `eld:derivedFrom`, `eld:cognateWith` and `eld:relatedTo` (defined on `linked-data.html`).
- Every entry links to its Eldamo page with `rdfs:seeAlso`. Quenya and Sindarin link to Lexvo language IRIs.
- IRIs are relative, so the data resolves wherever the site is hosted.
- Full dumps: `site/data/lexicon.ttl` and `site/data/lexicon.jsonld`.

## Accessibility (WCAG 2.2 AA)

See `site/accessibility.html` for the full statement. Highlights:

- `lang` attributes on every Elvish word (WCAG 3.1.2, Language of Parts)
- The √ and ✶ symbols are hidden from screen readers and replaced by the spoken words "root" and "primitive form". Status marks are spelled out in text
- A plain-language etymology sentence before each nested tree
- Skip link, landmarks, logical headings, breadcrumbs and an "On this page" menu
- Captioned data tables with header cells, inside keyboard-focusable scroll regions
- Search results announced through an `aria-live` status message. Every page except live search works without JavaScript
- Light and dark themes (following the system setting, with a toggle), visible focus, reduced-motion support, and reflow down to 320 px
- Tested with axe-core (0 violations on 35 sampled pages in both themes), keyboard-only use, and 375 px and 1280 px layouts

## How this covers the three assignments

| Assignment | Where it is covered |
|---|---|
| 1. Basic website (Library IT) | `site/`: multi-page site with navigation, browse indexes, search, about and data pages |
| 2. Database with Python (Library IT) | `lexicon/build_db.py` (schema design, XML → SQL loading, link resolution), `lexicon/explore.py` (recursive SQL queries), `lexicon/build_site.py` (database-driven page generation) |
| 3. Accessible web page (Universal Design) | Accessibility features throughout, plus `site/accessibility.html` (statement mapped to WCAG 2.2 success criteria) |

Not affiliated with the Tolkien Estate. Non-commercial educational project.

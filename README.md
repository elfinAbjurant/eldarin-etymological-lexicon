# Eldarin Etymological Lexicon

The Eldarin Etymological Lexicon is a digital humanities project for exploring Tolkien's late-period Elvish languages and the relationships between their words. It includes a searchable static website, a SQLite database built with Python, and linked-data exports.

**Website:** [elfinabjurant.github.io/eldarin-etymological-lexicon](https://elfinabjurant.github.io/eldarin-etymological-lexicon/)

The site covers Primitive Elvish, Quenya, Sindarin, Telerin, and related languages. Its dataset contains:

- 7,877 dictionary entries across 11 languages
- 12,613 word-to-word relationships, including derivations, compounds, and cognates
- 27,457 citations to Tolkien's writings

Entries with extensive etymological links have dedicated pages. Shorter entries are displayed on alphabetical language indexes. Entries include embedded JSON-LD, and the complete dataset is also available as JSON-LD, Turtle, CSV, and SQLite downloads from the website.

## Project and coursework

This project was created for coursework in library and information science, with a focus on building a basic website and examining accessibility in a digital resource.

## Data and attribution

Lexical data comes from [Eldamo](https://eldamo.org) by Paul Strack, version 0.8.14, used under the [Creative Commons Attribution 4.0 license](https://creativecommons.org/licenses/by/4.0/). The data and generated files derived from it retain that attribution requirement. See [data/README.md](data/README.md) for details.

The star illustration on the homepage is “Star” by acspike via Openclipart, released under CC0 1.0. The source and credit appear on the homepage and in the SVG metadata.

## How it works

```text
data/eldamo-data.xml -> lexicon/build_db.py -> data/lexicon.db
data/lexicon.db -> lexicon/build_site.py -> site/ (HTML, RDF, CSV, search index)
```

The Python scripts use the standard library. The database stores languages, entries, attestations, sources, categories, and typed word relationships. The `links` view provides a consolidated view of etymological connections. `lexicon/explore.py` offers command-line lookups and recursive ancestry queries.

The database schema and relationship model are described below and in `lexicon/build_db.py`. The generated site is plain static HTML, CSS, JavaScript, and data files; Python is used to build the database and generate the website, not run the published pages.

## Build and preview

Requirements: Python 3.10 or newer. No packages are required for the standard build. From the project directory:

```bash
make all       # rebuild the SQLite database and static site
make check     # check internal links, search URLs, and data exports
make serve     # preview at http://localhost:8000
```

To generate an individual page for every entry, as used for GitHub Pages:

```bash
make site-all
```

The generated site is written to `site/`. GitHub Actions builds and publishes this directory when changes are pushed to the `master` branch. `rdflib` is optional and enables additional RDF parsing checks in `make check`.

## Database overview

| Table or view | Contents |
|---|---|
| `languages` | The 11 languages, their BCP 47 tags, and language-family relationships |
| `entries` | Headwords, language, part of speech, gloss, category, notes, and editorial status |
| `attestations` | Forms as cited in Tolkien's sources, with citations and grammatical information |
| `relations` | Typed word relationships and their supporting citations |
| `categories`, `sources` | Lookup tables for semantic categories and bibliographic sources |
| `links` (view) | Distinct word-to-word relationships with supporting-citation counts |

Eldamo records links both on words and on individual citations. The Python import process resolves both kinds into the `relations` table, preserving citation evidence for each relationship.

## Linked data

The linked-data model uses OntoLex-Lemon, LexInfo, and the decomposition vocabulary, alongside project properties for derivation, cognacy, and relatedness. Each lexical entry has a stable identifier and links to its Eldamo source entry. The site provides full JSON-LD and Turtle exports, with relative IRIs so the data remains usable under different hosting paths.

## Accessibility

The site is designed toward WCAG 2.2 AA and has an [accessibility statement](https://elfinabjurant.github.io/eldarin-etymological-lexicon/accessibility.html) describing its features, test methods, and limitations. Features include a skip link, semantic landmarks and headings, language tags on Elvish text, visible keyboard focus, labeled forms, keyboard-operable controls, responsive layouts, and search-result announcements.

Automated axe-core checks reported no WCAG A/AA violations on a representative sample of pages in both themes. WAVE's homepage scan reported 0 contrast errors, 8 language errors, and 1 redundant-link alert. The language errors appear to correspond to the private-use tag for Primitive Elvish (`art-x-prelv`). Keyboard checks have covered selected controls, and screen-reader testing has not yet been completed. These checks are useful but do not establish full WCAG conformance; details and known limitations are recorded on the accessibility page.

## Project structure

- `data/`: Eldamo source XML, SQLite database, and data attribution
- `lexicon/`: Python database and site builders, query tool, and static assets
- `site/`: generated website output
- `tools/check_site.py`: generated-site link and data validation
- `.github/workflows/pages.yml`: GitHub Pages build and deployment workflow

This is a non-commercial educational project and is not affiliated with the Tolkien Estate.
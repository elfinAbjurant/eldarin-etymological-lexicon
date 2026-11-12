#!/usr/bin/env python3
"""
build_site.py — Generate the accessible static website and linked-data exports
from lexicon.db.

Output (in ./site):
  index.html, browse.html, roots.html, search.html, linked-data.html,
  about.html, accessibility.html
  lang/<code>[-<letter>].html   alphabetical indexes per language
  entry/<id>.html               one page per dictionary entry, with embedded JSON-LD
  data/lexicon.ttl              full RDF dump (Turtle, OntoLex-Lemon)
  data/lexicon.jsonld           full RDF dump (JSON-LD)
  data/entries.csv              flat table of entries
  data/lexicon.db               the SQLite database itself
  data/search-index.json        index used by the search page

All IRIs are relative (e.g. entry/1319998893.html#entry), so the data resolves
correctly wherever the site is hosted.

Usage: python3 lexicon/build_site.py
"""

import csv
import html
import json
import re
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "lexicon.db"
STATIC = ROOT / "lexicon" / "static"
OUT = ROOT / "site"
ELDAMO_WORD = "https://pfstrack.github.io/eldamo/content/words/word-{}.html"
ELDAMO_BASE = "https://pfstrack.github.io/eldamo/content/words/"

e = html.escape

POS_LABELS = {
    "n": "noun", "adj": "adjective", "vb": "verb", "root": "root", "adv": "adverb",
    "pron": "pronoun", "prep": "preposition", "conj": "conjunction", "interj": "interjection",
    "suf": "suffix", "pref": "prefix", "affix": "affix", "article": "article",
    "particle": "particle", "cardinal": "cardinal number", "ordinal": "ordinal number",
    "fraction": "fraction", "masc-name": "masculine name", "fem-name": "feminine name",
    "place-name": "place name", "proper-name": "proper name",
    "collective-name": "collective name", "?": "uncertain",
}
LEXINFO_POS = {
    "n": "noun", "adj": "adjective", "vb": "verb", "adv": "adverb", "pron": "pronoun",
    "prep": "preposition", "conj": "conjunction", "interj": "interjection",
    "suf": "suffix", "pref": "prefix", "affix": "affix", "article": "article",
    "particle": "particle", "cardinal": "cardinalNumeral", "ordinal": "ordinalAdjective",
    "masc-name": "properNoun", "fem-name": "properNoun", "place-name": "properNoun",
    "proper-name": "properNoun", "collective-name": "properNoun",
}
# Definitions from Eldamo's "Terminology and Notations" page.
MARKS = {
    "#": "derived form, deduced from attested words",
    "†": "archaic or poetic",
    "*": "reconstructed form",
    "**": "reconstructed form",
    "?": "speculative form",
    "‽": "Tolkien marked this with a question mark",
    "^": "reformulated from an earlier version of the language",
    "!": "neologism (not by Tolkien)",
}
REL_LABELS = {
    "cognate": ("Cognates", "Words in sister languages that share the same origin."),
    "related": ("Related words", "Words Eldamo links as related in form or meaning."),
    "see_also": ("See also", "Cross-references given in the sources."),
}

NAV = [("index.html", "Home"), ("browse.html", "Browse"), ("roots.html", "Roots"),
       ("search.html", "Search"), ("linked-data.html", "Linked data"),
       ("about.html", "About"), ("accessibility.html", "Accessibility")]


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

LANGS = {r["lang_code"]: dict(r) for r in
         conn.execute("SELECT * FROM languages ORDER BY sort_order")}
CATS = {r["cat_id"]: dict(r) for r in conn.execute("SELECT * FROM categories")}
SOURCES = {r["prefix"]: r["name"] for r in conn.execute("SELECT * FROM sources")}
ENTRIES = {r["entry_id"]: dict(r) for r in
           conn.execute("SELECT * FROM entries ORDER BY lang_code, sort_key")}
BY_LANG_FORM = {(x["lang_code"], x["form"]): i for i, x in ENTRIES.items()}

OUT_LINKS = defaultdict(lambda: defaultdict(list))   # from_id -> type -> [to_id]
IN_LINKS = defaultdict(lambda: defaultdict(list))    # to_id   -> type -> [from_id]
for r in conn.execute("SELECT from_id, to_id, rel_type, citations FROM links"):
    OUT_LINKS[r["from_id"]][r["rel_type"]].append(r["to_id"])
    IN_LINKS[r["to_id"]][r["rel_type"]].append(r["from_id"])

ATTEST = defaultdict(list)
for r in conn.execute("SELECT * FROM attestations ORDER BY att_id"):
    ATTEST[r["entry_id"]].append(dict(r))

# Entries with more than two distinct links (or long commentary) get their own
# page. Shorter entries are published in full on their alphabetical index page.
# This keeps the site under 5,000 files for hosting while losing no data.
_DEG = defaultdict(set)
for _f, _t in conn.execute("SELECT from_id, to_id FROM links"):
    _DEG[_f].add(_t)
    _DEG[_t].add(_f)
FULL = {i for i, x in ENTRIES.items() if len(_DEG[i]) > 2 or len(x["notes_html"] or "") > 1500}

LANG_COUNTS = {r[0]: r[1] for r in
               conn.execute("SELECT lang_code, COUNT(*) FROM entries GROUP BY lang_code")}
STATS = {
    "entries": len(ENTRIES),
    "attestations": conn.execute("SELECT COUNT(*) FROM attestations").fetchone()[0],
    "links": conn.execute("SELECT COUNT(*) FROM links").fetchone()[0],
    "roots": sum(1 for x in ENTRIES.values() if x["speech"] == "root"),
}


def sort_by_form(ids):
    return sorted(set(ids), key=lambda i: (LANGS[ENTRIES[i]["lang_code"]]["sort_order"],
                                           ENTRIES[i]["sort_key"]))


def letter_of(entry):
    k = entry["sort_key"][:1]
    return k if k.isalpha() and k.isascii() else "other"


def index_page(eid):
    x = ENTRIES[eid]
    if LANG_COUNTS[x["lang_code"]] > 400:
        return f'lang/{x["lang_code"]}-{letter_of(x)}.html'
    return f'lang/{x["lang_code"]}.html'


def href(eid, pre):
    return f"{pre}entry/{eid}.html" if eid in FULL else f"{pre}{index_page(eid)}#w{eid}"


def iri(eid, pre):
    return f"{pre}entry/{eid}.html#entry" if eid in FULL else f"{pre}{index_page(eid)}#w{eid}"


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def headword(entry, tag="span"):
    """Render an Elvish form with the correct lang attribute.
    Eldamo's √ (root) and ✶ (primitive form) symbols are hidden from screen
    readers and replaced with a spoken word."""
    lang = LANGS[entry["lang_code"]]["bcp47"]
    prefix = ""
    if entry["speech"] == "root":
        prefix = '<span class="sym" aria-hidden="true">√</span><span class="visually-hidden">root </span>'
    elif entry["lang_code"] == "p":
        prefix = ('<span class="sym" aria-hidden="true">✶</span>'
                  '<span class="visually-hidden">primitive form </span>')
    return f'{prefix}<{tag} lang="{lang}" class="elv">{e(entry["form"])}</{tag}>'


def word_link(eid, pre, show_lang=True, show_gloss=True):
    x = ENTRIES[eid]
    parts = [f'<a href="{href(eid, pre)}">{headword(x)}</a>']
    if show_lang:
        parts.append(f'<span class="lang-name">{e(LANGS[x["lang_code"]]["name"])}</span>')
    if show_gloss and x["gloss"]:
        parts.append(f'<span class="gloss">“{e(x["gloss"])}”</span>')
    return " ".join(parts)


def page(path, title, body, pre="", current=None, description="", head_extra=""):
    nav = "\n".join(
        f'<li><a href="{pre}{href}"{" aria-current=\"page\"" if href == current else ""}>{label}</a></li>'
        for href, label in NAV)
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · Eldarin Etymological Lexicon</title>
<meta name="description" content="{e(description or 'An accessible, linked-data dictionary of Tolkien’s Elvish languages and their etymologies.')}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E%3Ctext x=%2216%22 y=%2225%22 font-size=%2226%22 text-anchor=%22middle%22 fill=%22%237d5f17%22%3E%E2%9C%B6%3C/text%3E%3C/svg%3E">
<link rel="stylesheet" href="{pre}assets/style.css">
<script>try{{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
{head_extra}
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="{pre}index.html"><span class="brand-mark" aria-hidden="true">✶</span> Eldarin Etymological Lexicon</a>
    <button type="button" class="theme-toggle" aria-pressed="false" data-theme-toggle>Dark theme</button>
  </div>
  <nav class="wrap" aria-label="Main">
    <ul class="nav-list">
{nav}
    </ul>
  </nav>
</header>
<main id="main" tabindex="-1" class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>Lexical data from <a href="https://eldamo.org">Eldamo</a> by Paul Strack, used under the
    <a href="https://creativecommons.org/licenses/by/4.0/">Creative Commons Attribution 4.0 license</a>.
    The Elvish languages were created by J.R.R. Tolkien. This is a non-commercial educational project
    and is not affiliated with the Tolkien Estate.</p>
    <p><a href="{pre}accessibility.html">Accessibility statement</a> · <a href="{pre}linked-data.html">Data and downloads</a> · <a href="{pre}about.html">About this project</a></p>
  </div>
</footer>
<script src="{pre}assets/site.js" defer></script>
</body>
</html>
"""
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(doc, encoding="utf-8")


def breadcrumbs(items, pre):
    lis = []
    for i, (href, label) in enumerate(items):
        if i == len(items) - 1:
            lis.append(f'<li><a href="{href}" aria-current="page">{label}</a></li>' if href
                       else f'<li aria-current="page">{label}</li>')
        else:
            lis.append(f'<li><a href="{pre}{href}">{label}</a></li>')
    return f'<nav aria-label="Breadcrumb" class="breadcrumbs"><ol>{"".join(lis)}</ol></nav>'


# ---------------------------------------------------------------------------
# Notes (Eldamo commentary): rewrite internal links
# ---------------------------------------------------------------------------
A_LV = re.compile(r'<a l="([^"]*)" v="([^"]*)">(.*?)</a>', re.S)
A_HREF = re.compile(r'href="(?!https?:|mailto:|#)([^"]*)"')


def convert_notes(raw, pre):
    if not raw:
        return ""
    def repl(m):
        key = (m.group(1), html.unescape(m.group(2)))
        eid = BY_LANG_FORM.get(key)
        inner = m.group(3)
        if eid:
            lang = LANGS[key[0]]["bcp47"]
            return f'<a href="{href(eid, pre)}" lang="{lang}">{inner}</a>'
        return inner
    out = A_LV.sub(repl, raw)
    out = A_HREF.sub(lambda m: f'href="{urljoin(ELDAMO_BASE, m.group(1))}"', out)
    # Notes use <i> for cited forms; promote to <cite>-free emphasis that keeps semantics simple.
    return out


# ---------------------------------------------------------------------------
# Etymology trees
# ---------------------------------------------------------------------------
_REACH = {}


def reachable(eid, stack=()):
    """All ancestors of an entry (following derived_from links)."""
    if eid in _REACH:
        return _REACH[eid]
    out = set()
    for p in OUT_LINKS[eid]["derived_from"]:
        if p not in stack and p != eid:
            out.add(p)
            out |= reachable(p, stack + (eid,))
    if not stack:
        _REACH[eid] = out
    return out


def direct_parents(eid):
    """Parents with redundant shortcuts removed: if Q. elen derives from both
    ✶elen and √EL, and ✶elen itself derives from √EL, only ✶elen is kept."""
    parents = set(OUT_LINKS[eid]["derived_from"]) - {eid}
    keep = [p for p in parents if not any(p in reachable(q) for q in parents if q != p)]
    # Prefer word forms over roots so the summary walks the full chain.
    return sorted(sort_by_form(keep), key=lambda i: ENTRIES[i]["speech"] == "root")


def ancestor_tree(eid, pre, seen=None, depth=0):
    seen = (seen or set()) | {eid}
    parents = [p for p in direct_parents(eid) if p not in seen]
    if not parents or depth > 6:
        return ""
    items = []
    for p in parents:
        items.append(f"<li>from {word_link(p, pre)}{ancestor_tree(p, pre, seen, depth + 1)}</li>")
    return f'<ul class="tree">{"".join(items)}</ul>'


def descendant_tree(eid, pre, depth=0, seen=None):
    seen = (seen or set()) | {eid}
    kids = [k for k in sort_by_form(IN_LINKS[eid]["derived_from"]) if k not in seen]
    if not kids or depth > 2:
        return ""
    items = [f"<li>{word_link(k, pre)}{descendant_tree(k, pre, depth + 1, seen)}</li>" for k in kids]
    return f'<ul class="tree">{"".join(items)}</ul>'


def ancestry_sentence(eid):
    """Plain-language summary, e.g. 'Quenya elen comes from Primitive Elvish ✶elen, from the root √EL.'"""
    chain, cur, seen = [], eid, {eid}
    while True:
        parents = [p for p in direct_parents(cur) if p not in seen]
        if not parents:
            break
        cur = parents[0]
        seen.add(cur)
        chain.append(cur)
        if len(chain) > 6:
            break
    if not chain:
        return ""
    def describe(i):
        x = ENTRIES[i]
        kind = "the root" if x["speech"] == "root" else LANGS[x["lang_code"]]["name"]
        return f'{kind} {headword(x)}'
    x = ENTRIES[eid]
    s = f'{e(LANGS[x["lang_code"]]["name"])} {headword(x)} comes from {describe(chain[0])}'
    for i in chain[1:]:
        s += f", from {describe(i)}"
    return f'<p class="summary">{s}.</p>'


# ---------------------------------------------------------------------------
# Linked data
# ---------------------------------------------------------------------------
CONTEXT = {
    "ontolex": "http://www.w3.org/ns/lemon/ontolex#",
    "decomp": "http://www.w3.org/ns/lemon/decomp#",
    "lexinfo": "http://www.lexinfo.net/ontology/3.0/lexinfo#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dct": "http://purl.org/dc/terms/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "eld": "../linked-data.html#",
}


def lang_iri(code, pre):
    if LANGS[code]["bcp47"] in ("qya", "sjn"):
        return f'http://lexvo.org/id/iso639-3/{LANGS[code]["bcp47"]}'
    return f"{pre}browse.html#lang-{code}"


def entry_jsonld(eid, pre):
    x = ENTRIES[eid]
    node_base = f"{pre}entry/{eid}.html" if eid in FULL else f"{pre}{index_page(eid)}#w{eid}-"
    node = {
        "@id": iri(eid, pre),
        "@type": "ontolex:Etymon" if x["speech"] == "root" else "ontolex:LexicalEntry",
        "rdfs:label": {"@value": x["form"], "@language": LANGS[x["lang_code"]]["bcp47"]},
        "ontolex:canonicalForm": {
            "@id": (node_base + "#form") if eid in FULL else node_base + "form",
            "@type": "ontolex:Form",
            "ontolex:writtenRep": {"@value": x["form"], "@language": LANGS[x["lang_code"]]["bcp47"]},
        },
        "dct:language": {"@id": lang_iri(x["lang_code"], pre)},
        "rdfs:seeAlso": {"@id": ELDAMO_WORD.format(eid)},
    }
    if x["gloss"]:
        node["ontolex:sense"] = {
            "@id": (node_base + "#sense") if eid in FULL else node_base + "sense",
            "@type": "ontolex:LexicalSense",
            "skos:definition": {"@value": x["gloss"], "@language": "en"},
        }
    if x["speech"] in LEXINFO_POS:
        node["lexinfo:partOfSpeech"] = {"@id": "lexinfo:" + LEXINFO_POS[x["speech"]]}
    if x["cat_id"]:
        node["dct:subject"] = CATS[x["cat_id"]]["label"]
    props = {"derived_from": "eld:derivedFrom", "has_element": "decomp:subterm",
             "cognate": "eld:cognateWith", "related": "eld:relatedTo", "see_also": "rdfs:seeAlso"}
    for rel, prop in props.items():
        targets = sort_by_form(OUT_LINKS[eid][rel])
        if targets:
            vals = [{"@id": iri(t, pre)} for t in targets]
            if prop == "rdfs:seeAlso":
                vals = [node["rdfs:seeAlso"]] + vals
            node[prop] = vals
    return node


def ttl_literal(value, lang):
    v = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{v}"@{lang}'


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def build_entry(eid):
    pre = "../"
    x = ENTRIES[eid]
    L = LANGS[x["lang_code"]]
    lang_page = index_page(eid)
    crumbs = breadcrumbs([("index.html", "Home"), ("browse.html", "Browse"),
                          (lang_page, e(L["name"])), (None, e(x["form"]))], pre)

    mark = ""
    if x["mark"]:
        desc = "; ".join(MARKS[m] for m in sorted(MARKS, key=len, reverse=True)
                         if m in x["mark"] and not (m == "*" and "**" in x["mark"])) or "editorial mark in Eldamo"
        mark = f'<p class="mark-note"><span aria-hidden="true">{e(x["mark"])}</span> <span>Status: {e(desc)}.</span></p>'

    facts = [("Language", f'<a href="{pre}{lang_page}">{e(L["name"])}</a>'),
             ("Part of speech", e(POS_LABELS.get(x["speech"], x["speech"] or "—")))]
    if x["gloss"]:
        facts.append(("Meaning", f'“{e(x["gloss"])}”'))
    if x["ngloss"] and x["ngloss"] != x["gloss"]:
        facts.append(("Meaning, incl. earlier conceptions", f'“{e(x["ngloss"])}”'))
    if x["stem"]:
        facts.append(("Stem", f'<span lang="{L["bcp47"]}" class="elv">{e(x["stem"])}</span>'))
    if x["cat_id"]:
        c = CATS[x["cat_id"]]
        facts.append(("Semantic category", f'{e(c["group_label"])} › {e(c["label"])}'))
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    sections = []
    toc = []

    def section(sid, title, content, intro=""):
        toc.append((sid, title))
        intro_html = f'<p class="section-intro">{intro}</p>' if intro else ""
        sections.append(f'<section aria-labelledby="{sid}"><h2 id="{sid}">{title}</h2>{intro_html}{content}</section>')

    anc = ancestor_tree(eid, pre)
    if anc:
        section("etymology", "Etymology", ancestry_sentence(eid) + anc,
                "Each level shows the older form a word developed from.")
    desc_tree = descendant_tree(eid, pre)
    if desc_tree:
        n = len(set(IN_LINKS[eid]["derived_from"]))
        section("derivatives", f"Derived words ({n})", desc_tree,
                "Later words that developed from this one, up to three generations.")
    elements = sort_by_form(OUT_LINKS[eid]["has_element"])
    if elements:
        section("elements", "Built from", "<ul class=\"word-list\">" +
                "".join(f"<li>{word_link(i, pre)}</li>" for i in elements) + "</ul>",
                "The parts that make up this compound or name.")
    used_in = sort_by_form(IN_LINKS[eid]["has_element"])
    if used_in:
        items = "".join(f"<li>{word_link(i, pre)}</li>" for i in used_in)
        section("compounds", f"Used in ({len(used_in)})", f'<ul class="word-list cols">{items}</ul>',
                "Compounds and names that contain this word.")
    for rel in ("cognate", "related", "see_also"):
        ids = sort_by_form(OUT_LINKS[eid][rel] + IN_LINKS[eid][rel])
        if ids:
            title, intro = REL_LABELS[rel]
            section(rel.replace("_", "-"), title, "<ul class=\"word-list\">" +
                    "".join(f"<li>{word_link(i, pre)}</li>" for i in ids) + "</ul>", intro)
    notes = convert_notes(x["notes_html"], pre)
    if notes:
        section("notes", "Notes", f'<div class="notes">{notes}</div>',
                'Commentary by Paul Strack from <a href="' + ELDAMO_WORD.format(eid) + '">this word’s Eldamo entry</a>.')
    atts = ATTEST[eid]
    if atts:
        rows = "".join(
            f'<tr><td><span lang="{L["bcp47"]}" class="elv">{e(a["form"])}</span></td>'
            f'<td>{e(a["gloss"] or "—")}</td><td>{e(a["inflection"] or "—")}</td>'
            f'<td>{e(SOURCES.get(a["source_prefix"], a["source_prefix"]))} <span class="cite">{e(a["source"])}</span></td></tr>'
            for a in atts)
        table = (f'<div class="table-scroll" role="region" aria-labelledby="att-caption" tabindex="0"><table>'
                 f'<caption id="att-caption">Every place this word appears in Tolkien’s writings ({len(atts)})</caption>'
                 f'<thead><tr><th scope="col">Form</th><th scope="col">Gloss in source</th>'
                 f'<th scope="col">Grammatical form</th><th scope="col">Source</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>')
        section("attestations", f"Attestations ({len(atts)})", table)

    ld = entry_jsonld(eid, "../")
    ld_doc = {"@context": CONTEXT, **ld}
    ld_text = json.dumps(ld_doc, ensure_ascii=False, indent=2)
    section("linked-data", "Linked data",
            f'<p>This entry’s identifier is <code>entry/{eid}.html#entry</code>. The same data is embedded in this page as JSON-LD '
            f'using the <a href="{pre}linked-data.html">OntoLex-Lemon model</a>. It matches '
            f'<a href="{ELDAMO_WORD.format(eid)}">Eldamo word {eid}</a>.</p>'
            f'<details><summary>Show the JSON-LD for this entry</summary><pre class="code" tabindex="0"><code>{e(ld_text)}</code></pre></details>')

    toc_html = ""
    if len(toc) > 2:
        toc_html = ('<nav aria-label="On this page" class="toc"><h2 class="toc-title">On this page</h2><ul>' +
                    "".join(f'<li><a href="#{sid}">{t}</a></li>' for sid, t in toc) + "</ul></nav>")

    body = f"""{crumbs}
<article class="entry">
  <header class="entry-head">
    <p class="eyebrow">{e(L["name"])} · {e(POS_LABELS.get(x["speech"], x["speech"] or ""))}</p>
    <h1>{headword(x)}</h1>
    {f'<p class="lede">“{e(x["gloss"])}”</p>' if x["gloss"] else ""}
    {mark}
  </header>
  <div class="entry-layout">
    <div class="entry-main">
      <dl class="facts">{dl}</dl>
      {"".join(sections)}
    </div>
    {toc_html}
  </div>
</article>"""
    title = f'{x["form"]} ({L["name"]})'
    head = f'<script type="application/ld+json">{ld_text.replace("</", "<\\/")}</script>'
    desc = f'{L["name"]} {POS_LABELS.get(x["speech"], "")} “{x["gloss"] or ""}”: etymology, related words and attestations.'
    page(f"entry/{eid}.html", title, body, pre, description=desc, head_extra=head)


def family_tree(pre, code=None):
    kids = [c for c, L in LANGS.items() if L["parent_code"] == code]
    if not kids:
        return ""
    items = []
    for c in kids:
        L = LANGS[c]
        href = f"{pre}lang/{c}.html"
        items.append(f'<li id="lang-{c}"><a href="{href}">{e(L["name"])}</a> '
                     f'<span class="count">{LANG_COUNTS.get(c, 0):,} entries</span>'
                     f'<span class="lang-desc"> — {e(L["description"])}</span>{family_tree(pre, c)}</li>')
    return f'<ul class="family">{"".join(items)}</ul>'


def short_entry(eid, pre, level):
    """A complete, compact entry shown inline on an index page."""
    x = ENTRIES[eid]
    L = LANGS[x["lang_code"]]
    h = f"h{level}"
    meta = [e(POS_LABELS.get(x["speech"], x["speech"] or ""))]
    if x["cat_id"]:
        meta.append(e(CATS[x["cat_id"]]["label"]))
    rows = []
    rel_names = [("derived_from", "From", False), ("has_element", "Built from", False),
                 ("cognate", "Cognate", True), ("related", "Related", True), ("see_also", "See also", True)]
    for rel, label, sym in rel_names:
        ids = OUT_LINKS[eid][rel] + (IN_LINKS[eid][rel] if sym else [])
        if ids:
            rows.append(f"<div><dt>{label}</dt><dd>" + "; ".join(word_link(i, pre) for i in sort_by_form(ids)) + "</dd></div>")
    for rel, label in [("derived_from", "Derived words"), ("has_element", "Used in")]:
        ids = IN_LINKS[eid][rel]
        if ids:
            rows.append(f"<div><dt>{label}</dt><dd>" + "; ".join(word_link(i, pre) for i in sort_by_form(ids)) + "</dd></div>")
    if x["mark"]:
        desc = "; ".join(MARKS[m] for m in sorted(MARKS, key=len, reverse=True)
                         if m in x["mark"] and not (m == "*" and "**" in x["mark"])) or "editorial mark in Eldamo"
        rows.append(f'<div><dt>Status</dt><dd><span aria-hidden="true">{e(x["mark"])}</span> {e(desc)}</dd></div>')
    extra = ""
    notes = convert_notes(x["notes_html"], pre)
    if notes:
        extra += f'<details><summary>Notes<span class="visually-hidden"> on {e(x["form"])}</span></summary><div class="notes">{notes}</div></details>'
    atts = ATTEST[eid]
    if atts:
        lis = "".join(
            f'<li><span lang="{L["bcp47"]}" class="elv">{e(a["form"])}</span>'
            f'{" “" + e(a["gloss"]) + "”" if a["gloss"] else ""}{" (" + e(a["inflection"]) + ")" if a["inflection"] else ""}'
            f' — {e(SOURCES.get(a["source_prefix"], a["source_prefix"]))} <span class="cite">{e(a["source"])}</span></li>'
            for a in atts)
        extra += (f'<details><summary>{len(atts)} attestation{"s" if len(atts) != 1 else ""}'
                  f'<span class="visually-hidden"> of {e(x["form"])}</span></summary><ul class="att-list">{lis}</ul></details>')
    dl = f'<dl class="mini">{"".join(rows)}</dl>' if rows else ""
    gloss = f' <span class="gloss">“{e(x["gloss"])}”</span>' if x["gloss"] else ""
    return (f'<article class="short-entry" id="w{eid}" aria-labelledby="h-w{eid}">'
            f'<{h} id="h-w{eid}" class="short-head">{headword(x)}</{h}>'
            f'<p class="short-meta">{" · ".join(meta)}{gloss}</p>{dl}{extra}'
            f'<p class="short-src"><a href="{ELDAMO_WORD.format(eid)}">Eldamo entry<span class="visually-hidden"> for {e(x["form"])}</span></a></p>'
            f'</article>')


def build_lang_pages():
    for code, L in LANGS.items():
        ids = [i for i, x in ENTRIES.items() if x["lang_code"] == code]
        ids.sort(key=lambda i: ENTRIES[i]["sort_key"])
        letters = defaultdict(list)
        for i in ids:
            letters[letter_of(ENTRIES[i])].append(i)
        order = sorted(k for k in letters if k != "other") + (["other"] if "other" in letters else [])
        big = len(ids) > 400
        pre = "../"

        def letter_nav(active=None):
            lis = []
            for k in order:
                label = "Other" if k == "other" else k.upper()
                href = f"{code}-{k}.html" if big else f"#letter-{k}"
                cur = ' aria-current="page"' if k == active else ""
                lis.append(f'<li><a href="{href}"{cur}><span class="visually-hidden">Letter </span>{label}'
                           f'<span class="visually-hidden">, {len(letters[k])} entries</span></a></li>')
            return f'<nav aria-label="Alphabetical index" class="letters"><ul>{"".join(lis)}</ul></nav>'

        def word_list(id_list, level):
            items = []
            for i in id_list:
                if i in FULL:
                    items.append(f'<li class="full">{word_link(i, pre, show_lang=False)}'
                                 f' <span class="count">full entry</span></li>')
                else:
                    items.append(f"<li>{short_entry(i, pre, level)}</li>")
            return '<ul class="word-list index-list">' + "".join(items) + "</ul>"

        def page_ld(id_list):
            graph = [entry_jsonld(i, pre) for i in id_list if i not in FULL]
            if not graph:
                return ""
            txt = json.dumps({"@context": CONTEXT, "@graph": graph}, ensure_ascii=False)
            return f'<script type="application/ld+json">{txt.replace("</", "<\\/")}</script>'

        intro = (f'<h1>{e(L["name"])}</h1><p class="lede">{e(L["description"])}. '
                 f'{len(ids):,} entries.</p>')
        if L["parent_code"]:
            intro += f'<p>Descends from <a href="{L["parent_code"]}.html">{e(LANGS[L["parent_code"]]["name"])}</a>.</p>'
        crumbs = [("index.html", "Home"), ("browse.html", "Browse")]
        if big:
            body = breadcrumbs(crumbs + [(None, e(L["name"]))], pre) + intro + letter_nav() + \
                "<p>Choose a letter to see entries.</p>"
            page(f"lang/{code}.html", L["name"], body, pre, current=None)
            for k in order:
                label = "Other" if k == "other" else k.upper()
                body = (breadcrumbs(crumbs + [(f"lang/{code}.html", e(L["name"])), (None, label)], pre) +
                        f'<h1>{e(L["name"])}: {label}</h1>'
                        f'<p class="lede">{len(letters[k]):,} entries. Words with many links have their own page; shorter entries are shown in full below.</p>' + letter_nav(k) + word_list(letters[k], 2))
                page(f"lang/{code}-{k}.html", f'{L["name"]}: {label}', body, pre, head_extra=page_ld(letters[k]))
        else:
            parts = [breadcrumbs(crumbs + [(None, e(L["name"]))], pre), intro, letter_nav()]
            for k in order:
                label = "Other" if k == "other" else k.upper()
                parts.append(f'<section aria-labelledby="letter-{k}"><h2 id="letter-{k}">{label}</h2>{word_list(letters[k], 3)}</section>')
            page(f"lang/{code}.html", L["name"], "".join(parts), pre, head_extra=page_ld(ids))


def build_static_pages():
    pre = ""
    # ---------- Home ----------
    roots = [i for i, x in ENTRIES.items() if x["speech"] == "root"]
    top_roots = sorted(roots, key=lambda i: -len(set(IN_LINKS[i]["derived_from"])))[:8]
    featured = [BY_LANG_FORM.get(k) for k in [("q", "elen"), ("s", "galadh"), ("q", "Elendil"),
                                              ("s", "mellon"), ("q", "lómë"), ("s", "Imladris")]]
    featured = [f for f in featured if f]
    body = f"""
<section class="hero" aria-labelledby="hero-title">
  <p class="eyebrow">A digital humanities project</p>
  <h1 id="hero-title">The words behind the words of Middle-earth</h1>
  <p class="lede">Tolkien built his Elvish languages like a historical linguist: every Quenya and Sindarin word descends from older forms and ancient roots. This lexicon links {STATS["entries"]:,} words through {STATS["links"]:,} etymological relationships, so you can follow a word back to its origin or forward to its descendants.</p>
  <form class="search-form" role="search" action="search.html" method="get">
    <label for="home-q">Search Elvish words or English meanings</label>
    <div class="search-row">
      <input id="home-q" name="q" type="search" autocomplete="off" placeholder="for example: star, galadh, √KAL">
      <button type="submit">Search</button>
    </div>
  </form>
</section>

<section aria-labelledby="stats-title" class="stats-section">
  <h2 id="stats-title" class="visually-hidden">The lexicon in numbers</h2>
  <ul class="stats">
    <li><span class="stat-num">{STATS["entries"]:,}</span> <span class="stat-label">dictionary entries</span></li>
    <li><span class="stat-num">{STATS["roots"]:,}</span> <span class="stat-label">Primitive Elvish roots</span></li>
    <li><span class="stat-num">{STATS["links"]:,}</span> <span class="stat-label">links between words</span></li>
    <li><span class="stat-num">{STATS["attestations"]:,}</span> <span class="stat-label">citations in Tolkien’s writings</span></li>
  </ul>
</section>

<div class="two-col">
<section aria-labelledby="family-title">
  <h2 id="family-title">The Elvish language family</h2>
  <p>All Elvish languages descend from Primitive Elvish. This tree covers Tolkien’s late conception of the languages (1950–1973).</p>
  {family_tree(pre)}
</section>

<section aria-labelledby="start-title">
  <h2 id="start-title">Start exploring</h2>
  <ul class="word-list featured">
    {"".join(f"<li>{word_link(i, pre)}</li>" for i in featured)}
  </ul>
  <h3>Most productive roots</h3>
  <ol class="word-list">
    {"".join(f'<li>{word_link(i, pre, show_lang=False)} <span class="count">{len(set(IN_LINKS[i]["derived_from"]))} derived words</span></li>' for i in top_roots)}
  </ol>
  <p><a href="roots.html">See all {STATS["roots"]:,} roots</a></p>
</section>
</div>
"""
    page("index.html", "Home", body, pre, current="index.html")

    # ---------- Browse ----------
    body = f"""<h1>Browse by language</h1>
<p class="lede">Languages are arranged by descent. Each language has an alphabetical index.</p>
{family_tree(pre)}
"""
    page("browse.html", "Browse", body, pre, current="browse.html")

    # ---------- Roots ----------
    rows = []
    for i in sorted(roots, key=lambda i: ENTRIES[i]["sort_key"]):
        x = ENTRIES[i]
        n_der = len(set(IN_LINKS[i]["derived_from"]))
        rows.append(f'<tr><th scope="row"><a href="{href(i, "")}">{headword(x)}</a></th>'
                    f'<td>{e(x["gloss"] or "—")}</td><td class="num">{n_der}</td></tr>')
    body = f"""<h1>Primitive Elvish roots</h1>
<p class="lede">Roots are the building blocks of Tolkien’s Elvish vocabulary. Tolkien wrote them in capital letters, marked here with √. Select a root to see the words that grew from it.</p>
<div class="table-scroll" role="region" aria-labelledby="roots-caption" tabindex="0">
<table class="roots-table">
<caption id="roots-caption">All {len(roots):,} roots, in alphabetical order, with the number of words directly derived from each</caption>
<thead><tr><th scope="col">Root</th><th scope="col">Meaning</th><th scope="col" class="num">Derived words</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>"""
    page("roots.html", "Roots", body, pre, current="roots.html")

    # ---------- Search ----------
    opts = "".join(f'<option value="{c}">{e(L["name"])}</option>' for c, L in LANGS.items())
    body = f"""<h1>Search the lexicon</h1>
<form class="search-form" role="search" id="search-form" action="search.html" method="get">
  <div class="field">
    <label for="q">Elvish word or English meaning</label>
    <input id="q" name="q" type="search" autocomplete="off" aria-describedby="q-hint">
    <p id="q-hint" class="hint">Accents are optional: “lome” finds <span lang="qya">lómë</span>.</p>
  </div>
  <div class="field">
    <label for="lang">Language</label>
    <select id="lang" name="lang"><option value="">All languages</option>{opts}</select>
  </div>
  <div class="field">
    <span id="mode-label" class="label">Search in</span>
    <div class="radio-row" role="radiogroup" aria-labelledby="mode-label">
      <label><input type="radio" name="mode" value="all" checked> Words and meanings</label>
      <label><input type="radio" name="mode" value="form"> Elvish words only</label>
      <label><input type="radio" name="mode" value="gloss"> English meanings only</label>
    </div>
  </div>
  <button type="submit">Search</button>
</form>
<noscript><p class="notice">Search needs JavaScript. You can still <a href="browse.html">browse every language alphabetically</a>.</p></noscript>
<p id="search-status" class="search-status" role="status" aria-live="polite"></p>
<ul id="results" class="word-list results"></ul>
"""
    page("search.html", "Search", body, pre, current="search.html",
         head_extra='<script src="assets/search.js" defer></script>')

    # ---------- Linked data ----------
    elen = BY_LANG_FORM[("q", "elen")]
    sample = json.dumps({"@context": CONTEXT, **entry_jsonld(elen, "")}, ensure_ascii=False, indent=2)
    body = f"""<h1>Linked data</h1>
<p class="lede">Every entry is published as machine-readable linked data, so other projects can reuse and connect to it.</p>

<section aria-labelledby="model"><h2 id="model">Data model</h2>
<p>Entries follow the W3C <a href="https://www.w3.org/2016/05/ontolex/">OntoLex-Lemon</a> model for lexical resources. Each word has three identifiers on its page:</p>
<ul>
<li><code>entry/ID.html#entry</code> is the word itself (an <code>ontolex:LexicalEntry</code>, or an <code>ontolex:Etymon</code> for roots). Shorter entries that appear on an index page use the identifier <code>lang/PAGE.html#wID</code> instead.</li>
<li><code>#form</code> is its written form, tagged with a language code.</li>
<li><code>#sense</code> is its English meaning.</li>
</ul>
<p>The page address and the word are kept apart: the page is a document about the word, while the <code>#entry</code> identifier stands for the word. All identifiers are relative, so the data stays valid wherever the site is hosted.</p>
<p>Quenya and Sindarin use their ISO 639-3 codes, <code>qya</code> and <code>sjn</code>, and link to <a href="http://www.lexvo.org/">Lexvo</a>. The other Elvish languages have no official code, so they use private-use language tags such as <code>art-x-telerin</code>.</p>
</section>

<section aria-labelledby="vocab"><h2 id="vocab">Vocabulary</h2>
<p>Standard properties are used where they exist. Three properties are defined by this project in the <code>eld:</code> namespace.</p>
<dl class="vocab">
<div><dt id="derivedFrom"><code>eld:derivedFrom</code></dt><dd>The subject developed historically from the object, for example Quenya <span lang="qya">elen</span> from Primitive Elvish <span lang="art-x-prelv">elen</span>. This is a direct etymological link and can be chained.</dd></div>
<div><dt id="cognateWith"><code>eld:cognateWith</code></dt><dd>The two words come from the same older form in sister languages, for example Quenya <span lang="qya">elen</span> and Sindarin <span lang="sjn">êl</span>. Symmetric.</dd></div>
<div><dt id="relatedTo"><code>eld:relatedTo</code></dt><dd>A looser connection in form or meaning noted in the sources. A sub-property of <code>rdfs:seeAlso</code>.</dd></div>
<div><dt><code>decomp:subterm</code></dt><dd>From the OntoLex decomposition module: the parts of a compound, for example <span lang="qya">Elendil</span> contains <span lang="qya">elen</span>.</dd></div>
<div><dt><code>rdfs:seeAlso</code></dt><dd>Links each entry to its source page in Eldamo, plus cross-references.</dd></div>
</dl>
</section>

<section aria-labelledby="example"><h2 id="example">Example: Quenya <span lang="qya">elen</span>, “star”</h2>
<pre class="code" tabindex="0" aria-label="JSON-LD example"><code>{e(sample)}</code></pre>
</section>

<section aria-labelledby="downloads"><h2 id="downloads">Downloads</h2>
<ul>
<li><a href="data/lexicon.ttl">lexicon.ttl</a>: the full dataset as RDF in Turtle format</li>
<li><a href="data/lexicon.jsonld">lexicon.jsonld</a>: the full dataset as JSON-LD</li>
<li><a href="data/entries.csv">entries.csv</a>: one row per entry, for spreadsheets</li>
<li><a href="data/lexicon.db">lexicon.db</a>: the SQLite database that generates this site</li>
</ul>
<p>The data is derived from Eldamo and shared under the same <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0 license</a>. Please credit Paul Strack’s Eldamo when reusing it.</p>
</section>
"""
    page("linked-data.html", "Linked data", body, pre, current="linked-data.html")

    # ---------- About ----------
    body = f"""<h1>About this project</h1>
<p class="lede">The Eldarin Etymological Lexicon is an accessible, linked-data dictionary of Tolkien’s late-period Elvish languages. It focuses on the connections between words: their roots, derivations, compounds and cognates.</p>

<section aria-labelledby="source"><h2 id="source">Source data</h2>
<p>The lexical data comes from <a href="https://eldamo.org">Eldamo</a> (Elvish Data Model), a scholarly lexicon by Paul Strack that records each word with citations to Tolkien’s published writings and linguistic papers. Eldamo publishes its full XML data model under a Creative Commons Attribution license. This project uses the subset for Tolkien’s late conception of the languages (1950–1973): Primitive Elvish and its descendants. Phonology notes, grammar notes and phrases are left out, keeping dictionary headwords only.</p>
</section>

<section aria-labelledby="pipeline"><h2 id="pipeline">How it is built</h2>
<p>Two Python scripts, using only the standard library, turn the data into this website:</p>
<ol class="steps">
<li><strong><code>build_db.py</code></strong> reads Eldamo’s XML and loads it into a relational SQLite database. Eldamo records etymological links in two ways: on a word (by language and form) and on individual citations (by source reference). The script resolves both into one table of word-to-word links and keeps the citation as evidence.</li>
<li><strong><code>build_site.py</code></strong> queries the database and writes the website. Words with more than two etymological links get their own page; shorter entries are published in full on their alphabetical index page. It also writes the search index and the RDF exports.</li>
</ol>
</section>

<section aria-labelledby="schema"><h2 id="schema">Database schema</h2>
<div class="table-scroll" role="region" aria-labelledby="schema-caption" tabindex="0">
<table>
<caption id="schema-caption">Tables in lexicon.db</caption>
<thead><tr><th scope="col">Table</th><th scope="col">Contents</th><th scope="col" class="num">Rows</th></tr></thead>
<tbody>
<tr><th scope="row"><code>languages</code></th><td>Elvish languages, their language tags and parent language</td><td class="num">{len(LANGS)}</td></tr>
<tr><th scope="row"><code>entries</code></th><td>Dictionary headwords: form, part of speech, meaning, category, notes</td><td class="num">{STATS["entries"]:,}</td></tr>
<tr><th scope="row"><code>attestations</code></th><td>Each appearance of a word in a source, with citation</td><td class="num">{STATS["attestations"]:,}</td></tr>
<tr><th scope="row"><code>relations</code></th><td>Links between entries (derived from, has element, cognate, related, see also) with the citation that supports each</td><td class="num">{conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]:,}</td></tr>
<tr><th scope="row"><code>categories</code></th><td>Semantic categories (for example “Physical World › Sea”)</td><td class="num">{len(CATS):,}</td></tr>
<tr><th scope="row"><code>sources</code></th><td>Bibliographic sources cited</td><td class="num">{len(SOURCES):,}</td></tr>
</tbody>
</table>
</div>
<p>A view called <code>links</code> collapses <code>relations</code> into one row per distinct link with a count of supporting citations. Etymology chains are found with a recursive SQL query. See the project README for examples.</p>
</section>

<section aria-labelledby="notation"><h2 id="notation">Notation</h2>
<dl class="vocab">
<div><dt><span aria-hidden="true">√</span> root</dt><dd>A primitive base or root, such as <span lang="art-x-prelv">EL</span> “star”. Screen readers hear the word “root” in place of the symbol.</dd></div>
<div><dt><span aria-hidden="true">✶</span> primitive form</dt><dd>A word form in Primitive Elvish.</dd></div>
<div><dt>Status marks</dt><dd>Some entries carry Eldamo’s editorial marks, for example † for archaic or poetic words and * for reconstructed forms. Each mark is spelled out in words on the entry page.</dd></div>
</dl>
<p>Definitions follow Eldamo’s <a href="https://pfstrack.github.io/eldamo/general/terminology-and-notations.html">Terminology and Notations</a> page.</p>
</section>
"""
    page("about.html", "About", body, pre, current="about.html")

    # ---------- Accessibility statement ----------
    body = """<h1>Accessibility statement</h1>
<p class="lede">This site aims to meet the Web Content Accessibility Guidelines (WCAG) 2.2 at level AA. Its design follows the principles of universal design, so the same pages work for everyone, without a separate “accessible version”.</p>

<section aria-labelledby="features"><h2 id="features">What we have done</h2>
<h3>Perceivable</h3>
<ul>
<li><strong>Language of parts (WCAG 3.1.2):</strong> every Elvish word is marked with a language tag (<code>lang="qya"</code> for Quenya, <code>lang="sjn"</code> for Sindarin). This lets assistive technology and translation tools know the text is not English.</li>
<li><strong>Symbols explained in words:</strong> Eldamo’s √ and ✶ symbols are hidden from screen readers and replaced by the spoken words “root” and “primitive form”. Status marks such as † are always spelled out in text.</li>
<li><strong>Color contrast (1.4.3, 1.4.11):</strong> text and interface elements meet at least 4.5:1 and 3:1 contrast in both light and dark themes.</li>
<li><strong>Not color alone (1.4.1):</strong> links are underlined, and the current page is marked in code, not only by color.</li>
<li><strong>Reflow and resize (1.4.4, 1.4.10):</strong> layouts adapt down to 320 pixels wide and to 200% zoom without horizontal scrolling. Wide tables scroll inside their own labeled region.</li>
</ul>
<h3>Operable</h3>
<ul>
<li><strong>Keyboard access (2.1.1):</strong> all features, including search, theme switching and expandable sections, work with a keyboard alone.</li>
<li><strong>Bypass blocks (2.4.1):</strong> a “Skip to main content” link is the first item on every page.</li>
<li><strong>Visible focus (2.4.7, 2.4.11):</strong> a thick, high-contrast outline shows which element has focus.</li>
<li><strong>Navigation (2.4.5, 2.4.8):</strong> several ways to find a word (search, browse by language, the root index), plus breadcrumbs and an “On this page” menu on longer entries.</li>
<li><strong>Reduced motion (2.3.3):</strong> animations and smooth scrolling are turned off when your system asks for reduced motion.</li>
</ul>
<h3>Understandable</h3>
<ul>
<li><strong>Plain-language summaries:</strong> each etymology begins with a sentence such as “Quenya elen comes from Primitive Elvish elen, from the root EL”, before the detailed tree.</li>
<li><strong>Consistent navigation (3.2.3):</strong> the same menu appears in the same place on every page.</li>
<li><strong>Labels and instructions (3.3.2):</strong> every form field has a visible label, and search explains that accents are optional.</li>
</ul>
<h3>Robust</h3>
<ul>
<li><strong>Semantic HTML (4.1.2):</strong> pages use landmarks (header, navigation, main, footer), a logical heading order, real lists for word trees, and data tables with captions and header cells.</li>
<li><strong>Status messages (4.1.3):</strong> the number of search results is announced to screen readers without moving focus.</li>
<li><strong>Works without JavaScript:</strong> everything except live search is plain HTML. The browse pages give full access when scripts are off.</li>
</ul>
</section>

<section aria-labelledby="testing"><h2 id="testing">How it was tested</h2>
<ul>
<li>Automated checks with the axe-core accessibility engine on a sample of pages, in both themes.</li>
<li>Keyboard-only navigation of every page type.</li>
<li>Layout checks at 320, 375 and 1280 pixels wide.</li>
</ul>
</section>

<section aria-labelledby="limits"><h2 id="limits">Known limitations</h2>
<ul>
<li>Screen readers have no Elvish voices. A language tag tells software the word is not English, but most screen readers will still read it with an English voice, and the private-use tags (like <code>art-x-telerin</code>) are ignored by some tools.</li>
<li>Commentary in the “Notes” sections comes from Eldamo. Elvish words inside it are tagged only when they link to an entry in this lexicon.</li>
<li>Some very large entries (common roots) produce long lists. The “On this page” menu and headings help you move through them.</li>
</ul>
</section>

<section aria-labelledby="feedback"><h2 id="feedback">Feedback</h2>
<p>If you find a barrier on this site, please describe the page and the problem to the site author so it can be fixed.</p>
</section>
"""
    page("accessibility.html", "Accessibility", body, pre, current="accessibility.html")


def build_exports():
    data = OUT / "data"
    data.mkdir(parents=True, exist_ok=True)
    shutil.copy(DB_PATH, data / "lexicon.db")

    # Search index (compact arrays).
    index = [[i, x["form"], x["sort_key"], x["lang_code"], x["gloss"] or "", x["speech"] or "", href(i, "")]
             for i, x in ENTRIES.items()]
    meta = {c: [L["name"], L["bcp47"]] for c, L in LANGS.items()}
    (data / "search-index.json").write_text(
        json.dumps({"langs": meta, "entries": index}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    # CSV.
    with open(data / "entries.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_id", "language", "form", "part_of_speech", "gloss", "category",
                    "derived_from", "elements", "cognates", "eldamo_url"])
        for i, x in ENTRIES.items():
            fmt = lambda ids: "; ".join(f'{ENTRIES[t]["form"]} ({LANGS[ENTRIES[t]["lang_code"]]["name"]})' for t in sort_by_form(ids))
            w.writerow([i, LANGS[x["lang_code"]]["name"], x["form"], POS_LABELS.get(x["speech"], x["speech"]),
                        x["gloss"], CATS[x["cat_id"]]["label"] if x["cat_id"] else "",
                        fmt(OUT_LINKS[i]["derived_from"]), fmt(OUT_LINKS[i]["has_element"]),
                        fmt(OUT_LINKS[i]["cognate"] + IN_LINKS[i]["cognate"]), ELDAMO_WORD.format(i)])

    # JSON-LD dump (relative IRIs resolve against data/lexicon.jsonld -> ../entry/...).
    graph = [entry_jsonld(i, "../") for i in ENTRIES]
    ctx = dict(CONTEXT)
    (data / "lexicon.jsonld").write_text(
        json.dumps({"@context": ctx, "@graph": graph}, ensure_ascii=False), encoding="utf-8")

    # Turtle dump.
    lines = [
        "# Eldarin Etymological Lexicon — data derived from Eldamo (c) Paul Strack, CC BY 4.0",
        "# Relative IRIs resolve against the location of this file.",
        "@prefix ontolex: <http://www.w3.org/ns/lemon/ontolex#> .",
        "@prefix decomp: <http://www.w3.org/ns/lemon/decomp#> .",
        "@prefix lexinfo: <http://www.lexinfo.net/ontology/3.0/lexinfo#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix dct: <http://purl.org/dc/terms/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix eld: <../linked-data.html#> .",
        "",
    ]
    props = {"derived_from": "eld:derivedFrom", "has_element": "decomp:subterm",
             "cognate": "eld:cognateWith", "related": "eld:relatedTo", "see_also": "rdfs:seeAlso"}
    for i, x in ENTRIES.items():
        tag = LANGS[x["lang_code"]]["bcp47"]
        node = iri(i, "../")
        form_iri = node.replace("#entry", "#form") if i in FULL else node + "-form"
        sense_iri = node.replace("#entry", "#sense") if i in FULL else node + "-sense"
        typ = "ontolex:Etymon" if x["speech"] == "root" else "ontolex:LexicalEntry"
        t = [f"<{node}> a {typ}",
             f"    rdfs:label {ttl_literal(x['form'], tag)}",
             f"    ontolex:canonicalForm <{form_iri}>",
             f"    dct:language <{lang_iri(x['lang_code'], '../')}>",
             f"    rdfs:seeAlso <{ELDAMO_WORD.format(i)}>"]
        if x["speech"] in LEXINFO_POS:
            t.append(f"    lexinfo:partOfSpeech lexinfo:{LEXINFO_POS[x['speech']]}")
        if x["gloss"]:
            t.append(f"    ontolex:sense <{sense_iri}>")
        for rel, prop in props.items():
            targets = sort_by_form(OUT_LINKS[i][rel])
            if targets:
                t.append(f"    {prop} " + ", ".join(f"<{iri(k, '../')}>" for k in targets))
        lines.append(" ;\n".join(t) + " .")
        lines.append(f"<{form_iri}> a ontolex:Form ; ontolex:writtenRep {ttl_literal(x['form'], tag)} .")
        if x["gloss"]:
            lines.append(f"<{sense_iri}> a ontolex:LexicalSense ; skos:definition {ttl_literal(x['gloss'], 'en')} .")
        lines.append("")
    (data / "lexicon.ttl").write_text("\n".join(lines), encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(STATIC, OUT / "assets")
    build_static_pages()
    build_lang_pages()
    for eid in FULL:
        build_entry(eid)
    build_exports()
    n = sum(1 for _ in OUT.rglob("*.html"))
    print(f"Wrote {n:,} HTML pages and data exports to {OUT}")


if __name__ == "__main__":
    main()

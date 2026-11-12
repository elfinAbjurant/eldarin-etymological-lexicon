# Eldarin Etymological Lexicon - common tasks. Run `make help`.
PYTHON ?= python3
PORT ?= 8000
ELDAMO_URL = https://raw.githubusercontent.com/pfstrack/eldamo/master/src/data/eldamo-data.xml

.PHONY: help all db site site-all check serve stats update clean

help:
	@echo "make all       build the database, then the site"
	@echo "make db        data/eldamo-data.xml -> data/lexicon.db"
	@echo "make site      data/lexicon.db -> site/ (hybrid layout, under 5,000 files)"
	@echo "make site-all  one page per entry (about 8,000 files)"
	@echo "make check     verify links, search URLs and RDF exports"
	@echo "make serve     preview at http://localhost:$(PORT)"
	@echo "make stats     database statistics"
	@echo "make update    download the latest Eldamo data"
	@echo "make clean     remove site/"

all: db site

db:
	$(PYTHON) lexicon/build_db.py

site:
	$(PYTHON) lexicon/build_site.py

site-all:
	$(PYTHON) lexicon/build_site.py --all-pages

check:
	$(PYTHON) tools/check_site.py

serve:
	$(PYTHON) -m http.server --directory site $(PORT)

stats:
	$(PYTHON) lexicon/explore.py --stats

update:
	curl -L -o data/eldamo-data.xml $(ELDAMO_URL)

clean:
	rm -rf site

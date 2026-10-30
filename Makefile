TAG ?= $(shell git describe --tags --abbrev=0)
DEST ?= ../pdffiller-knowledge/plugins/turnstile

.PHONY: test vendor
test:
	python3 -m unittest discover -s tests

vendor:
	sh scripts/vendor.sh $(TAG) $(DEST)

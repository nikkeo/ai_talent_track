PYTHON := .venv/bin/python

.PHONY: install demo test eval

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

demo:
	PYTHONPATH=src $(PYTHON) -m support_ai.cli --demo

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

eval:
	PYTHONPATH=src $(PYTHON) -m support_ai.evaluate

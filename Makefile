PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_PIP := $(VENV_PYTHON) -m pip
LOCAL_DEPS_DIR := .local_deps
XCB_WORK_DIR := $(LOCAL_DEPS_DIR)/xcb_cursor
XCB_LIB_DIR := $(XCB_WORK_DIR)/lib
XCB_DEB := $(XCB_WORK_DIR)/libxcb-cursor0.deb
GUI_LD_LIBRARY_PATH := $(XCB_LIB_DIR):$$LD_LIBRARY_PATH

.PHONY: install install-system-libs run debug clean lint lint-strict

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV_DIR)

install-system-libs:
	mkdir -p "$(XCB_WORK_DIR)" "$(XCB_LIB_DIR)"
	if ! command -v apt-get >/dev/null 2>&1; then \
		echo "apt-get not found; skipping Ubuntu xcb fallback install."; \
	else \
		rm -f "$(XCB_DEB)"; \
		( cd "$(XCB_WORK_DIR)" && apt-get download libxcb-cursor0 ); \
		deb="$(XCB_WORK_DIR)"/libxcb-cursor0_*.deb; \
		if [ ! -e "$$deb" ]; then \
			echo "Download failed for libxcb-cursor0."; \
			exit 1; \
		fi; \
		rm -rf "$(XCB_LIB_DIR)"; \
		mkdir -p "$(XCB_LIB_DIR)"; \
		tmp="$$(mktemp -d)"; \
		cp "$$deb" "$$tmp/pkg.deb"; \
		( \
			cd "$$tmp" && \
			ar x pkg.deb && \
			for archive in data.tar.xz data.tar.zst data.tar.gz data.tar.bz2; do \
				if [ -f "$$archive" ]; then \
					tar -xf "$$archive"; \
				fi; \
			done \
		); \
		cp -a "$$tmp"/usr/lib/*-linux-gnu/libxcb-cursor.so* "$(XCB_LIB_DIR)"/; \
		rm -rf "$$tmp"; \
	fi

install: $(VENV_PYTHON) install-system-libs
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt

run: install
	LD_LIBRARY_PATH="$(GUI_LD_LIBRARY_PATH)" $(VENV_PYTHON) -m flyin_viewer --gui --maps-root maps

debug: install
	$(VENV_PYTHON) -m pdb -m flyin_viewer maps/easy/01_linear_path.txt

clean:
	rm -rf __pycache__ .mypy_cache .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +

lint:
	$(VENV_DIR)/bin/flake8 . --exclude .venv
	$(VENV_DIR)/bin/mypy . --exclude '(^|/)\.venv/' --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	$(VENV_DIR)/bin/flake8 . --exclude .venv
	$(VENV_DIR)/bin/mypy . --exclude '(^|/)\.venv/' --strict

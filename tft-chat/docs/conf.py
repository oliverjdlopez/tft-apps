"""Sphinx configuration for the ChatTFT docs site."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches [tool.pytest.ini_options] pythonpath in pyproject.toml, so autodoc
# can import the same top-level packages (api, core, db, domain, ...).
sys.path.insert(0, str(REPO_ROOT / "app" / "backend"))
sys.path.insert(0, str(REPO_ROOT / "app" / "backend" / "src"))

project = "ChatTFT"
copyright = "ChatTFT contributors"
author = "ChatTFT contributors"
html_title = "ChatTFT · TFT analysis platform"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# docs/README.md is the GitHub-facing landing page for the docs/ folder;
# index.md is the Sphinx root doc and covers the same nav via toctrees.
exclude_patterns = ["README.md", "_build", "Thumbs.db", ".DS_Store"]

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_show_sphinx = False
html_theme_options = {
    "navigation_with_keys": True,
    "light_css_variables": {
        "color-brand-primary": "#7158e8",
        "color-brand-content": "#5f46d6",
        "color-link": "#5f46d6",
        "color-link--hover": "#422da8",
        "color-admonition-background": "#f8f7ff",
    },
    "dark_css_variables": {
        "color-brand-primary": "#c9bcff",
        "color-brand-content": "#b7a6ff",
        "color-link": "#c9bcff",
        "color-link--hover": "#f0ebff",
        "color-admonition-background": "#19182a",
    },
}

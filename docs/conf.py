"""Sphinx configuration for the project documentation."""

from __future__ import annotations

import doctest
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from docutils import nodes
from sphinx import addnodes
from sphinx_iconify.roles import iconify_icon


if TYPE_CHECKING:
    from typing import NoReturn

    from sphinx.application import Sphinx
    from sphinx.util.docutils import SphinxTranslator


_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(_ROOT))

_project_metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

project = str(_project_metadata["name"])
author = "Demin Vadim"
copyright = author  # noqa: A001
version = str(_project_metadata["version"])
release = version

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx_contributors",
    "sphinx_tabs.tabs",
    "sphinx_iconify",
    "sphinxcontrib.mermaid",
    "sphinx_llm_friendly",
]

exclude_patterns = ["_build"]
nitpicky = True
# No external Sphinx inventory is configured for these dependency and Python types.
nitpick_ignore = [
    # pycent publishes a GitHub API reference without a Sphinx inventory; see usage.rst.
    ("py:class", "cent._client.Client"),
    ("py:class", "cent._client.AsyncClient"),
    ("py:class", "cent._api.PublishResult"),
    ("py:exc", "cent.CentError"),
    ("py:data", "typing.NotRequired"),
    ("py:data", "typing.Unpack"),
    ("py:data", "typing.Any"),
    ("py:data", "typing.Optional"),
    ("py:data", "typing_extensions.TypeForm"),
    ("py:data", "typing.Literal"),
    ("py:data", "typing.ClassVar"),
    ("py:data", "Ellipsis"),
    ("py:class", "collections.abc.Callable"),
    ("py:class", "collections.abc.Collection"),
    ("py:class", "collections.abc.Coroutine"),
    ("py:class", "collections.abc.Mapping"),
    ("py:class", "collections.abc.Sequence"),
    ("py:class", "inspect.Signature"),
    ("py:class", "django.http.request.HttpRequest"),
    ("py:class", "django.http.response.HttpResponse"),
    ("py:class", "django.http.response.JsonResponse"),
    ("py:class", "django.http.response.HttpResponseBase"),
    ("py:meth", "django.views.generic.base.View.as_view"),
    ("py:exc", "django.core.exceptions.ImproperlyConfigured"),
    ("py:exc", "django.core.exceptions.PermissionDenied"),
    ("py:class", "grpc.aio._base_server.Server"),
]

autodoc_typehints = "description"
always_document_param_types = True

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_param = True
napoleon_use_rtype = True

doctest_default_flags = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE

html_theme = "shibuya"
html_theme_options = {"accent_color": "blue"}
html_static_path = ["_static"]
html_css_files = ["custom.css"]


def _skip_iconify(_translator: SphinxTranslator, _node: nodes.Node) -> NoReturn:
    """Omit decorative icons from the generated Markdown pages."""
    raise nodes.SkipNode


def setup(app: Sphinx) -> dict[str, bool]:
    """Register Markdown support for third-party documentation nodes."""
    app.add_node(iconify_icon, override=True, llm_markdown=(_skip_iconify, None))
    app.add_node(addnodes.desc_type_parameter_list, override=True, llm_markdown=(_skip_iconify, None))
    return {"parallel_read_safe": True, "parallel_write_safe": True}

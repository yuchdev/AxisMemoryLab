"""Self-contained HTML: escaped text only, no scripts, no external resources."""

from __future__ import annotations

import html
from typing import Any

from axis_memlab.reporting.markdown import render_markdown

_CSP = "default-src 'none'; style-src 'unsafe-inline'"


def render_html(doc: dict[str, Any]) -> str:
    """Wrap the Markdown rendering verbatim in an escaped preformatted block."""
    body = html.escape(render_markdown(doc))
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
        "<title>Memory evidence report</title>"
        "<style>body{font-family:sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap}</style></head><body>"
        f"<pre>{body}</pre></body></html>\n"
    )

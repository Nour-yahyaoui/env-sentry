"""
Generate an SVG score badge for your README.

No network calls, no shields.io dependency — just a small, deterministic SVG
you can commit next to your README and update in CI.
"""

from __future__ import annotations

from typing import Optional
from xml.sax.saxutils import escape

FONT = "Verdana,Geneva,DejaVu Sans,sans-serif"


def colour_for(score: int) -> str:
    if score >= 90:
        return "#4c1"
    if score >= 80:
        return "#97ca00"
    if score >= 70:
        return "#dfb317"
    if score >= 60:
        return "#fe7d37"
    return "#e05d44"


def _text_width(text: str) -> int:
    # Roughly Verdana 11px advance width; good enough for badge sizing.
    return int(len(text) * 6.6) + 10


def render(
    score: int,
    label: str = "env-sentry",
    message: Optional[str] = None,
    style: str = "flat",
) -> str:
    """Return an SVG badge string for ``score`` (0-100)."""
    score = max(0, min(100, int(score)))
    message = message if message is not None else f"{score}/100"
    colour = colour_for(score)
    label_width = _text_width(label)
    message_width = _text_width(message)
    total_width = label_width + message_width
    radius = 3 if style != "flat-square" else 0
    gradient = (
        '<linearGradient id="s" x2="0" y2="100%">'
        '<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        '<stop offset="1" stop-opacity=".1"/></linearGradient>'
        if style != "flat-square" else ""
    )
    title = escape(f"{label}: {message}")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{title}">
  <title>{title}</title>
  {gradient}
  <g shape-rendering="crispEdges">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{message_width}" height="20" fill="{colour}"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="{FONT}" font-size="11">
    <text x="{label_width / 2:.0f}" y="14">{escape(label)}</text>
    <text x="{label_width + message_width / 2:.0f}" y="14">{escape(message)}</text>
  </g>
  <rect width="{total_width}" height="20" rx="{radius}" fill="url(#s)"/>
</svg>
"""


def write(path, score: int, label: str = "env-sentry", style: str = "flat") -> str:
    """Write the badge to ``path`` and return the SVG."""
    svg = render(score, label=label, style=style)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    return svg


def markdown(path: str = ".env-sentry-badge.svg", alt: str = "env-sentry health") -> str:
    return f"![{alt}]({path})"

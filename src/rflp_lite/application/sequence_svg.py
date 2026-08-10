"""Business-free SVG primitives used by the sequence renderer."""

from __future__ import annotations

from html import escape


def number(value: float) -> str:
    return f"{float(value):.2f}"


def svg_text(
    x: float,
    y: float,
    value: object,
    *,
    fill: str = "#263238",
    size: int = 13,
    weight: str | None = None,
    anchor: str = "start",
    class_name: str | None = None,
) -> str:
    attrs = [
        f'x="{number(x)}"',
        f'y="{number(y)}"',
        f'fill="{escape(fill, quote=True)}"',
        f'font-size="{int(size)}"',
        f'text-anchor="{escape(anchor, quote=True)}"',
    ]
    if weight:
        attrs.append(f'font-weight="{escape(weight, quote=True)}"')
    if class_name:
        attrs.append(f'class="{escape(class_name, quote=True)}"')
    text = escape(str(value), quote=False)
    return f"<text {' '.join(attrs)}>{text}</text>"


def svg_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    style: str = "solid",
    arrow: str | None = None,
    stroke: str = "#263238",
    width: float = 1.8,
    class_name: str | None = None,
) -> str:
    attrs = [
        f'x1="{number(x1)}"',
        f'y1="{number(y1)}"',
        f'x2="{number(x2)}"',
        f'y2="{number(y2)}"',
        f'stroke="{escape(stroke, quote=True)}"',
        f'stroke-width="{number(width)}"',
    ]
    if style == "dashed":
        attrs.append('stroke-dasharray="8 5"')
    elif style == "lifeline":
        attrs.append('stroke-dasharray="6 5"')
    if arrow:
        attrs.append(f'marker-end="url(#{escape(arrow, quote=True)})"')
    if class_name:
        attrs.append(f'class="{escape(class_name, quote=True)}"')
    return f"<line {' '.join(attrs)}/>"


def svg_rect(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str = "none",
    stroke: str = "#263238",
    stroke_width: float = 1.0,
    radius: float = 0.0,
    class_name: str | None = None,
) -> str:
    attrs = [
        f'x="{number(x)}"',
        f'y="{number(y)}"',
        f'width="{number(width)}"',
        f'height="{number(height)}"',
        f'fill="{escape(fill, quote=True)}"',
        f'stroke="{escape(stroke, quote=True)}"',
        f'stroke-width="{number(stroke_width)}"',
    ]
    if radius:
        attrs.append(f'rx="{number(radius)}"')
    if class_name:
        attrs.append(f'class="{escape(class_name, quote=True)}"')
    return f"<rect {' '.join(attrs)}/>"


def svg_path(
    path: str,
    *,
    fill: str = "none",
    stroke: str = "#263238",
    stroke_width: float = 1.8,
    style: str = "solid",
    arrow: str | None = None,
    class_name: str | None = None,
) -> str:
    attrs = [
        f'd="{escape(path, quote=True)}"',
        f'fill="{escape(fill, quote=True)}"',
        f'stroke="{escape(stroke, quote=True)}"',
        f'stroke-width="{number(stroke_width)}"',
    ]
    if style == "dashed":
        attrs.append('stroke-dasharray="8 5"')
    elif style == "lifeline":
        attrs.append('stroke-dasharray="6 5"')
    if arrow:
        attrs.append(f'marker-end="url(#{escape(arrow, quote=True)})"')
    if class_name:
        attrs.append(f'class="{escape(class_name, quote=True)}"')
    return f"<path {' '.join(attrs)}/>"

"""Small deterministic HTML helpers shared by report sections."""

import html
import re
from typing import Any


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def short(value: str) -> str:
    return value if len(value) <= 14 else f"{value[:8]}…{value[-4:]}"


def fmt_eth(value: float | int | None) -> str:
    return "—" if value is None else f"{float(value):,.6f}"


def fmt_num(value: float | int | None, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):,.{digits}f}"


def fmt_price(value: float | None) -> str:
    return "—" if value is None else f"{value:.4e}"


def badge(ok: bool | None, label: str) -> str:
    if ok is None:
        return f'<span class="badge muted">{esc(label)}: n/a</span>'
    css = "ok" if ok else "bad"
    return f'<span class="badge {css}">{esc(label)}: {"yes" if ok else "no"}</span>'


def slug(text: str, seen: dict[str, int]) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", "", text)).strip().lower()
    base = re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "section"
    count = seen.get(base, 0) + 1
    seen[base] = count
    return base if count == 1 else f"{base}-{count}"


def decorate_sections(document: str) -> str:
    """Add stable section anchors and a sticky table of contents."""
    pattern = re.compile(r"<section>\s*<h2>(.*?)</h2>", re.S)
    matches = list(pattern.finditer(document))
    seen: dict[str, int] = {}
    replacements = []
    toc_items = []
    for match in matches:
        title_html = match.group(1)
        title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        anchor = slug(title, seen)
        toc_items.append(f'<a href="#{anchor}">{html.escape(title)}</a>')
        replacements.append(
            (
                match.start(),
                match.end(),
                f'<section id="{anchor}">\n  <h2>{title_html}</h2>',
            )
        )
    for start, end, replacement in reversed(replacements):
        document = document[:start] + replacement + document[end:]
    if matches:
        document = document.replace(
            "</section>",
            '<a class="back" href="#top">Back to top</a></section>',
        )
    if toc_items:
        toc = (
            '<nav class="toc" aria-label="Report sections">'
            '<a href="#top">Top</a>' + "".join(toc_items) + "</nav>"
        )
        document = document.replace("<!--TOC-->", toc)
    return document


def table(
    headers: list[str],
    rows: list[list[Any]],
    *,
    numeric_from: int = 1,
    css_class: str = "",
) -> str:
    head = "".join(
        f'<th class="{"num" if index >= numeric_from else ""}">{esc(header)}</th>'
        for index, header in enumerate(headers)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="{"num" if index >= numeric_from else ""}">{esc(value)}</td>'
            for index, value in enumerate(row)
        )
        body.append(f"<tr>{cells}</tr>")
    class_attr = f' class="{css_class}"' if css_class else ""
    return (
        f'<div class="table-wrap"><table{class_attr}><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )

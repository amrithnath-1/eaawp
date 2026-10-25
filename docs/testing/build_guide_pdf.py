"""
Build EAAWP_GEC_DMM_Complete_Testing_Guide.pdf from the Markdown source in this folder.

    pip install markdown==3.7 playwright==1.48.0 pypdf
    python docs/testing/build_guide_pdf.py [--chromium PATH]

Renders the Markdown to HTML, prints it with Chromium (A4, page numbers in the footer) and fills the table of
contents with real page numbers by rendering twice. Not part of the application.
"""
from __future__ import annotations

import argparse
import html
import io
import re
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
SRC = HERE / "EAAWP_GEC_DMM_Complete_Testing_Guide.md"
OUT = HERE / "EAAWP_GEC_DMM_Complete_Testing_Guide.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "DejaVu Sans", "Segoe UI", Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 17pt; margin: 0 0 8pt; padding-bottom: 4pt; border-bottom: 1.5pt solid #1a1a1a; page-break-before: always; }
h2 { font-size: 12.5pt; margin: 14pt 0 5pt; }
p, li { margin: 4pt 0; }
ul, ol { padding-left: 18pt; }
code { font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 8.6pt; background: #f1f1f1; padding: 0 2pt; }
pre { background: #f4f4f4; border: 0.6pt solid #cfcfcf; padding: 6pt; white-space: pre-wrap; word-break: break-all; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 0.6pt solid #9a9a9a; padding: 3pt 4pt; vertical-align: top; text-align: left; }
th { background: #ececec; }
a { color: #1a1a1a; }
.cover { height: 240mm; display: flex; flex-direction: column; justify-content: center; }
.cover .kicker { font-size: 10pt; letter-spacing: 3pt; color: #555; }
.cover h1.title { page-break-before: avoid; border: none; font-size: 26pt; margin: 6pt 0; }
.cover .subtitle { font-size: 13pt; color: #333; }
.cover .version { margin-top: 28pt; font-size: 9pt; color: #555; }
.cover .warn { margin-top: 18pt; padding: 8pt; border: 1pt solid #1a1a1a; font-size: 9pt; }
.toc { page-break-before: always; }
.toc h2 { font-size: 17pt; border-bottom: 1.5pt solid #1a1a1a; padding-bottom: 4pt; }
.toc ol { list-style: none; padding: 0; }
.toc li { display: flex; gap: 6pt; margin: 2.5pt 0; }
.toc li .dots { flex: 1; border-bottom: 0.8pt dotted #888; margin-bottom: 3pt; }
.toc li .num { min-width: 18pt; text-align: right; }
"""

FOOTER = ('<div style="font-size:8px;width:100%;padding:0 16mm;color:#555;display:flex;justify-content:space-between;">'
          '<span>EAAWP — Complete Testing Guide (GEC Services / Digital Marketing Manager)</span>'
          '<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')


def front_matter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    if text.startswith("---"):
        head, body = text[3:].split("\n---", 1)
        for line in head.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
        return meta, body
    return meta, text


def build_html(meta: dict, body_md: str, pages: dict[str, int]) -> tuple[str, list[str]]:
    body = markdown.markdown(body_md, extensions=["tables", "fenced_code", "sane_lists", "toc"])
    headings = [html.unescape(re.sub(r"<[^>]+>", "", h)) for h in re.findall(r"<h1[^>]*>(.*?)</h1>", body)]
    ids = re.findall(r'<h1 id="([^"]+)"', body)
    toc = "".join(
        f'<li><a href="#{i}">{html.escape(h)}</a><span class="dots"></span><span class="num">{pages.get(h, "")}</span></li>'
        for h, i in zip(headings, ids)
    )
    cover = (
        '<section class="cover"><div class="kicker">EAAWP · ENTERPRISE AGENTIC AI WORKFORCE PLATFORM</div>'
        f'<h1 class="title">{html.escape(meta.get("title", "Testing Guide"))}</h1>'
        f'<div class="subtitle">{html.escape(meta.get("subtitle", ""))}</div>'
        f'<div class="version">{html.escape(meta.get("version", ""))}</div>'
        '<div class="warn">Contains no passwords, keys or tokens. Never write credentials into this document, the AI '
        'chat or screenshots. Features marked NOT AVAILABLE or LIMITED are known gaps of this version.</div></section>'
    )
    doc = (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{cover}"
           f'<section class="toc"><h2>Contents</h2><ol>{toc}</ol></section>{body}</body></html>')
    return doc, headings


def render(doc: str, chromium: str | None) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"executable_path": chromium} if chromium else {}))
        page = browser.new_page()
        page.set_content(doc, wait_until="load")
        pdf = page.pdf(format="A4", print_background=True, display_header_footer=True,
                       header_template="<div></div>", footer_template=FOOTER,
                       margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"})
        browser.close()
        return pdf


def heading_pages(pdf: bytes, headings: list[str], skip_pages: int) -> dict[str, int]:
    reader = PdfReader(io.BytesIO(pdf))
    texts = [(" ".join((pg.extract_text() or "").split())) for pg in reader.pages]
    found: dict[str, int] = {}
    start = skip_pages
    for h in headings:
        key = " ".join(h.split())
        for n in range(start, len(texts)):
            if texts[n].startswith(key) or f" {key} " in f" {texts[n][:len(key) + 40]} ":
                found[h] = n + 1
                start = n
                break
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", default=None, help="path to a Chromium/headless_shell binary (optional)")
    args = ap.parse_args()
    meta, body_md = front_matter(SRC.read_text(encoding="utf-8"))
    doc, headings = build_html(meta, body_md, {})
    first = render(doc, args.chromium)
    toc_pages = 1 + max(1, (len(headings) + 39) // 40)       # cover + contents
    pages = heading_pages(first, headings, toc_pages)
    doc, _ = build_html(meta, body_md, pages)
    final = render(doc, args.chromium)
    OUT.write_bytes(final)
    missing = [h for h in headings if h not in pages]
    print(f"wrote {OUT} ({len(PdfReader(io.BytesIO(final)).pages)} pages, {len(headings)} sections"
          + (f"; page not found for: {missing}" if missing else "") + ")")


if __name__ == "__main__":
    main()

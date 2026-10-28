#!/usr/bin/env python3
"""Crop every question out of the GATE EC papers as an image.

For each paper we find "anchors" on the pages: the start of each question, the start of a
common-data / linked-answer statement (prepended to every question it covers), and "stop"
lines (section headers, END OF PAPER). A question's crop runs from its anchor to the next
anchor, continuing across page breaks. Text PDFs are read with PyMuPDF; scanned pages are
OCR'd with RapidOCR.

Usage: python3 scripts/crop_questions.py OUT_DIR [paper ...]
Writes OUT_DIR/<paper>/<q>.webp
"""
import io
import os
import re
import sys

import pymupdf
from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DPI = 150
pymupdf.TOOLS.mupdf_display_errors(False)

# paper: (pdf, [(first_page, last_page, prefix)], mode)  pages 1-based inclusive
# prefix "GA" means questions on those pages are numbered GA1.. in our dataset.
PAPERS = {
    "2007": ("EC2007.pdf", [(2, 22, "")], "ocr"),
    "2008": ("EC2008.pdf", [(2, 24, "")], "ocr"),
    "2009": ("EC2009.pdf", [(2, 16, "")], "ocr"),
    "2010": ("EC2010.pdf", [(2, 16, "")], "ocr"),
    "2011": ("EC2011.pdf", [(2, 17, "")], "ocr"),
    "2012": ("EC2012.pdf", [(2, 14, "")], "text"),
    "2013": ("EC2013.pdf", [(3, 19, "")], "text"),
    "2014-1": ("EC2014.pdf", [(6, 7, "GA"), (8, 18, "")], "text"),
    "2014-2": ("EC2014.pdf", [(25, 26, "GA"), (27, 38, "")], "text"),
    "2014-3": ("EC2014.pdf", [(45, 46, "GA", "ocr"), (47, 61, "", "ocr")], "text"),
    "2014-4": ("EC2014.pdf", [(68, 69, "GA"), (70, 82, "")], "text"),
    "2015-1": ("EC2015.pdf", [(2, 25, "")], "ocr"),
    "2015-2": ("EC2015.pdf", [(27, 52, "")], "ocr"),
    "2015-3": ("EC2015.pdf", [(54, 77, "")], "ocr"),
    "2016-1": ("EC2016.pdf", [(1, 2, "GA"), (3, 19, "")], "text"),
    "2016-2": ("EC2016.pdf", [(22, 24, "GA", "ocr"), (25, 38, "")], "text"),
    "2016-3": ("EC2016.pdf", [(41, 43, "GA"), (44, 62, "")], "text"),
    "2017-1": ("EC1-2017-repaired.pdf", [(1, 22, "")], "ocr"),
    "2017-2": ("EC2-2017.pdf", [(2, 30, "")], "ocr"),
    "2018": ("EC2018.pdf", [(1, 3, "GA"), (4, 20, "")], "text"),
    "2019": ("EC2019.pdf", [(1, 28, "")], "ocr"),
    "2020": ("EC2020.pdf", [(1, 18, "")], "qno"),
    "2021": ("EC2021.pdf", [(1, 39, "")], "ocr"),
    "2022": ("EC2022.pdf", [(1, 52, "")], "text"),
    "2023": ("EC2023.pdf", [(1, 44, "")], "text"),
    "2024": ("EC2024.pdf", [(1, 46, "")], "text"),
    "2025": ("EC2025.pdf", [(1, 52, "")], "text"),
    "2026": ("EC.pdf", [(1, 58, "")], "text"),
}

# Anchors OCR misses: paper -> [(page 1-based, y in pixels at DPI, question number)]
MANUAL = {
    "2019": [(14, 316, "19")],
}

Q_RE = re.compile(r"^\s*Q\s*[\.,]?\s*(?:No\.?\s*)?(\d{1,2})(?!\d)(?!\s*(?:[–\-]|to\b))")
PRE_RE = re.compile(r"(Common Data|Statement for Linked|Linked Answer Questions?:? ?Q)", re.I)
STOP_RE = re.compile(r"(carry (one|two|ONE|TWO) marks?|END OF THE QUESTION|General Aptitude \(GA\) Questions"
                     r"|^Common Data Questions$|^Linked Answer Questions$|Space for Rough Work)", re.I)


_ocr = None


def ocr_lines(pix_png):
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    res, _ = _ocr(pix_png)
    out = []
    for box, text, score in res or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append((min(xs), min(ys), max(xs), max(ys), text))
    return out


def page_lines(doc, pno, mode):
    """Return (lines, page_w, page_h, scale) with line boxes in pixel coords at DPI."""
    page = doc[pno]
    scale = DPI / 72.0
    w, h = page.rect.width * scale, page.rect.height * scale
    if mode == "ocr":
        png = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY).tobytes("png")
        return ocr_lines(png), w, h
    lines = []
    raw = page.get_text("rawdict") if mode == "qnum17" else page.get_text("dict")
    for b in raw["blocks"]:
        if b.get("type") == 1:   # image block: only matters for header/footer detection
            x0, y0, x1, y1 = b["bbox"]
            if (y1 - y0) < 0.15 * page.rect.height:
                lines.append((x0 * scale, y0 * scale, x1 * scale, y1 * scale, ""))
            continue
        for l in b.get("lines", []):
            if mode == "qnum17":
                t = "".join(chr(ord(c["c"]) + 29) for s in l["spans"] for c in s["chars"]
                            if ord(c["c"]) != 0)
                t = "".join(ch for ch in t if 31 < ord(ch) < 127)
            else:
                t = "".join(s["text"] for s in l["spans"])
            x0, y0, x1, y1 = l["bbox"]
            lines.append((x0 * scale, y0 * scale, x1 * scale, y1 * scale, t))
    return lines, w, h


def find_anchors(lines, w, h, mode):
    """Return list of (y, kind, value): kind in q / pre / stop."""
    anchors = []
    lines = sorted(lines, key=lambda l: (round(l[1] / 6), l[0]))
    for x0, y0, x1, y1, t in lines:
        t = t.strip()
        if not t:
            continue
        m = re.match(r"Question\s*Number\s*[:;]?\s*(\d+)", t.replace(" ", ""))
        if m:
            anchors.append((y0, "q", m.group(1)))
            continue
        if mode in ("qnum", "qnum17"):
            continue
        if x0 > 0.30 * w:
            continue
        if PRE_RE.search(t):
            nums = re.findall(r"\d+", t)
            anchors.append((y0, "pre", [n for n in nums if 1 <= int(n) <= 85]))
            continue
        if STOP_RE.search(t):
            anchors.append((y0, "stop", None))
            continue
        m = Q_RE.match(t)
        if m and x0 < 0.18 * w:
            anchors.append((y0, "q", m.group(1)))
    return anchors


def content_band(lines, w, h, first_anchor=None, headers=True):
    """Exclude running header/footer: lines in the top/bottom 10% bands.

    The footer starts at the first bottom-band line that is set apart from the line above
    it by a gap, so options running into the bottom band are kept.
    """
    top, bot = 0.035 * h, 0.965 * h
    for x0, y0, x1, y1, t in lines:
        ts = t.strip()
        if ts and (Q_RE.match(ts) or ts.startswith("Question Number") or PRE_RE.search(ts)):
            continue
        if first_anchor is not None and y1 > first_anchor - 4:
            pass
        elif headers and y1 < 0.10 * h:
            top = max(top, y1 + 3)
    if headers:   # 2020 (qno) has no footer and sets options near the foot
        prev_bottom = 0
        for x0, y0, x1, y1, t in sorted(lines, key=lambda l: l[1]):
            if y0 > 0.90 * h and y0 - prev_bottom >= 12:
                bot = min(bot, y0 - 3)
                break
            prev_bottom = max(prev_bottom, y1)
    return top, bot


def trim(img):
    g = ImageOps.invert(img.convert("L"))
    g = g.point(lambda v: 255 if v > 40 else 0)
    box = g.getbbox()
    if not box:
        return None
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - 10), max(0, y0 - 8), min(img.width, x1 + 10), min(img.height, y1 + 8)))


def vstack(parts):
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    wmax = max(p.width for p in parts)
    hsum = sum(p.height for p in parts) + 12 * (len(parts) - 1)
    out = Image.new("L", (wmax, hsum), 255)
    y = 0
    for p in parts:
        out.paste(p, (0, y))
        y += p.height + 12
    return out


def crop_paper(paper, out_dir):
    pdf, ranges, mode = PAPERS[paper]
    doc = pymupdf.open(os.path.join(ROOT, pdf))
    events = []   # (page_idx, y, kind, value, prefix)
    pages = {}
    for rng in ranges:
        first, last, prefix = rng[:3]
        rmode = rng[3] if len(rng) > 3 else mode
        for p in range(first - 1, last):
            lines, w, h = page_lines(doc, p, rmode)
            img = Image.open(io.BytesIO(doc[p].get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY).tobytes("png")))
            anchors = find_anchors(lines, w, h, rmode)
            first = min((a[0] for a in anchors if a[1] != "stop"), default=None)
            top, bot = content_band(lines, w, h, first, headers=(rmode != "qno"))
            pages[p] = (img, top, bot)
            for y, kind, val in anchors:
                if top - 20 <= y <= bot:
                    events.append((p, y, kind, val, prefix))
    for page, y, val in MANUAL.get(paper, []):
        events.append((page - 1, y, "q", val, ""))
    events.sort(key=lambda e: (e[0], e[1]))
    if paper in ("2019", "2020", "2021"):   # GA Q1-10 come first, then EC restarts at Q1
        prev = 0
        for i, e in enumerate(events):
            if e[2] != "q":
                continue
            n = int(e[3])
            if n < prev:
                break
            prev = n
            events[i] = (e[0], e[1], e[2], e[3], "GA")
    order = [p for r in ranges for p in range(r[0] - 1, r[1])]
    pos = {p: i for i, p in enumerate(order)}

    def region(start, end):
        """Crop from (page, y) to (page, y), spanning pages."""
        (p0, y0), (p1, y1) = start, end
        parts = []
        i = pos[p0]
        while True:
            p = order[i]
            img, top, bot = pages[p]
            ya = max(y0 - 18, 0) if p == p0 else top
            yb = min(y1 - 18, bot) if p == p1 else bot
            if yb > ya + 4:
                parts.append(trim(img.crop((0, int(ya), img.width, int(yb)))))
            if p == p1 or i + 1 >= len(order):
                break
            i += 1
        return vstack(parts)

    os.makedirs(os.path.join(out_dir, paper), exist_ok=True)
    seen, pre_imgs, written = set(), {}, []
    last_page = order[-1]
    end_of_doc = (last_page, pages[last_page][2])
    for k, (p, y, kind, val, prefix) in enumerate(events):
        nxt = next(((e[0], e[1]) for e in events[k + 1:]), end_of_doc)
        if kind == "pre":
            img = region((p, y), nxt)
            for n in val:
                pre_imgs[prefix + n] = img
        elif kind == "q":
            q = prefix + val
            if q in seen:
                continue
            seen.add(q)
            img = region((p, y), nxt)
            if q in pre_imgs:
                img = vstack([pre_imgs[q], img])
            if img is None:
                continue
            img.save(os.path.join(out_dir, paper, q + ".webp"), "WEBP", quality=72, method=6)
            written.append(q)
    return written


def main():
    out_dir = sys.argv[1]
    papers = sys.argv[2:] or list(PAPERS)
    for paper in papers:
        qs = crop_paper(paper, out_dir)
        print(paper, len(qs), " ".join(qs))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the GATE EC web book.

Usage: python3 scripts/build_book.py CROPS_DIR

Reads
  data/questions.json            classification (from scripts/build.py)
  data/solutions/<paper>.md      worked solutions, one "@@ Q<n>" block per question
  data/book/*.md                 analysis, predictions and question bank pages
  CROPS_DIR/<paper>/<q>.webp     question images (from scripts/crop_questions.py)
  syllabus/ec_2027_taxonomy.json
Writes
  book/index.html                the app (copied from book/src/index.html)
  book/data/book.json            metadata, solutions, pages, stats
  book/data/img-<paper>.json     {q_no: data-URI} per paper, loaded on demand
"""
import base64
import io
import json
import os
import re
import shutil
import sys
from collections import OrderedDict, defaultdict

import markdown
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from build import PAPERS  # noqa: E402

MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
MATH_RE = re.compile(r"(\$\$.+?\$\$|\$[^$\n]+?\$)", re.S)


def md_to_html(text):
    """Render markdown but leave $...$ / $$...$$ untouched for MathJax."""
    stash = []

    def keep(m):
        stash.append(m.group(0))
        return f"\x00M{len(stash) - 1}\x00"

    protected = MATH_RE.sub(keep, text)
    MD.reset()
    html = MD.convert(protected)
    html = re.sub(r"\x00M(\d+)\x00", lambda m: stash[int(m.group(1))]
                  .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), html)
    return html


def parse_blocks(path):
    """Parse '@@ <key>' blocks: header 'field: value' lines, '@@' line, markdown body."""
    if not os.path.exists(path):
        return OrderedDict()
    text = open(path, encoding="utf-8").read()
    blocks = OrderedDict()
    for chunk in re.split(r"^@@ ", text, flags=re.M)[1:]:
        key, rest = chunk.split("\n", 1)
        head, _, body = rest.partition("\n@@\n")
        fields = {}
        for line in head.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip()
        body = body.strip()
        if "\n%%\n" in body:   # question part, then solution part (predictions / bank)
            qpart, _, body = body.partition("\n%%\n")
            fields["question_html"] = md_to_html(qpart.strip())
        fields["html"] = md_to_html(body.strip())
        for k in ("ans", "concept"):
            if k in fields:
                fields[k + "_html"] = md_to_html(fields[k]).removeprefix("<p>").removesuffix("</p>")
        blocks[key.strip()] = fields
    return blocks


def tidy_image(path):
    """Collapse long blank bands, keep it grayscale, return a webp data URI."""
    im = Image.open(path).convert("L")
    if im.width > 960:
        im = im.resize((960, round(im.height * 960 / im.width)), Image.LANCZOS)
    a = np.array(im)
    blank = (a < 150).sum(1) <= 6
    keep, run = [], 0
    for i, b in enumerate(blank):
        run = run + 1 if b else 0
        if run <= 18:
            keep.append(i)
    im = Image.fromarray(a[keep])
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=68, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def check_answer(ans, key):
    """Compare our answer text with an official key. True/False, or None when not comparable."""
    if not key:
        return None
    if key in ("MTA", "Marks to All"):
        return True
    plain = re.sub(r"<[^>]+>|\$", " ", ans).replace("−", "-")
    m = re.match(r"\s*(-?[\d.]+)\s+to\s+(-?[\d.]+)", key)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", plain.replace(",", ""))[:3]]
        if not nums:
            return None
        tol = max(1e-9, abs(hi) * 0.002)
        return any(lo - tol <= n <= hi + tol for n in nums)
    letters = set(re.findall(r"\(([A-D])\)", plain))
    if not letters:
        return None
    return letters == set(key.replace(";", ",").replace(" ", "").split(","))


def main():
    crops = sys.argv[1]
    out = os.path.join(ROOT, "book")
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    rows = json.load(open(os.path.join(ROOT, "data", "questions.json")))
    tax = json.load(open(os.path.join(ROOT, "syllabus", "ec_2027_taxonomy.json")))
    sections = tax["sections"] + tax["general_aptitude"]["sections"]

    by_paper = defaultdict(list)
    for r in rows:
        by_paper[r["id"].rsplit("-", 1)[0]].append(r)

    papers, questions = [], []
    for paper, (year, set_label, pdf, _) in PAPERS.items():
        sols = parse_blocks(os.path.join(ROOT, "data", "solutions", paper + ".md"))
        kp = os.path.join(ROOT, "data", "keys", paper + ".json")
        keys = json.load(open(kp)) if os.path.exists(kp) else {}
        imgs, solved = {}, 0
        for r in by_paper[paper]:
            q = r["q_no"]
            img = os.path.join(crops, paper, q + ".webp")
            if os.path.exists(img):
                imgs[q] = tidy_image(img)
            s = sols.get("Q" + q)
            if s:
                solved += 1
            questions.append({
                "id": r["id"], "paper": paper, "year": year, "set": set_label,
                "sec": r["paper"], "q": q, "marks": r["marks"], "type": r["type"],
                "subject": r["subject_id"], "topic": r["topic_id"], "subtopic": r["subtopic_id"],
                "summary": r["summary"], "off": r["off_syllabus_topic"],
                "img": q in imgs,
                "key": keys.get(q),
                "ok": check_answer(s.get("ans", ""), keys.get(q)) if s else None,
                "sol": None if not s else {
                    "ans": s.get("ans_html", ""), "concept": s.get("concept_html", ""),
                    "level": s.get("level", ""), "style": s.get("style", ""), "html": s["html"]},
            })
        json.dump(imgs, open(os.path.join(out, "data", f"img-{paper}.json"), "w"), separators=(",", ":"))
        papers.append({"id": paper, "year": year, "set": set_label, "pdf": pdf,
                       "count": len(by_paper[paper]), "solved": solved, "images": len(imgs)})

    pages = {}
    book_dir = os.path.join(ROOT, "data", "book")
    for name in ("patterns", "predictions", "bank", "about"):
        p = os.path.join(book_dir, name + ".md")
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8").read()
        if "\n@@ " in text or text.startswith("@@ "):
            intro, _, _ = text.partition("\n@@ ")
            pages[name] = {"intro": md_to_html(intro.strip()),
                           "items": [dict(id=k, **v) for k, v in parse_blocks(p).items()]}
        else:
            pages[name] = {"intro": md_to_html(text), "items": []}

    book = {"papers": papers, "sections": sections, "questions": questions, "pages": pages}
    json.dump(book, open(os.path.join(out, "data", "book.json"), "w"), separators=(",", ":"))
    shutil.copy(os.path.join(out, "src", "index.html"), os.path.join(out, "index.html"))
    total = sum(p["solved"] for p in papers)
    bad = [q["id"] for q in questions if q["ok"] is False]
    unk = [q["id"] for q in questions if q["sol"] and q["key"] and q["ok"] is None]
    print("key mismatches:", " ".join(bad) or "none")
    if unk:
        print("not auto-comparable:", " ".join(unk))
    print(f"{len(questions)} questions, {total} solved, "
          f"{sum(p['images'] for p in papers)} images, pages: {', '.join(pages)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the classified GATE EC PYQ dataset.

Inputs (hand-labelled, one row per question):
  data/labels/<paper>.tsv   q_no <TAB> - <TAB> label_id <TAB> summary [<TAB> off-syllabus topic]
  data/types/<paper>.json   {q_no: "M" | "S" | "N"}  (MCQ / MSQ / NAT); missing file => all MCQ
  syllabus/ec_2027_taxonomy.json

label_id is the finest level that fits: a subtopic (EC.2.5.4), a topic (EC.4.1) or,
rarely, a section (EC.1). A fifth column marks a question whose topic is not in the
GATE 2027 EC syllabus (e.g. "8085 microprocessor"); label_id then points at the
closest syllabus node.

Outputs:
  data/questions.csv, data/questions.json
  reports/topic_weightage.md, reports/year_by_subject.md, reports/questions_by_topic.md
"""
import csv
import json
import os
from collections import Counter, OrderedDict, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# paper -> (year, set label, source pdf, numbering scheme)
# Numbering schemes:
#   old85  : Q1-20 = 1 mark, Q21-85 = 2 marks, no GA
#   old60  : Q1-20 = 1 mark, Q21-60 = 2 marks, no GA
#   ec_ga  : EC Q1-25 (1), Q26-55 (2); GA Q56-60 (1), Q61-65 (2)
#   gapre  : GA numbered GA1-GA10 (1-5 = 1 mark, 6-10 = 2); EC Q1-25 (1), Q26-55 (2)
#   ga_ec  : GA Q1-5 (1), Q6-10 (2); EC Q11-35 (1), Q36-65 (2)
PAPERS = OrderedDict([
    ("2007", (2007, "", "EC2007.pdf", "old85")),
    ("2008", (2008, "", "EC2008.pdf", "old85")),
    ("2009", (2009, "", "EC2009.pdf", "old60")),
    ("2010", (2010, "", "EC2010.pdf", "ec_ga")),
    ("2011", (2011, "", "EC2011.pdf", "ec_ga")),
    ("2012", (2012, "", "EC2012.pdf", "ec_ga")),
    ("2013", (2013, "", "EC2013.pdf", "ec_ga")),
    ("2014-1", (2014, "Set 1", "EC2014.pdf", "gapre")),
    ("2014-2", (2014, "Set 2", "EC2014.pdf", "gapre")),
    ("2014-3", (2014, "Set 3", "EC2014.pdf", "gapre")),
    ("2014-4", (2014, "Set 4", "EC2014.pdf", "gapre")),
    ("2015-1", (2015, "Set 1", "EC2015.pdf", "ga_ec")),
    ("2015-2", (2015, "Set 2", "EC2015.pdf", "ga_ec")),
    ("2015-3", (2015, "Set 3", "EC2015.pdf", "ga_ec")),
    ("2016-1", (2016, "Set 1", "EC2016.pdf", "gapre")),
    ("2016-2", (2016, "Set 2", "EC2016.pdf", "gapre")),
    ("2016-3", (2016, "Set 3", "EC2016.pdf", "gapre")),
    ("2017-1", (2017, "Set 1", "EC1-2017.pdf", "ec_ga")),
    ("2017-2", (2017, "Set 2", "EC2-2017.pdf", "ec_ga")),
    ("2018", (2018, "", "EC2018.pdf", "gapre")),
    ("2019", (2019, "", "EC2019.pdf", "gapre")),
    ("2020", (2020, "", "EC2020.pdf", "gapre")),
    ("2021", (2021, "", "EC2021.pdf", "gapre")),
    ("2022", (2022, "", "EC2022.pdf", "ga_ec")),
    ("2023", (2023, "", "EC2023.pdf", "ga_ec")),
    ("2024", (2024, "", "EC2024.pdf", "ga_ec")),
    ("2025", (2025, "", "EC2025.pdf", "ga_ec")),
    ("2026", (2026, "", "EC.pdf", "ga_ec")),
])

EXPECTED = {"old85": 85, "old60": 60, "ec_ga": 65, "gapre": 65, "ga_ec": 65}
TYPE_NAMES = {"M": "MCQ", "S": "MSQ", "N": "NAT"}


def marks_for(scheme, q):
    if scheme == "old85":
        return 1 if int(q) <= 20 else 2
    if scheme == "old60":
        return 1 if int(q) <= 20 else 2
    if scheme == "gapre":
        if q.startswith("GA"):
            return 1 if int(q[2:]) <= 5 else 2
        return 1 if int(q) <= 25 else 2
    n = int(q)
    if scheme == "ec_ga":
        if n <= 25:
            return 1
        if n <= 55:
            return 2
        return 1 if n <= 60 else 2
    if scheme == "ga_ec":
        if n <= 5:
            return 1
        if n <= 10:
            return 2
        return 1 if n <= 35 else 2
    raise ValueError(scheme)


def load_taxonomy():
    tax = json.load(open(os.path.join(ROOT, "syllabus", "ec_2027_taxonomy.json")))
    nodes = {}
    sections = tax["sections"] + tax["general_aptitude"]["sections"]
    for s in sections:
        nodes[s["id"]] = {"level": "section", "name": s["name"], "section": s}
        for t in s["topics"]:
            nodes[t["id"]] = {"level": "topic", "name": t["name"], "section": s, "topic": t}
            for st in t["subtopics"]:
                nodes[st["id"]] = {"level": "subtopic", "name": st["name"], "section": s,
                                   "topic": t, "subtopic": st}
    return sections, nodes


def main():
    sections, nodes = load_taxonomy()
    rows, errors = [], []
    for paper, (year, set_label, pdf, scheme) in PAPERS.items():
        types_path = os.path.join(ROOT, "data", "types", paper + ".json")
        types = json.load(open(types_path)) if os.path.exists(types_path) else {}
        seen = set()
        with open(os.path.join(ROOT, "data", "labels", paper + ".tsv")) as f:
            for line_no, line in enumerate(f, 1):
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 4:
                    errors.append(f"{paper}:{line_no}: expected >=4 columns")
                    continue
                q, _, label, summary = parts[:4]
                extra = parts[4] if len(parts) > 4 else ""
                if q in seen:
                    errors.append(f"{paper}: duplicate question {q}")
                seen.add(q)
                node = nodes.get(label)
                if node is None:
                    errors.append(f"{paper} Q{q}: unknown label {label}")
                    continue
                is_ga = label.startswith("GA")
                q_is_ga = (q.startswith("GA") or (scheme == "ec_ga" and int(q) > 55)
                           or (scheme == "ga_ec" and int(q) <= 10))
                if is_ga != q_is_ga:
                    errors.append(f"{paper} Q{q}: GA/EC label mismatch ({label})")
                t = types.get(q, "M")
                sec, top, sub = node["section"], node.get("topic"), node.get("subtopic")
                rows.append(OrderedDict([
                    ("id", f"{paper}-{q}"),
                    ("year", year),
                    ("set", set_label),
                    ("paper", "GA" if is_ga else "EC"),
                    ("q_no", q),
                    ("marks", marks_for(scheme, q)),
                    ("type", TYPE_NAMES[t]),
                    ("subject_id", sec["id"]),
                    ("subject", sec["name"]),
                    ("topic_id", top["id"] if top else ""),
                    ("topic", top["name"] if top else ""),
                    ("subtopic_id", sub["id"] if sub else ""),
                    ("subtopic", sub["name"] if sub else ""),
                    ("in_2027_syllabus", "no" if extra else "yes"),
                    ("off_syllabus_topic", extra),
                    ("summary", summary),
                    ("source_pdf", pdf),
                ]))
        if len(seen) != EXPECTED[scheme]:
            errors.append(f"{paper}: {len(seen)} questions, expected {EXPECTED[scheme]}")
        for q in types:
            if q not in seen:
                errors.append(f"{paper}: type given for unknown question {q}")
    if errors:
        raise SystemExit("\n".join(errors))

    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "questions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(ROOT, "data", "questions.json"), "w") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)

    write_reports(sections, rows)
    print(f"{len(rows)} questions from {len(PAPERS)} papers")


def paper_label(r):
    return f"{r['year']}" + (f" {r['set']}" if r["set"] else "")


def write_reports(sections, rows):
    years = sorted({r["year"] for r in rows})
    ec = [r for r in rows if r["paper"] == "EC"]
    n_papers = len(PAPERS)

    # --- topic weightage -------------------------------------------------
    by_sub = defaultdict(list)
    by_top = defaultdict(list)
    by_sec = defaultdict(list)
    for r in rows:
        by_sec[r["subject_id"]].append(r)
        if r["topic_id"]:
            by_top[r["topic_id"]].append(r)
        if r["subtopic_id"]:
            by_sub[r["subtopic_id"]].append(r)
    recent = [y for y in years if y >= years[-1] - 4]

    def stat(qs):
        m = sum(q["marks"] for q in qs)
        rq = [q for q in qs if q["year"] in recent]
        return len(qs), m, round(m / n_papers, 1), len(rq)

    out = ["# Topic-wise weightage — GATE EC PYQs", "",
           f"{len(rows)} questions from {n_papers} papers ({years[0]}–{years[-1]}; "
           "2014–2017 have multiple sets). Built by `scripts/build.py` from `data/labels/`.", "",
           f"*Avg marks/paper* = total marks ÷ {n_papers} papers. "
           f"*Last 5 yrs* = question count in {recent[0]}–{recent[-1]}.", ""]
    total_ec_marks = sum(r["marks"] for r in ec)
    out += ["## Subjects (EC part)", "",
            "| Subject | Questions | Marks | Avg marks/paper | Share of EC marks | Last 5 yrs |",
            "|---|---:|---:|---:|---:|---:|"]
    for s in sections:
        if s["id"].startswith("GA"):
            continue
        n, m, avg, rc = stat(by_sec[s["id"]])
        out.append(f"| {s['id']} {s['name']} | {n} | {m} | {avg} | {100*m/total_ec_marks:.1f}% | {rc} |")
    ga = [r for r in rows if r["paper"] == "GA"]
    out += ["", f"General Aptitude: {len(ga)} questions, {sum(r['marks'] for r in ga)} marks "
            "(from 2010 onwards).", ""]

    for s in sections:
        out += [f"## {s['id']} {s['name']}", "",
                "| Topic / subtopic | Questions | Marks | Last 5 yrs |", "|---|---:|---:|---:|"]
        general = [r for r in by_sec[s["id"]] if not r["topic_id"]]
        if general:
            n, m, _, rc = stat(general)
            out.append(f"| *(general / not tied to one topic)* | {n} | {m} | {rc} |")
        for t in s["topics"]:
            n, m, _, rc = stat(by_top[t["id"]])
            out.append(f"| **{t['id']} {t['name']}** | **{n}** | **{m}** | **{rc}** |")
            topic_only = [r for r in by_top[t["id"]] if not r["subtopic_id"]]
            for st in t["subtopics"]:
                n, m, _, rc = stat(by_sub[st["id"]])
                if n:
                    out.append(f"| &nbsp;&nbsp;{st['id']} {st['name']} | {n} | {m} | {rc} |")
            if topic_only:
                n, m, _, rc = stat(topic_only)
                out.append(f"| &nbsp;&nbsp;*(other / whole topic)* | {n} | {m} | {rc} |")
            zero = [st["name"] for st in t["subtopics"] if not by_sub[st["id"]]]
            if zero and not s["id"].startswith("GA"):
                out.append(f"| &nbsp;&nbsp;*never asked:* {', '.join(zero)} | 0 | 0 | 0 |")
        out.append("")

    off = [r for r in rows if r["off_syllabus_topic"]]
    cnt = Counter(r["off_syllabus_topic"] for r in off)
    out += ["## Questions on topics outside the 2027 syllabus", "",
            "Tagged under the closest syllabus topic, and flagged `in_2027_syllabus = no`.", "",
            "| Topic | Questions | Years |", "|---|---:|---|"]
    for k, v in cnt.most_common():
        ys = sorted({r["year"] for r in off if r["off_syllabus_topic"] == k})
        out.append(f"| {k} | {v} | {', '.join(map(str, ys))} |")
    open(os.path.join(ROOT, "reports", "topic_weightage.md"), "w").write("\n".join(out) + "\n")

    # --- year x subject marks matrix ---------------------------------------
    papers = list(OrderedDict.fromkeys(paper_label(r) for r in rows))
    out = ["# Marks per subject per paper", "",
           "Marks from each subject in each paper (EC part, plus GA).", "",
           "| Paper | " + " | ".join(s["id"] for s in sections if not s["id"].startswith("GA"))
           + " | GA | Total |",
           "|---|" + "---:|" * (len([s for s in sections if not s["id"].startswith("GA")]) + 2)]
    for p in papers:
        pr = [r for r in rows if paper_label(r) == p]
        cells = []
        for s in sections:
            if s["id"].startswith("GA"):
                continue
            cells.append(str(sum(r["marks"] for r in pr if r["subject_id"] == s["id"])))
        g = sum(r["marks"] for r in pr if r["paper"] == "GA")
        out.append(f"| {p} | " + " | ".join(cells) + f" | {g} | {sum(r['marks'] for r in pr)} |")
    out += ["", "Subject key: " + "; ".join(f"{s['id']} = {s['name']}" for s in sections
                                         if not s["id"].startswith("GA"))]
    open(os.path.join(ROOT, "reports", "year_by_subject.md"), "w").write("\n".join(out) + "\n")

    # --- every question listed under its topic ---------------------------------
    out = ["# Questions by topic", "",
           "Every question, grouped by subject → topic → subtopic. "
           "Reference format: `year [set] Q<no> (<marks>m, <type>)`.", ""]
    def fmt(r):
        flag = f" — *off-syllabus: {r['off_syllabus_topic']}*" if r["off_syllabus_topic"] else ""
        return (f"- {paper_label(r)} Q{r['q_no']} ({r['marks']}m, {r['type']}): "
                f"{r['summary']}{flag}")
    def key(r):
        return (r["year"], r["set"], int(r["q_no"].replace("GA", "")))
    for s in sections:
        out += [f"## {s['id']} {s['name']} ({len(by_sec[s['id']])})", ""]
        general = sorted([r for r in by_sec[s["id"]] if not r["topic_id"]], key=key)
        if general:
            out += ["**General**", ""] + [fmt(r) for r in general] + [""]
        for t in s["topics"]:
            qs = by_top[t["id"]]
            if not qs:
                continue
            out += [f"### {t['id']} {t['name']} ({len(qs)})", ""]
            for st in t["subtopics"]:
                sq = sorted(by_sub[st["id"]], key=key)
                if sq:
                    out += [f"**{st['id']} {st['name']}** ({len(sq)})", ""] + [fmt(r) for r in sq] + [""]
            rest = sorted([r for r in qs if not r["subtopic_id"]], key=key)
            if rest:
                out += [f"**Other {t['name']}** ({len(rest)})", ""] + [fmt(r) for r in rest] + [""]
    open(os.path.join(ROOT, "reports", "questions_by_topic.md"), "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()

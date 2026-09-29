# GATE EC previous-year questions, classified by topic

Every question from 28 GATE Electronics & Communication (EC) papers, 2007–2026, classified by
**subject → topic → subtopic** of the GATE 2027 EC syllabus. That is 1,855 questions. The
papers include every set from 2014–2017.

## What's where

| Path | Contents |
|---|---|
| `reports/topic_weightage.md` | Question count and marks per subject, topic and subtopic, plus a last-5-years column and subtopics never asked |
| `reports/year_by_subject.md` | Marks per subject in each paper |
| `reports/questions_by_topic.md` | Every question listed under its topic, e.g. `2014 Set 3 Q52 (2m, NAT): Entropy of outputs of cascaded BSCs` |
| `data/questions.csv` / `.json` | One row per question: year, set, GA/EC, question no., marks, MCQ/MSQ/NAT, subject/topic/subtopic IDs and names, a one-line summary, syllabus flag, source PDF |
| `syllabus/ec_2027_taxonomy.json` | The label set: 8 EC sections, 41 topics and 197 subtopics from the official syllabus, plus General Aptitude |
| `data/labels/*.tsv` | The hand-made classification, one file per paper. This is the file to edit |
| `data/types/*.json` | MCQ / MSQ / NAT per question |
| `scripts/build.py` | Validates the labels and regenerates everything in `data/` and `reports/` |
| `EC*.pdf` | The question papers (`EC.pdf` is GATE 2026) |

## Rebuilding after an edit

```
python3 scripts/build.py
```

The script stops with an error if a label ID isn't in the taxonomy, a question is missing or
duplicated, or a GA question carries an EC label (or the reverse).

Label format (tab-separated): `q_no  -  label_id  summary  [off-syllabus topic]`. `label_id`
is the finest level that fits: a subtopic (`EC.2.5.4`), a whole topic (`EC.4.1`) or, rarely,
a subject (`EC.1`).

## Classification notes

- **Topics outside the 2027 syllabus.** Older papers ask about topics that have since been
  dropped, such as the 8085 microprocessor, IC fabrication, numerical methods, JFETs and
  electrostatics. There are 77 such questions. Each is filed under the closest syllabus topic,
  with `in_2027_syllabus = no` and the dropped topic named. The full list is at the end of
  `topic_weightage.md`.
- **Grouped topics.** Control Systems is a flat list in the syllabus, so its six topics are my
  grouping. Waveguides, optical fibres, antennas and two-port networks were also split out of
  longer paragraphs. All of these are marked `derived: true` in the taxonomy.
- **General Aptitude.** GA isn't in the EC syllabus PDF. Its questions (2010 onward, 15 marks
  per paper) are classified under the four official GA areas: verbal, quantitative, analytical
  and spatial.
- **Numbering.** Question numbers are as printed. In 2014, 2016 and 2018–2021 the GA questions
  are numbered separately (`GA1`–`GA10`). In 2015 and from 2022, Q1–10 are GA. In 2010–2013
  and 2017, Q56–65 are GA. 2007–2009 have no GA section.
- **2013.** The PDF holds four booklets (EC-A to EC-D) with the same questions in a different
  order. Only EC-A is used.
- **2017 Set 1.** `EC1-2017.pdf` is damaged: its header and page tree are missing, so it opens
  as 0 pages. `EC1-2017-repaired.pdf` is a rebuilt copy (24 pages, all questions readable).
- **Question types** come from the answer keys where the PDFs include them (2014–2018, 2020).
  For 2019 and 2021 they were read from the paper layout. For 2022–2026 MSQs were identified
  from the wording ("is/are", "option(s)"). All papers before 2014 are MCQ only.

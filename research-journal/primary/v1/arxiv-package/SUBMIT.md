# arXiv Submission Instructions

## Local PDF generation

Verified on Ubuntu 22.04 with pandoc 2.9.2.1 + pandoc-citeproc + texlive-xetex on 2026-05-15.

```bash
# From this directory:
pandoc paper.md \
  --bibliography=references.bib \
  --filter pandoc-citeproc \
  --csl=https://www.zotero.org/styles/ieee \
  --pdf-engine=xelatex \
  -V geometry:margin=1in \
  -V fontsize=10pt \
  -V mainfont="DejaVu Serif" \
  -V monofont="DejaVu Sans Mono" \
  -o paper.pdf
```

Important flags (don't drop these):

- `--filter pandoc-citeproc` — pandoc 2.x does NOT recognize the bare `--citeproc` flag; needs the filter form. (Newer pandoc 3.x uses `--citeproc` as a flag; if you're on 3.x, swap accordingly.)
- `--pdf-engine=xelatex` + `-V mainfont="DejaVu Serif"` — required because the paper uses Greek letters (κ for inter-annotator agreement) and math symbols (≤, ≥) that the default `lmroman` font does not cover. Without these flags, those characters render as missing glyphs in the PDF.
- `-V monofont="DejaVu Sans Mono"` — keeps inline code blocks consistent under the xelatex font stack.

Note: `paper.md` includes a `# References` heading with a `<div id="refs"></div>`
placement marker that pandoc citeproc populates in place. The appendix sections
(A.1-A.6 in `A0-appendix.md`) are merged into `paper.md` after the bibliography
div and are excluded from the 4-page body budget per ML4H Findings convention.

For an arXiv source bundle (preferred — let arXiv compile):

```bash
pandoc paper.md \
  --bibliography=references.bib \
  --biblatex \
  -o paper.tex

# Then upload paper.tex + references.bib + figures/ + tables/ to arXiv.
```

## arXiv submission

1. Go to https://arxiv.org/submit
2. Login with author account
3. Categories:
   - Primary: cs.AI
   - Secondary: cs.IR
   - Tertiary: q-bio.QM
4. Upload either paper.pdf (final) or the LaTeX source bundle (paper.tex + references.bib + figures/ + tables/).
5. Title: "Pre-Fetched Retrieval and Role-Priored Tools for Multi-Agent Clinical Research over Diet, Herb, and TCM Knowledge Graphs"
6. Abstract: copy from `00-abstract.md`
7. License: choose CC-BY 4.0 (preferred) or CC-BY-NC-SA 4.0
8. Submit; arXiv typically issues an ID within 1-2 business days.

## After submission

Update `research-journal/primary/v1/README.md` with the arXiv ID and DOI.

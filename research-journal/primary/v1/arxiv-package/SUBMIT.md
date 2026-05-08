# arXiv Submission Instructions

## Local PDF generation

Pandoc was not available in the dev environment. Run on a machine with pandoc + a LaTeX distribution:

```bash
# From this directory:
pandoc paper.md \
  --bibliography=references.bib \
  --citeproc \
  --csl=https://www.zotero.org/styles/ieee \
  -V geometry:margin=1in \
  -V fontsize=10pt \
  -o paper.pdf
```

Note: `paper.md` includes a `# References` heading with a `<div id="refs"></div>`
placement marker that pandoc citeproc populates in place. The appendix sections
(A.1-A.6 in `A0-appendix.md`) are merged into `paper.md` after the bibliography
div and are excluded from the 4-page body budget per ML4H Findings convention.

For an arXiv source bundle (preferred):

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

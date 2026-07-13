# Editable Word thesis

`build/thesis-editable.docx` is an editable derivative of the canonical LaTeX
thesis. Rebuild it from the repository root with:

```bash
make thesis-word
make thesis-word-validate
```

The DOCX contains editable body text, headings, lists, tables, equations, code
listings, citations, and bibliography entries. The nine TikZ/PGFPlots diagrams
and two interface screenshots are embedded images; their editable sources
remain under `thesis/figures/src/` and `thesis/figures/screenshots/`.

When opening a freshly generated file in Microsoft Word, select the whole
document (`Ctrl+A`) and press `F9` to refresh the table of contents, list of
figures, list of tables, and page fields. The delivered DOCX has already had
those fields refreshed in Microsoft Word. Captions and in-text cross-reference
numbers reflect the compiled LaTeX source at build time; after reordering or
adding figures/tables, either update those numbers carefully or rebuild the
Word derivative from LaTeX.

Microsoft Word keeps updateable TOC field ends in otherwise empty paragraphs.
If a Word-refreshed copy will also be rendered through LibreOffice, collapse
those field-end spacers without breaking the fields, then validate again:

```bash
.venv/bin/python thesis/scripts/build_word.py --post-word-cleanup
.venv/bin/python thesis/scripts/validate_word.py build/thesis-editable.docx --render
```

The conversion uses `thesis/scripts/build_word.py`, the IEEE CSL file in this
directory, Pandoc, Tectonic, and Poppler. Structural and render checks are in
`thesis/scripts/validate_word.py`. Microsoft Word is useful for the final field
refresh but is not required for the reproducible cross-platform build.

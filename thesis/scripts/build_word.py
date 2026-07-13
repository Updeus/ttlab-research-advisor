#!/usr/bin/env python3
"""Build an editable Word derivative from the canonical LaTeX thesis.

Pandoc can preserve the thesis prose and mathematics, but the source also uses
TikZ/PGFPlots, tabularx, cleveref, custom description-list options, and book
appendix numbering that do not survive a direct conversion.  This script makes
a disposable, Pandoc-friendly copy, renders code-native figures, resolves the
current compiled cross-reference numbers, and then applies a small OOXML
finishing pass.  The LaTeX tree remains the canonical manuscript source.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
THESIS = ROOT / "thesis"
BUILD = ROOT / "build"
DEFAULT_OUTPUT = BUILD / "thesis-editable.docx"
DEFAULT_WORK = ROOT / "tmp" / "pdfs" / "thesis-word"

TITLE = (
    "Engineering and Evaluating a Source-Traceable Research-Intelligence "
    "Platform for a Laboratory Corpus"
)
SUBTITLE = (
    "Design, Full-Text Retrieval, Offline Evaluation, and Reproducibility "
    "of the TTLAB Platform"
)
AUTHOR = "Jarod Esareesingh"
DEPARTMENT = "Department of Computing & Information Technology"
UNIVERSITY = "The University of the West Indies"
EMAIL = "jarod.esareesingh@my.uwi.edu"
COUNTRY = "Trinidad and Tobago"
SUBJECT = (
    "MSc Data Science project, Department of Computing & Information "
    "Technology, The University of the West Indies"
)
KEYWORDS = (
    "research intelligence, information retrieval, retrieval-augmented "
    "generation, scholarly recommendation, responsible AI, reproducibility"
)

FIGURE_SOURCES = (
    "architecture",
    "entity_model",
    "ingestion_pipeline",
    "corpus_status_plot",
    "year_distribution_plot",
    "index_coverage_plot",
    "search_rag_workflow",
    "recommendation_workflow",
    "evaluation_workflow",
)

APPENDICES = {
    "A_traceability.tex": "A",
    "B_reproducibility.tex": "B",
    "C_schema_api.tex": "C",
    "D_review_instruments.tex": "D",
}

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dcterms": "http://purl.org/dc/terms/",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

for prefix, uri in {
    "w": NS["w"],
    "r": NS["r"],
    "m": NS["m"],
    "dc": NS["dc"],
    "cp": NS["cp"],
    "dcterms": NS["dcterms"],
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wp": NS["wp"],
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
}.items():
    ET.register_namespace(prefix, uri)


def qn(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
        env=env,
    )


def require_tool(name: str, fallback: Path | None = None) -> str:
    found = shutil.which(name)
    if found:
        return found
    if fallback and fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    raise SystemExit(f"Required tool not found: {name}")


def relative_tex_path(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace(os.sep, "/")


def render_code_figures(work: Path, assets: Path, tectonic: str, pdftocairo: str) -> None:
    wrappers = work / "figure-wrappers"
    wrappers.mkdir(parents=True, exist_ok=True)
    shutil.copytree(THESIS / "generated", wrappers / "generated", dirs_exist_ok=True)

    for stem in FIGURE_SOURCES:
        wrapper = wrappers / f"word-{stem}.tex"
        preamble = relative_tex_path(THESIS / "preamble", wrappers)
        metadata = relative_tex_path(THESIS / "metadata", wrappers)
        macros = relative_tex_path(THESIS / "generated" / "evidence_macros", wrappers)
        figure = relative_tex_path(THESIS / "figures" / "src" / stem, wrappers)
        wrapper.write_text(
            "\\documentclass[tikz,border=6pt]{standalone}\n"
            "\\newcommand{\\chaptermark}[1]{}\n"
            f"\\input{{{preamble}}}\n"
            f"\\input{{{metadata}}}\n"
            f"\\input{{{macros}}}\n"
            "\\begin{document}\n"
            f"\\input{{{figure}}}\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        run(
            [
                tectonic,
                "--chatter",
                "minimal",
                "--keep-logs",
                "--outdir",
                str(wrappers),
                str(wrapper),
            ],
            cwd=THESIS,
            capture=True,
        )
        pdf = wrappers / f"word-{stem}.pdf"
        if not pdf.is_file():
            raise SystemExit(f"Figure compilation did not create {pdf}")
        output_prefix = assets / stem
        run(
            [
                pdftocairo,
                "-png",
                "-singlefile",
                "-r",
                "300",
                str(pdf),
                str(output_prefix),
            ]
        )
        image = assets / f"{stem}.png"
        if not image.is_file() or image.stat().st_size == 0:
            raise SystemExit(f"Figure rasterization did not create {image}")


def prepare_screenshots(assets: Path) -> None:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit("Pillow is required to crop the Word screenshot asset") from exc

    ask_source = THESIS / "figures" / "screenshots" / "ask-answer.png"
    with Image.open(ask_source) as image:
        crop_height = min(1022, image.height)
        cropped = image.crop((0, 0, image.width, crop_height))
        cropped.save(assets / "ask-answer-cropped.png", optimize=True)

    shutil.copy2(
        THESIS / "figures" / "screenshots" / "evaluation-current.png",
        assets / "evaluation-current.png",
    )


def parse_aux_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    aux_files = [BUILD / "thesis.aux", *(BUILD / "chapters").glob("*.aux")]
    pattern = re.compile(r"\\newlabel\{([^}@]+)\}\{\{([^{}]+)\}")
    for aux in aux_files:
        if not aux.is_file():
            continue
        for match in pattern.finditer(aux.read_text(encoding="utf-8", errors="replace")):
            label, number = match.groups()
            labels.setdefault(label, number)
    required = {
        "fig:thesis-architecture",
        "fig:entity-model",
        "fig:ingestion",
        "fig:corpus-status",
        "fig:years",
        "fig:index-coverage",
        "fig:rag-workflow",
        "fig:recommendation-workflow",
        "fig:ui-evidence",
        "fig:ui-evaluation",
        "fig:evaluation-workflow",
        "tab:stakeholders",
        "tab:rq-plan",
        "tab:experiment-inventory",
        "tab:retrieval-results",
        "tab:qa-results",
        "tab:topic-results",
        "tab:performance-results",
        "tab:rq-traceability",
        "tab:repro-identifiers",
        "tab:schema-summary",
        "tab:api-summary",
        "app:traceability",
    }
    missing = sorted(required - labels.keys())
    if missing:
        raise SystemExit(
            "Compiled AUX labels are required for Word cross-references; missing: "
            + ", ".join(missing)
        )
    return labels


def table_columns(spec: str) -> str:
    columns: list[str] = []
    index = 0
    while index < len(spec):
        char = spec[index]
        if char in "lcr":
            columns.append(char)
            index += 1
        elif char == "Y":
            columns.append("l")
            index += 1
        elif char == "P" and index + 1 < len(spec) and spec[index + 1] == "{":
            depth = 1
            index += 2
            while index < len(spec) and depth:
                if spec[index] == "{":
                    depth += 1
                elif spec[index] == "}":
                    depth -= 1
                index += 1
            columns.append("l")
        else:
            index += 1
    if not columns:
        raise ValueError(f"No table columns found in specification {spec!r}")
    return "".join(columns)


def normalize_tables(text: str) -> str:
    # Pandoc treats booktabs' spacing-only row command as content in the first
    # cell of the following longtable row, which drops values such as RQ2--RQ5.
    # Word table spacing is handled by paragraph/table styles instead.
    text = text.replace("\\addlinespace", "")
    tabularx = re.compile(
        r"\\begin\{tabularx\}\{\\textwidth\}\{([^\n]+)\}"
    )
    text = tabularx.sub(
        lambda match: f"\\begin{{tabular}}{{{table_columns(match.group(1))}}}",
        text,
    )
    text = text.replace("\\end{tabularx}", "\\end{tabular}")
    longtable = re.compile(r"\\begin\{longtable\}\{([^\n]+)\}")
    text = longtable.sub(
        lambda match: f"\\begin{{longtable}}{{{table_columns(match.group(1))}}}",
        text,
    )
    # LaTeX longtable repeats a separate continuation header between
    # \endfirsthead and \endhead. Word uses one real header row with the
    # repeat-header property, so retaining both blocks duplicates the header on
    # the first page. Keep the first header and discard the continuation copy.
    text = re.sub(
        r"\\endfirsthead\s*.*?\\endhead\s*",
        "",
        text,
        flags=re.DOTALL,
    )
    return text


def human_reference(label: str, number: str) -> str:
    if label.startswith("fig:"):
        kind = "Figure"
    elif label.startswith("tab:"):
        kind = "Table"
    elif label.startswith("ch:"):
        kind = "Chapter"
    elif label.startswith("app:"):
        kind = "Appendix"
    elif label.startswith("eq:"):
        kind = "Equation"
    else:
        kind = "Section"
    return f"\\hyperref[{label}]{{{kind} {number}}}"


def resolve_cross_references(text: str, labels: dict[str, str]) -> str:
    pattern = re.compile(r"\\(?:c|C)ref\{([^}]+)\}")

    def replacement(match: re.Match[str]) -> str:
        names = [item.strip() for item in match.group(1).split(",")]
        rendered: list[str] = []
        for name in names:
            number = labels.get(name)
            if number is None:
                raise ValueError(f"No compiled cross-reference value for {name}")
            rendered.append(human_reference(name, number))
        if len(rendered) == 1:
            return rendered[0]
        if len(rendered) == 2:
            return " and ".join(rendered)
        return ", ".join(rendered[:-1]) + ", and " + rendered[-1]

    return pattern.sub(replacement, text)


def prefix_caption(block: str, label: str, labels: dict[str, str]) -> str:
    number = labels.get(label)
    if not number:
        return block
    if label.startswith("fig:"):
        prefix = f"Figure {number}. "
    elif label.startswith("tab:"):
        prefix = f"Table {number}. "
    else:
        return block
    caption = re.search(r"\\caption(?:\[[^\]]*\])?\{", block)
    if not caption:
        return block
    return block[: caption.end()] + prefix + block[caption.end() :]


def number_captions(text: str, labels: dict[str, str]) -> str:
    environment = re.compile(
        r"\\begin\{(figure|table|longtable)\}.*?\\end\{\1\}", re.DOTALL
    )

    def replacement(match: re.Match[str]) -> str:
        block = match.group(0)
        label = re.search(r"\\label\{([^}]+)\}", block)
        return prefix_caption(block, label.group(1), labels) if label else block

    return environment.sub(replacement, text)


def replace_figure_sources(text: str) -> str:
    for stem in FIGURE_SOURCES:
        patterns = (
            re.compile(
                rf"\\resizebox\{{[^}}]+\}}\{{!\}}\{{\\input\{{figures/src/{re.escape(stem)}\}}\}}"
            ),
            re.compile(rf"\\input\{{figures/src/{re.escape(stem)}\}}"),
        )
        replacement = (
            rf"\includegraphics[width=0.96\textwidth]"
            rf"{{word-assets/{stem}.png}}"
        )
        for pattern in patterns:
            text = pattern.sub(lambda _: replacement, text)

    text = re.sub(
        r"\\includegraphics\[[^\]]*\]\{figures/screenshots/ask-answer\.png\}",
        r"\\includegraphics[width=0.96\\textwidth]{word-assets/ask-answer-cropped.png}",
        text,
    )
    text = re.sub(
        r"\\projectScreenshot\{figures/screenshots/evaluation-current\.png\}\{[^}]+\}",
        r"\\includegraphics[width=0.96\\textwidth]{word-assets/evaluation-current.png}",
        text,
    )
    return text


def normalize_equations(text: str) -> str:
    align = re.compile(r"\\begin\{align\}(.*?)\\end\{align\}", re.DOTALL)

    def replacement(match: re.Match[str]) -> str:
        rows = [row.strip() for row in re.split(r"\\\\", match.group(1)) if row.strip()]
        displays = []
        for row in rows:
            row = row.rstrip(",.")
            row = row.replace("&=", "=")
            displays.append(f"\\[{row}\\]")
        return "\n".join(displays)

    return align.sub(replacement, text)


def normalize_appendix(text: str, letter: str) -> str:
    chapter = re.compile(r"\\chapter\{([^}]+)\}", re.DOTALL)
    text = chapter.sub(
        lambda match: f"\\chapter*{{Appendix {letter}: {match.group(1)}}}",
        text,
        count=1,
    )
    counter = 0

    def section(match: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        return f"\\section*{{{letter}.{counter} {match.group(1)}}}"

    return re.sub(r"\\section\{([^}]+)\}", section, text)


def prepare_source(source: Path, assets: Path, labels: dict[str, str]) -> None:
    shutil.copytree(THESIS, source, dirs_exist_ok=True)
    shutil.copytree(assets, source / "word-assets", dirs_exist_ok=True)

    tex_files = [source / "thesis.tex", *(source / "chapters").glob("*.tex")]
    for path in tex_files:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"\\begin\{description\}\[[^\]]*\]", r"\\begin{description}", text)
        text = normalize_tables(text)
        text = replace_figure_sources(text)
        text = normalize_equations(text)
        text = resolve_cross_references(text, labels)
        text = number_captions(text, labels)
        if path.name in APPENDICES:
            text = normalize_appendix(text, APPENDICES[path.name])
        path.write_text(text, encoding="utf-8")

    master = source / "thesis.tex"
    text = master.read_text(encoding="utf-8")
    text = text.replace("\\frontmatter", "")
    text = text.replace("\\mainmatter", "\nTHESIS_WORD_MAINMATTER_MARKER\n")
    text = text.replace("\\appendix", "")
    text = text.replace("\\backmatter", "")
    text = text.replace(
        "\\tableofcontents",
        "\\chapter*{Table of Contents}\nTHESIS_WORD_TOC_FIELD",
    )
    text = text.replace(
        "\\listoffigures",
        "\\chapter*{List of Figures}\nTHESIS_WORD_LOF_FIELD",
    )
    text = text.replace(
        "\\listoftables",
        "\\chapter*{List of Tables}\nTHESIS_WORD_LOT_FIELD",
    )
    text = text.replace("\\bibliographystyle{IEEEtran}", "")
    master.write_text(text, encoding="utf-8")


def ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    return child


def set_val(element: ET.Element, value: str) -> None:
    element.set(qn("w", "val"), value)


def set_style_font(style: ET.Element, name: str, half_points: str | None = None) -> None:
    rpr = ensure_child(style, qn("w", "rPr"))
    fonts = ensure_child(rpr, qn("w", "rFonts"))
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn("w", attr), name)
    if half_points:
        set_val(ensure_child(rpr, qn("w", "sz")), half_points)
        set_val(ensure_child(rpr, qn("w", "szCs")), half_points)


def configure_style(
    style: ET.Element,
    *,
    font: str = "Times New Roman",
    size: str | None = None,
    color: str | None = None,
    bold: bool = False,
    italic: bool = False,
    align: str | None = None,
    before: str | None = None,
    after: str | None = None,
    line: str | None = None,
    keep_next: bool = False,
    page_break_before: bool = False,
) -> None:
    set_style_font(style, font, size)
    rpr = ensure_child(style, qn("w", "rPr"))
    if color:
        set_val(ensure_child(rpr, qn("w", "color")), color)
    if bold:
        ensure_child(rpr, qn("w", "b"))
    if italic:
        ensure_child(rpr, qn("w", "i"))
    ppr = ensure_child(style, qn("w", "pPr"))
    if align:
        set_val(ensure_child(ppr, qn("w", "jc")), align)
    spacing = ensure_child(ppr, qn("w", "spacing"))
    if before is not None:
        spacing.set(qn("w", "before"), before)
    if after is not None:
        spacing.set(qn("w", "after"), after)
    if line is not None:
        spacing.set(qn("w", "line"), line)
        spacing.set(qn("w", "lineRule"), "auto")
    if keep_next:
        ensure_child(ppr, qn("w", "keepNext"))
    if page_break_before:
        ensure_child(ppr, qn("w", "pageBreakBefore"))


def set_page_geometry(sect_pr: ET.Element) -> None:
    page_size = ensure_child(sect_pr, qn("w", "pgSz"))
    page_size.set(qn("w", "w"), "11906")
    page_size.set(qn("w", "h"), "16838")
    margins = ensure_child(sect_pr, qn("w", "pgMar"))
    for attr, value in {
        "top": "1587",
        "right": "1587",
        "bottom": "1587",
        "left": "1587",
        "header": "720",
        "footer": "720",
        "gutter": "0",
    }.items():
        margins.set(qn("w", attr), value)


def rewrite_docx(path: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "r") as source_zip:
        entries = {name: source_zip.read(name) for name in source_zip.namelist()}
    entries.update(replacements)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
        for name in sorted(entries):
            output_zip.writestr(name, entries[name])
    temporary.replace(path)


def cleanup_word_updated_fields(path: Path) -> int:
    """Collapse field-end-only spacer paragraphs without breaking Word fields."""

    with zipfile.ZipFile(path, "r") as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    body = document.find(qn("w", "body"))
    if body is None:
        raise SystemExit("DOCX body is missing")

    titles = {"List of Figures", "List of Tables", "List of Abbreviations"}
    children = list(body)
    compacted = 0
    for index, child in enumerate(children[:-1]):
        if child.tag != qn("w", "p") or paragraph_text(child):
            continue
        following = children[index + 1]
        if following.tag != qn("w", "p") or paragraph_text(following) not in titles:
            continue
        field_ends = [
            node
            for node in child.iter(qn("w", "fldChar"))
            if node.get(qn("w", "fldCharType")) == "end"
        ]
        if not field_ends:
            continue
        ppr = paragraph_properties(child)
        spacing = ensure_child(ppr, qn("w", "spacing"))
        spacing.set(qn("w", "before"), "0")
        spacing.set(qn("w", "after"), "0")
        spacing.set(qn("w", "line"), "1")
        spacing.set(qn("w", "lineRule"), "exact")
        mark_properties = ensure_child(ppr, qn("w", "rPr"))
        set_val(ensure_child(mark_properties, qn("w", "sz")), "2")
        set_val(ensure_child(mark_properties, qn("w", "szCs")), "2")
        compacted += 1

    if not compacted:
        raise SystemExit("No Word-updated front-matter field spacers were found")
    # ElementTree does not retain unused namespace declarations from Word's
    # root element. Keeping mc:Ignorable after those prefixes disappear makes
    # Microsoft Word report a corrupt document, so remove only that advisory
    # attribute; all namespace-qualified content remains intact.
    document.attrib.pop(
        "{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable",
        None,
    )
    rewrite_docx(
        path,
        {
            "word/document.xml": ET.tostring(
                document, encoding="utf-8", xml_declaration=True
            )
        },
    )
    return compacted


def create_reference_docx(path: Path, pandoc: str) -> None:
    result = subprocess.run(
        [pandoc, "--print-default-data-file", "reference.docx"],
        check=True,
        capture_output=True,
    )
    path.write_bytes(result.stdout)
    with zipfile.ZipFile(path, "r") as archive:
        styles = ET.fromstring(archive.read("word/styles.xml"))
        document = ET.fromstring(archive.read("word/document.xml"))

    style_map = {
        style.get(qn("w", "styleId")): style
        for style in styles.findall(qn("w", "style"))
    }
    if "Normal" in style_map:
        configure_style(
            style_map["Normal"], size="24", align="both", after="120", line="360"
        )
    for style_id in ("BodyText", "FirstParagraph"):
        if style_id in style_map:
            configure_style(
                style_map[style_id], size="24", align="both", after="120", line="360"
            )
    if "Title" in style_map:
        configure_style(
            style_map["Title"],
            size="40",
            color="16324F",
            bold=True,
            align="center",
            before="360",
            after="240",
        )
    if "Subtitle" in style_map:
        configure_style(
            style_map["Subtitle"],
            size="28",
            color="526273",
            align="center",
            after="180",
        )
    if "Author" in style_map:
        configure_style(style_map["Author"], size="28", bold=True, align="center")
    heading_settings = {
        "Heading1": ("32", "16324F", "360", "180", True),
        "Heading2": ("28", "16324F", "240", "120", False),
        "Heading3": ("24", "526273", "180", "90", False),
    }
    for style_id, (size, color, before, after, page_break) in heading_settings.items():
        if style_id in style_map:
            configure_style(
                style_map[style_id],
                size=size,
                color=color,
                bold=True,
                before=before,
                after=after,
                keep_next=True,
                page_break_before=page_break,
            )
    for style_id in ("ImageCaption", "TableCaption", "Caption"):
        if style_id in style_map:
            configure_style(
                style_map[style_id],
                size="20",
                italic=True,
                align="center",
                before="90",
                after="150",
                keep_next=style_id == "TableCaption",
            )
    for style_id in ("SourceCode", "VerbatimChar"):
        if style_id in style_map:
            configure_style(
                style_map[style_id],
                font="Consolas",
                size="18",
                line="240",
                align="left",
            )
    if "Bibliography" in style_map:
        configure_style(
            style_map["Bibliography"], size="20", align="left", after="90", line="240"
        )
    if "DefinitionTerm" in style_map:
        configure_style(
            style_map["DefinitionTerm"],
            size="20",
            bold=True,
            before="30",
            after="0",
            line="240",
            keep_next=True,
        )
    if "Definition" in style_map:
        configure_style(
            style_map["Definition"], size="20", before="0", after="30", line="240"
        )

    for sect_pr in document.iter(qn("w", "sectPr")):
        set_page_geometry(sect_pr)

    rewrite_docx(
        path,
        {
            "word/styles.xml": ET.tostring(styles, encoding="utf-8", xml_declaration=True),
            "word/document.xml": ET.tostring(
                document, encoding="utf-8", xml_declaration=True
            ),
        },
    )


def paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(qn("w", "t"))).strip()


def paragraph_properties(paragraph: ET.Element) -> ET.Element:
    ppr = paragraph.find(qn("w", "pPr"))
    if ppr is None:
        ppr = ET.Element(qn("w", "pPr"))
        paragraph.insert(0, ppr)
    return ppr


def paragraph_style_id(paragraph: ET.Element) -> str:
    style = paragraph.find(f"./{qn('w', 'pPr')}/{qn('w', 'pStyle')}")
    return style.get(qn("w", "val"), "") if style is not None else ""


def set_paragraph_style(paragraph: ET.Element, style_id: str, align: str | None = None) -> None:
    ppr = paragraph_properties(paragraph)
    set_val(ensure_child(ppr, qn("w", "pStyle")), style_id)
    if align:
        set_val(ensure_child(ppr, qn("w", "jc")), align)


def field_run(instruction: str, placeholder: str) -> list[ET.Element]:
    begin = ET.Element(qn("w", "r"))
    ET.SubElement(begin, qn("w", "fldChar"), {qn("w", "fldCharType"): "begin"})
    instr_run = ET.Element(qn("w", "r"))
    instr = ET.SubElement(instr_run, qn("w", "instrText"))
    instr.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    instr.text = instruction
    separate = ET.Element(qn("w", "r"))
    ET.SubElement(separate, qn("w", "fldChar"), {qn("w", "fldCharType"): "separate"})
    display = ET.Element(qn("w", "r"))
    ET.SubElement(display, qn("w", "t")).text = placeholder
    end = ET.Element(qn("w", "r"))
    ET.SubElement(end, qn("w", "fldChar"), {qn("w", "fldCharType"): "end"})
    return [begin, instr_run, separate, display, end]


def replace_with_field(paragraph: ET.Element, instruction: str, placeholder: str) -> None:
    for child in list(paragraph):
        if child.tag != qn("w", "pPr"):
            paragraph.remove(child)
    for run_element in field_run(instruction, placeholder):
        paragraph.append(run_element)


def add_relationship(rels: ET.Element, rel_type: str, target: str) -> str:
    ids = []
    for relationship in rels:
        rel_id = relationship.get("Id", "")
        match = re.fullmatch(r"rId(\d+)", rel_id)
        if match:
            ids.append(int(match.group(1)))
    rel_id = f"rId{max(ids, default=0) + 1}"
    ET.SubElement(
        rels,
        f"{{{NS['rel']}}}Relationship",
        {
            "Id": rel_id,
            "Type": rel_type,
            "Target": target,
        },
    )
    return rel_id


def make_header() -> bytes:
    header = ET.Element(qn("w", "hdr"))
    paragraph = ET.SubElement(header, qn("w", "p"))
    ppr = ET.SubElement(paragraph, qn("w", "pPr"))
    set_val(ET.SubElement(ppr, qn("w", "jc")), "center")
    run_element = ET.SubElement(paragraph, qn("w", "r"))
    rpr = ET.SubElement(run_element, qn("w", "rPr"))
    set_val(ET.SubElement(rpr, qn("w", "color")), "526273")
    set_val(ET.SubElement(rpr, qn("w", "sz")), "18")
    ET.SubElement(run_element, qn("w", "t")).text = "TTLAB Research Intelligence Platform"
    return ET.tostring(header, encoding="utf-8", xml_declaration=True)


def make_footer() -> bytes:
    footer = ET.Element(qn("w", "ftr"))
    paragraph = ET.SubElement(footer, qn("w", "p"))
    ppr = ET.SubElement(paragraph, qn("w", "pPr"))
    set_val(ET.SubElement(ppr, qn("w", "jc")), "center")
    for item in field_run(" PAGE ", "1"):
        paragraph.append(item)
    return ET.tostring(footer, encoding="utf-8", xml_declaration=True)


def set_section_links(sect_pr: ET.Element, header_id: str, footer_id: str) -> None:
    for tag in (qn("w", "headerReference"), qn("w", "footerReference")):
        for existing in list(sect_pr.findall(tag)):
            sect_pr.remove(existing)
    header = ET.Element(
        qn("w", "headerReference"),
        {qn("w", "type"): "default", qn("r", "id"): header_id},
    )
    footer = ET.Element(
        qn("w", "footerReference"),
        {qn("w", "type"): "default", qn("r", "id"): footer_id},
    )
    sect_pr.insert(0, footer)
    sect_pr.insert(0, header)


def add_content_type(content_types: ET.Element, part_name: str, content_type: str) -> None:
    for child in content_types:
        if child.get("PartName") == part_name:
            return
    ET.SubElement(
        content_types,
        f"{{{NS['ct']}}}Override",
        {"PartName": part_name, "ContentType": content_type},
    )


def finish_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        styles = ET.fromstring(archive.read("word/styles.xml"))
        settings = ET.fromstring(archive.read("word/settings.xml"))
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        content_types = ET.fromstring(archive.read("[Content_Types].xml"))
        core = ET.fromstring(archive.read("docProps/core.xml"))

    body = document.find(qn("w", "body"))
    if body is None:
        raise SystemExit("DOCX body is missing")

    output_style_map = {
        style.get(qn("w", "styleId")): style
        for style in styles.findall(qn("w", "style"))
    }
    if "SourceCode" not in output_style_map:
        raise SystemExit("Pandoc output is missing the SourceCode style")
    configure_style(
        output_style_map["SourceCode"],
        font="Consolas",
        size="18",
        line="240",
        align="left",
    )

    field_markers = {
        "THESIS_WORD_TOC_FIELD": (
            ' TOC \\o "1-3" \\h \\z \\u ',
            "Update this field in Word to generate the table of contents.",
        ),
        "THESIS_WORD_LOF_FIELD": (
            ' TOC \\h \\z \\t "Image Caption,1" ',
            "Update this field in Word to generate the list of figures.",
        ),
        "THESIS_WORD_LOT_FIELD": (
            ' TOC \\h \\z \\t "Table Caption,1" ',
            "Update this field in Word to generate the list of tables.",
        ),
    }

    main_marker: ET.Element | None = None
    title_styles = {
        UNIVERSITY: "Subtitle",
        DEPARTMENT: "Subtitle",
        TITLE: "Title",
        SUBTITLE: "Subtitle",
        "MSc Data Science Project": "Subtitle",
        AUTHOR: "Author",
        EMAIL: "Normal",
        COUNTRY: "Normal",
    }
    for paragraph in body.findall(qn("w", "p")):
        text = paragraph_text(paragraph)
        if text in field_markers:
            instruction, placeholder = field_markers[text]
            replace_with_field(paragraph, instruction, placeholder)
        elif text == "THESIS_WORD_MAINMATTER_MARKER":
            main_marker = paragraph
            for child in list(paragraph):
                if child.tag != qn("w", "pPr"):
                    paragraph.remove(child)
        elif text in title_styles:
            set_paragraph_style(paragraph, title_styles[text], "center")
        elif text.startswith("Evidence snapshot "):
            set_paragraph_style(paragraph, "Normal", "center")
        elif text.endswith("Introduction") and paragraph_style_id(paragraph) == "Heading1":
            # The front/main section break already starts Chapter 1 on a new
            # page. Override Heading 1's extra break here so LibreOffice does
            # not insert an otherwise blank page after the front matter.
            set_val(
                ensure_child(
                    paragraph_properties(paragraph), qn("w", "pageBreakBefore")
                ),
                "false",
            )

    if main_marker is None:
        raise SystemExit("Main-matter section marker was not preserved")

    # Pandoc leaves an empty FirstParagraph between the three front-matter list
    # fields. If the preceding field fills a page, that paragraph can spill to
    # a page of its own and the following Heading 1 page break then creates a
    # visibly blank page. Remove only these known inter-list spacer paragraphs.
    children = list(body)
    front_list_titles = {"List of Figures", "List of Tables", "List of Abbreviations"}
    for index, child in enumerate(children[:-1]):
        if child.tag != qn("w", "p") or paragraph_text(child):
            continue
        following = children[index + 1]
        if (
            following.tag == qn("w", "p")
            and paragraph_text(following) in front_list_titles
        ):
            body.remove(child)

    final_sect = body.find(qn("w", "sectPr"))
    if final_sect is None:
        final_sect = ET.SubElement(body, qn("w", "sectPr"))
    set_page_geometry(final_sect)

    front_sect = copy.deepcopy(final_sect)
    set_page_geometry(front_sect)
    front_num = ensure_child(front_sect, qn("w", "pgNumType"))
    front_num.set(qn("w", "fmt"), "lowerRoman")
    front_num.set(qn("w", "start"), "1")
    ensure_child(front_sect, qn("w", "titlePg"))
    main_num = ensure_child(final_sect, qn("w", "pgNumType"))
    main_num.set(qn("w", "fmt"), "decimal")
    main_num.set(qn("w", "start"), "1")

    header_id = add_relationship(
        relationships,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header",
        "header1.xml",
    )
    footer_id = add_relationship(
        relationships,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer",
        "footer1.xml",
    )
    set_section_links(front_sect, header_id, footer_id)
    set_section_links(final_sect, header_id, footer_id)
    paragraph_properties(main_marker).append(front_sect)

    update = settings.find(qn("w", "updateFields"))
    if update is None:
        update = ET.SubElement(settings, qn("w", "updateFields"))
    set_val(update, "true")

    for table in body.iter(qn("w", "tbl")):
        rows = table.findall(qn("w", "tr"))
        for index, row in enumerate(rows):
            trpr = row.find(qn("w", "trPr"))
            if trpr is None:
                trpr = ET.Element(qn("w", "trPr"))
                row.insert(0, trpr)
            ensure_child(trpr, qn("w", "cantSplit"))
            if index == 0:
                ensure_child(trpr, qn("w", "tblHeader"))
        if rows:
            header = [paragraph_text(cell) for cell in rows[0].findall(qn("w", "tc"))]
            if header == ["RQ", "Method", "Evidence", "Result", "Conclusion"]:
                grid = table.find(qn("w", "tblGrid"))
                grid_columns = grid.findall(qn("w", "gridCol")) if grid is not None else []
                if len(grid_columns) == 5:
                    first_width = int(grid_columns[0].get(qn("w", "w"), "536"))
                    second_width = int(grid_columns[1].get(qn("w", "w"), "1762"))
                    delta = max(0, 720 - first_width)
                    grid_columns[0].set(qn("w", "w"), str(first_width + delta))
                    grid_columns[1].set(
                        qn("w", "w"), str(max(1200, second_width - delta))
                    )
                for row in rows:
                    cells = row.findall(qn("w", "tc"))
                    if not cells:
                        continue
                    tcpr = cells[0].find(qn("w", "tcPr"))
                    if tcpr is None:
                        tcpr = ET.Element(qn("w", "tcPr"))
                        cells[0].insert(0, tcpr)
                    ensure_child(tcpr, qn("w", "noWrap"))
                    width = ensure_child(tcpr, qn("w", "tcW"))
                    width.set(qn("w", "w"), "720")
                    width.set(qn("w", "type"), "dxa")

    captions = [
        paragraph_text(paragraph)
        for paragraph in body.iter(qn("w", "p"))
        if paragraph_style_id(paragraph) == "ImageCaption"
    ]
    drawing_properties = list(body.iter(qn("wp", "docPr")))
    if len(captions) != len(drawing_properties):
        raise SystemExit(
            "Cannot attach figure alternative text: "
            f"{len(captions)} captions for {len(drawing_properties)} drawings"
        )
    for caption, properties in zip(captions, drawing_properties, strict=True):
        properties.set("descr", caption)
        match = re.match(r"(Figure\s+[A-Z]?\d+(?:\.\d+)?\.)", caption)
        properties.set("title", match.group(1) if match else "Thesis figure")

    properties = {
        qn("dc", "title"): TITLE,
        qn("dc", "creator"): AUTHOR,
        qn("dc", "subject"): SUBJECT,
        qn("dc", "description"): f"Author contact: {EMAIL}; {COUNTRY}",
        qn("cp", "keywords"): KEYWORDS,
        qn("cp", "lastModifiedBy"): AUTHOR,
    }
    for tag, value in properties.items():
        element = core.find(tag)
        if element is None:
            element = ET.SubElement(core, tag)
        element.text = value

    add_content_type(
        content_types,
        "/word/header1.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
    )
    add_content_type(
        content_types,
        "/word/footer1.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
    )

    # Package-level relationship and content-type parts require their namespace
    # as the default namespace.  Prefixing either root (for example ``ns0``)
    # is XML-valid but is rejected by LibreOffice and some Microsoft Word
    # versions.
    ET.register_namespace("", NS["rel"])
    relationships_xml = ET.tostring(
        relationships, encoding="utf-8", xml_declaration=True
    )
    ET.register_namespace("", NS["ct"])
    content_types_xml = ET.tostring(
        content_types, encoding="utf-8", xml_declaration=True
    )

    rewrite_docx(
        path,
        {
            "word/document.xml": ET.tostring(
                document, encoding="utf-8", xml_declaration=True
            ),
            "word/settings.xml": ET.tostring(
                settings, encoding="utf-8", xml_declaration=True
            ),
            "word/styles.xml": ET.tostring(
                styles, encoding="utf-8", xml_declaration=True
            ),
            "word/_rels/document.xml.rels": relationships_xml,
            "[Content_Types].xml": content_types_xml,
            "docProps/core.xml": ET.tostring(
                core, encoding="utf-8", xml_declaration=True
            ),
            "word/header1.xml": make_header(),
            "word/footer1.xml": make_footer(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument(
        "--post-word-cleanup",
        action="store_true",
        help="remove field-end spacer pages after Microsoft Word refreshes fields",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    if args.post_word_cleanup:
        if not output.is_file():
            raise SystemExit(f"Word document does not exist: {output}")
        compacted = cleanup_word_updated_fields(output)
        print(f"Collapsed {compacted} Word field-end spacer paragraphs in {output}")
        return 0

    pandoc = require_tool("pandoc")
    tectonic = require_tool("tectonic", Path.home() / ".local" / "bin" / "tectonic")
    pdftocairo = require_tool("pdftocairo")

    work = args.work_dir.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    assets = work / "word-assets"
    source = work / "source"
    assets.mkdir()

    print("Rendering the nine code-native thesis figures...", flush=True)
    render_code_figures(work, assets, tectonic, pdftocairo)
    prepare_screenshots(assets)
    labels = parse_aux_labels()
    prepare_source(source, assets, labels)

    reference_docx = work / "reference.docx"
    create_reference_docx(reference_docx, pandoc)
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        pandoc,
        "thesis.tex",
        "--from=latex",
        "--to=docx",
        "--standalone",
        "--number-sections",
        f"--reference-doc={reference_docx}",
        "--citeproc",
        "--csl=word/ieee.csl",
        "--bibliography=references.bib",
        "--metadata=reference-section-title:References",
        "--resource-path=.:word-assets:figures/screenshots",
        f"--output={output}",
    ]
    run(command, cwd=source)
    finish_docx(output)
    if not output.is_file() or output.stat().st_size == 0:
        raise SystemExit(f"Word build did not create {output}")

    print(f"Created {output} ({output.stat().st_size:,} bytes)", flush=True)
    if not args.keep_work:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

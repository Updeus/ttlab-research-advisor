#!/usr/bin/env python3
"""Validate the editable Word thesis structurally and, optionally, by render."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCX = ROOT / "build" / "thesis-editable.docx"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

TITLE = (
    "Source-Traceable Research Intelligence: Evidence-Grounded Discovery, "
    "Question Answering, and Thesis-Extension Support"
)
AUTHOR = "Jarod Esareesingh"
SUBJECT = (
    "MSc Data Science project, Department of Computing & Information "
    "Technology, The University of the West Indies"
)

REQUIRED_HEADINGS = {
    "Abstract",
    "Statement of Scope and AI Assistance",
    "Table of Contents",
    "List of Figures",
    "List of Tables",
    "List of Abbreviations",
    "Introduction",
    "Problem Statement",
    "Research Questions and Objectives",
    "Literature Review",
    "Methodology",
    "System Architecture and Design",
    "Data Collection and Processing",
    "Implementation",
    "Experimental Design",
    "Results",
    "Discussion",
    "Limitations, Ethics and Threats to Validity",
    "Conclusion and Future Work",
    "Appendix A: Research-Question Traceability Matrix",
    "Appendix B: Reproducibility Guide",
    "Appendix C: Schema and API Summary",
    "Appendix D: Executed AI-Review Instruments",
    "References",
}

EXPECTED_FIGURES = {
    "Figure 6.1.",
    "Figure 6.2.",
    "Figure 7.1.",
    "Figure 7.2.",
    "Figure 7.3.",
    "Figure 8.1.",
    "Figure 8.2.",
    "Figure 8.3.",
    "Figure 8.4.",
    "Figure 8.5.",
    "Figure 9.1.",
}

EXPECTED_TABLES = {
    "Table 2.1.",
    "Table 3.1.",
    "Table 9.1.",
    "Table 10.1.",
    "Table 10.2.",
    "Table 10.3.",
    "Table 10.4.",
    "Table A.1.",
    "Table B.1.",
    "Table C.1.",
    "Table C.2.",
}


def qn(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w", "t"))).strip()


def paragraph_style(paragraph: ET.Element) -> str:
    style = paragraph.find(f"./{qn('w', 'pPr')}/{qn('w', 'pStyle')}")
    return style.get(qn("w", "val"), "") if style is not None else ""


def fail(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def parse_pdfinfo(path: Path) -> dict[str, str]:
    result = subprocess.run(
        ["pdfinfo", str(path)], check=True, capture_output=True, text=True
    )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def render_check(docx: Path, keep_dir: Path | None) -> dict[str, object]:
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice:
        raise RuntimeError("LibreOffice is required for --render")
    qpdf = shutil.which("qpdf")
    if not qpdf:
        raise RuntimeError("qpdf is required for --render")

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if keep_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="thesis-word-render-")
        render_dir = Path(temporary.name)
    else:
        render_dir = keep_dir.resolve()
        if render_dir.exists():
            shutil.rmtree(render_dir)
        render_dir.mkdir(parents=True)
    profile = render_dir / "lo-profile"
    output = render_dir / "output"
    profile.mkdir()
    output.mkdir()

    command = [
        libreoffice,
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output),
        str(docx),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    pdf = output / f"{docx.stem}.pdf"
    if result.returncode != 0 or not pdf.is_file():
        raise RuntimeError(
            "LibreOffice could not render the DOCX: "
            + (result.stdout + result.stderr).strip()
        )
    subprocess.run([qpdf, "--check", str(pdf)], check=True, capture_output=True, text=True)
    info = parse_pdfinfo(pdf)
    page_count = int(info.get("Pages", "0"))
    page_size = info.get("Page size", "")
    if not (65 <= page_count <= 85):
        raise RuntimeError(f"Unexpected Word-render page count: {page_count}")
    if "595" not in page_size or "841" not in page_size:
        raise RuntimeError(f"Word render is not A4: {page_size}")
    rendered = {
        "pages": page_count,
        "page_size": page_size,
        "pdf": str(pdf),
    }
    if temporary is not None:
        temporary.cleanup()
        rendered["pdf"] = "temporary render removed"
    return rendered


def validate(docx: Path, render: bool, render_dir: Path | None) -> dict[str, object]:
    errors: list[str] = []
    if not docx.is_file() or docx.stat().st_size == 0:
        return {"status": "FAIL", "errors": [f"Missing DOCX: {docx}"]}

    required_parts = {
        "[Content_Types].xml",
        "word/document.xml",
        "word/styles.xml",
        "word/settings.xml",
        "word/_rels/document.xml.rels",
        "word/header1.xml",
        "word/footer1.xml",
        "docProps/core.xml",
    }
    with zipfile.ZipFile(docx, "r") as archive:
        bad_member = archive.testzip()
        fail(errors, bad_member is None, f"Corrupt ZIP member: {bad_member}")
        names = set(archive.namelist())
        fail(errors, required_parts <= names, "DOCX is missing required package parts")
        if errors:
            return {"status": "FAIL", "errors": errors}
        document = ET.fromstring(archive.read("word/document.xml"))
        styles = ET.fromstring(archive.read("word/styles.xml"))
        footer = ET.fromstring(archive.read("word/footer1.xml"))
        core = ET.fromstring(archive.read("docProps/core.xml"))
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        media = [name for name in names if name.startswith("word/media/")]

    paragraphs = list(document.iter(qn("w", "p")))
    by_style: dict[str, list[str]] = {}
    for paragraph in paragraphs:
        by_style.setdefault(paragraph_style(paragraph), []).append(text_of(paragraph))
    all_text = "\n".join(text_of(paragraph) for paragraph in paragraphs)

    drawings = sum(1 for _ in document.iter(qn("w", "drawing")))
    drawing_properties = list(document.iter(qn("wp", "docPr")))
    table_elements = list(document.iter(qn("w", "tbl")))
    tables = len(table_elements)
    equations = sum(1 for _ in document.iter(qn("m", "oMathPara")))
    sections = list(document.iter(qn("w", "sectPr")))
    heading1 = by_style.get("Heading1", [])
    heading2 = by_style.get("Heading2", [])
    figure_captions = by_style.get("ImageCaption", [])
    table_captions = by_style.get("TableCaption", [])
    bibliography = by_style.get("Bibliography", [])

    fail(errors, len(media) == 11, f"Expected 11 embedded media files, found {len(media)}")
    fail(errors, drawings == 11, f"Expected 11 drawings, found {drawings}")
    fail(
        errors,
        len(drawing_properties) == 11
        and all(node.get("descr", "").startswith("Figure ") for node in drawing_properties),
        "Every figure must have meaningful embedded alternative text",
    )
    fail(errors, tables == 11, f"Expected 11 editable tables, found {tables}")
    fail(errors, len(figure_captions) == 11, "Expected 11 figure captions")
    fail(errors, len(table_captions) == 11, "Expected 11 table captions")
    fail(errors, len(bibliography) == 32, "Expected 32 IEEE bibliography entries")
    fail(errors, equations >= 2, "Expected at least two display equations")
    fail(errors, len(by_style.get("SourceCode", [])) == 4, "Expected four code listings")
    fail(errors, len(by_style.get("DefinitionTerm", [])) == 25, "Definition-list labels were lost")
    fail(errors, len(heading1) == 24, f"Expected 24 Heading 1 paragraphs, found {len(heading1)}")
    fail(errors, len(heading2) == 85, f"Expected 85 Heading 2 paragraphs, found {len(heading2)}")
    normalized_heading1 = {re.sub(r"^\d+", "", heading) for heading in heading1}
    fail(
        errors,
        REQUIRED_HEADINGS <= normalized_heading1,
        "Required thesis headings are missing",
    )
    introduction_paragraphs = [
        paragraph
        for paragraph in paragraphs
        if paragraph_style(paragraph) == "Heading1"
        and text_of(paragraph).endswith("Introduction")
    ]
    introduction_break = (
        introduction_paragraphs[0].find(
            f"./{qn('w', 'pPr')}/{qn('w', 'pageBreakBefore')}"
        )
        if introduction_paragraphs
        else None
    )
    fail(
        errors,
        introduction_break is not None
        and introduction_break.get(qn("w", "val")) in {"false", "0"},
        "The first chapter may be preceded by a blank page",
    )
    body = document.find(qn("w", "body"))
    body_children = list(body) if body is not None else []
    front_list_titles = {"List of Figures", "List of Tables", "List of Abbreviations"}
    inter_list_spacers = [
        index
        for index, child in enumerate(body_children[:-1])
        if child.tag == qn("w", "p")
        and not text_of(child)
        and body_children[index + 1].tag == qn("w", "p")
        and text_of(body_children[index + 1]) in front_list_titles
    ]
    fail(
        errors,
        all(
            (spacing := body_children[index].find(
                f"./{qn('w', 'pPr')}/{qn('w', 'spacing')}"
            ))
            is not None
            and spacing.get(qn("w", "lineRule")) == "exact"
            and int(spacing.get(qn("w", "line"), "999")) <= 20
            and spacing.get(qn("w", "before"), "0") == "0"
            and spacing.get(qn("w", "after"), "0") == "0"
            for index in inter_list_spacers
        ),
        "A front-matter field-end paragraph may create a blank page",
    )
    field_types = [
        node.get(qn("w", "fldCharType"), "")
        for node in document.iter(qn("w", "fldChar"))
    ]
    fail(
        errors,
        field_types.count("begin") == field_types.count("end"),
        "Word field boundaries are unbalanced",
    )

    found_figures = {caption.split(" ", 2)[0] + " " + caption.split(" ", 2)[1] for caption in figure_captions if caption.startswith("Figure ")}
    found_tables = {caption.split(" ", 2)[0] + " " + caption.split(" ", 2)[1] for caption in table_captions if caption.startswith("Table ")}
    fail(errors, found_figures == EXPECTED_FIGURES, "Figure numbering/captions are incomplete")
    fail(errors, found_tables == EXPECTED_TABLES, "Table numbering/captions are incomplete")

    traceability_table: ET.Element | None = None
    for table in table_elements:
        rows = table.findall(qn("w", "tr"))
        if not rows:
            continue
        first_cells = [text_of(cell) for cell in rows[0].findall(qn("w", "tc"))]
        if first_cells == ["RQ", "Method", "Evidence", "Result", "Conclusion"]:
            traceability_table = table
            break
    fail(errors, traceability_table is not None, "Traceability table is missing")
    if traceability_table is not None:
        rows = traceability_table.findall(qn("w", "tr"))
        rq_values = [
            text_of(cells[0])
            for row in rows[1:]
            if (cells := row.findall(qn("w", "tc")))
        ]
        fail(
            errors,
            rq_values == ["1", "2", "3", "4", "5"],
            f"Traceability RQ identifiers are incomplete: {rq_values}",
        )
        first_cells = rows[0].findall(qn("w", "tc")) if rows else []
        no_wrap = (
            first_cells[0].find(f"./{qn('w', 'tcPr')}/{qn('w', 'noWrap')}")
            if first_cells
            else None
        )
        fail(errors, no_wrap is not None, "Traceability RQ header may wrap vertically")
        grid = traceability_table.find(qn("w", "tblGrid"))
        grid_columns = grid.findall(qn("w", "gridCol")) if grid is not None else []
        first_width = (
            int(grid_columns[0].get(qn("w", "w"), "0")) if grid_columns else 0
        )
        fail(errors, first_width >= 680, "Traceability RQ column is too narrow")

    source_code_style = next(
        (
            style
            for style in styles.findall(qn("w", "style"))
            if style.get(qn("w", "styleId")) == "SourceCode"
        ),
        None,
    )
    source_code_alignment = (
        source_code_style.find(f"./{qn('w', 'pPr')}/{qn('w', 'jc')}")
        if source_code_style is not None
        else None
    )
    fail(
        errors,
        source_code_alignment is not None
        and source_code_alignment.get(qn("w", "val")) == "left",
        "Code listings are not explicitly left aligned",
    )

    fail(errors, len(sections) == 2, f"Expected front/main Word sections, found {len(sections)}")
    for section in sections:
        page_size = section.find(qn("w", "pgSz"))
        fail(
            errors,
            page_size is not None
            and page_size.get(qn("w", "w")) == "11906"
            and page_size.get(qn("w", "h")) == "16838",
            "A Word section is not A4",
        )
    if len(sections) == 2:
        front_num = sections[0].find(qn("w", "pgNumType"))
        main_num = sections[1].find(qn("w", "pgNumType"))
        fail(
            errors,
            front_num is not None
            and front_num.get(qn("w", "fmt")) == "lowerRoman"
            and front_num.get(qn("w", "start")) == "1",
            "Front-matter Roman page numbering is missing",
        )
        # Word removes the explicit decimal format on save because decimal is the
        # OOXML default; accept either representation while requiring the restart.
        fail(
            errors,
            main_num is not None
            and main_num.get(qn("w", "fmt")) in {None, "decimal"}
            and main_num.get(qn("w", "start")) == "1",
            "Main-matter decimal page-number restart is missing",
        )

    instructions = "\n".join(
        node.text or "" for node in document.iter(qn("w", "instrText"))
    )
    instructions += "\n" + "\n".join(
        node.text or "" for node in footer.iter(qn("w", "instrText"))
    )
    fail(errors, 'TOC \\o "1-3"' in instructions, "Updateable table-of-contents field is missing")
    fail(errors, 'Image Caption,1' in instructions, "Updateable list-of-figures field is missing")
    fail(errors, 'Table Caption,1' in instructions, "Updateable list-of-tables field is missing")
    fail(errors, "PAGE" in instructions, "Page-number field is missing")

    core_values = {
        "title": core.findtext(qn("dc", "title"), default=""),
        "author": core.findtext(qn("dc", "creator"), default=""),
        "subject": core.findtext(qn("dc", "subject"), default=""),
        "description": core.findtext(qn("dc", "description"), default=""),
    }
    fail(errors, core_values["title"] == TITLE, "DOCX title metadata is incorrect")
    fail(errors, core_values["author"] == AUTHOR, "DOCX author metadata is incorrect")
    fail(errors, core_values["subject"] == SUBJECT, "DOCX subject metadata is incorrect")
    fail(
        errors,
        core_values["description"]
        == "Author contact: jarod.esareesingh@my.uwi.edu; Trinidad and Tobago",
        "DOCX author-contact metadata is incorrect",
    )

    image_relationships = [
        rel
        for rel in relationships
        if rel.get("Type", "").endswith("/image")
    ]
    fail(errors, len(image_relationships) == 11, "Expected 11 image relationships")
    fail(
        errors,
        all(rel.get("TargetMode") != "External" for rel in image_relationships),
        "A figure is externally linked instead of embedded",
    )

    forbidden_patterns = {
        "raw LaTeX environment": r"\\(?:begin|end)\{",
        "unresolved cleveref": r"\\(?:c|C)ref\{",
        "unresolved internal label": r"\[(?:fig|tab|ch|app):",
        "raw custom table column": r"P\d+mm",
        "author marker": r"AUTHOR INPUT REQUIRED",
        "placeholder marker": r"\b(?:PLACEHOLDER|TODO)\b(?!\s+markers?\b)|\?\?",
        "private local path": r"/mnt/c/|file://",
        "unwanted city": r"Port of Spain",
        "author-date citation": r"\(Narine and Hosein,? 2025\)",
        "build marker": r"THESIS_WORD_[A-Z_]+",
    }
    for label, pattern in forbidden_patterns.items():
        fail(errors, re.search(pattern, all_text, flags=re.IGNORECASE) is None, f"Found {label}")

    for number in range(1, 33):
        fail(
            errors,
            any(entry.startswith(f"[{number}]") for entry in bibliography),
            f"Reference [{number}] is missing",
        )

    render_result: dict[str, object] | None = None
    if render and not errors:
        try:
            render_result = render_check(docx, render_dir)
        except Exception as exc:  # noqa: BLE001 - fail-loud validation boundary
            errors.append(str(exc))

    report: dict[str, object] = {
        "status": "PASS" if not errors else "FAIL",
        "path": str(docx),
        "size_bytes": docx.stat().st_size,
        "counts": {
            "heading1": len(heading1),
            "heading2": len(heading2),
            "figures": drawings,
            "figure_captions": len(figure_captions),
            "tables": tables,
            "table_captions": len(table_captions),
            "display_equations": equations,
            "code_listings": len(by_style.get("SourceCode", [])),
            "definition_terms": len(by_style.get("DefinitionTerm", [])),
            "bibliography_entries": len(bibliography),
            "sections": len(sections),
        },
        "metadata": core_values,
        "render": render_result,
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", nargs="?", type=Path, default=DEFAULT_DOCX)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--render-dir", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = validate(args.docx.resolve(), args.render, args.render_dir)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

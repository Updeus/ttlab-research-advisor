from __future__ import annotations

from pathlib import Path

import httpx

from app.evaluation.external_sanity import PINNED_DOCUMENTS, acquire, parse_open_article


def _xml(pmcid: str, title: str, topic: str) -> bytes:
    numeric = pmcid.removeprefix("PMC")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta>
    <article-id pub-id-type="pmc">{numeric}</article-id>
    <article-id pub-id-type="doi">10.0000/{numeric}</article-id>
    <title-group><article-title>{title}</article-title></title-group>
    <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/">
      <license-p>Creative Commons Attribution 4.0 International License.</license-p>
    </license></permissions>
  </article-meta></front>
  <body><sec><title>Introduction</title><p>{topic} {topic} {topic}.</p></sec></body>
</article>""".encode()


def test_parser_requires_pinned_identity_and_cc_by() -> None:
    expected = PINNED_DOCUMENTS[0]
    parsed = parse_open_article(
        _xml(expected["pmcid"], f"A study using {expected['expected_title_fragment']}", expected["query"]),
        expected,
    )
    assert parsed["pmcid"] == expected["pmcid"]
    assert parsed["license"] == "CC BY"
    assert parsed["chunk_count"] == 1
    assert parsed["xml_sha256"]


def test_acquisition_writes_public_manifest_but_separates_raw_xml(tmp_path: Path) -> None:
    payloads = {
        row["pmcid"]: _xml(row["pmcid"], f"Study: {row['expected_title_fragment']}", row["query"])
        for row in PINNED_DOCUMENTS
    }

    def handler(request: httpx.Request) -> httpx.Response:
        pmcid = request.url.path.split("/")[-2]
        return httpx.Response(200, content=payloads[pmcid], headers={"content-type": "application/xml"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = acquire(tmp_path, client=client)

    assert result["status"] == "complete"
    assert len(result["documents"]) == 3
    assert result["sanity_check"]["top_1_matches"] == 3
    assert result["redistribution"]["raw_xml_in_release"] is False
    assert (tmp_path / "external_sanity_manifest.json").is_file()
    assert len(list((tmp_path / "raw").glob("*.xml"))) == 3

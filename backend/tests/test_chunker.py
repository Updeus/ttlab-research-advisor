from app.indexing.chunker import build_chunks_from_extraction


def make_extracted_fixture() -> dict[str, object]:
    page_one = "Introduction. " + " ".join(
        f"Sentence {index} explains the research platform with enough words for chunking."
        for index in range(90)
    )
    page_two = "Methodology. " + " ".join(
        f"Sentence {index} describes deterministic extraction and chunk creation for source citation."
        for index in range(90, 180)
    )
    return {
        "paper_id": "chunk-paper",
        "pages": [
            {"page_number": 1, "text": page_one},
            {"page_number": 2, "text": page_two},
        ],
    }


def test_chunker_creates_page_aware_chunks() -> None:
    chunks = build_chunks_from_extraction(make_extracted_fixture(), target_words=140, overlap_words=30)

    assert len(chunks) > 1
    assert chunks[0]["page_start"] == 1
    assert chunks[-1]["page_end"] == 2
    assert all(chunk["paper_id"] == "chunk-paper" for chunk in chunks)


def test_chunker_preserves_overlap_and_stable_ids() -> None:
    extracted = make_extracted_fixture()
    chunks = build_chunks_from_extraction(extracted, target_words=140, overlap_words=30)
    repeated = build_chunks_from_extraction(extracted, target_words=140, overlap_words=30)
    first_words = set(chunks[0]["text"].split())
    second_words = set(chunks[1]["text"].split())

    assert first_words.intersection(second_words)
    assert [chunk["chunk_id"] for chunk in chunks] == [chunk["chunk_id"] for chunk in repeated]

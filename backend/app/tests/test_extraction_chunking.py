"""Text extraction (PDF, DOCX, Markdown, TXT) and chunking."""

import pytest

from app.rag.chunking import chunk_blocks, split_text
from app.rag.extraction import ExtractionError, TextBlock, clean_text, extract_bytes
from app.tests.factories import make_docx, make_encrypted_pdf, make_pdf

# --------------------------------------------------------------------------- extraction


def test_pdf_text_keeps_page_numbers():
    pdf = make_pdf(["Refunds take 5-7 business days.", "Shipping is free over $50."])

    document = extract_bytes(pdf, ".pdf")

    assert document.page_count == 2
    assert [(b.page_number, b.text) for b in document.blocks] == [
        (1, "Refunds take 5-7 business days."),
        (2, "Shipping is free over $50."),
    ]


def test_pdf_pages_without_text_are_skipped_but_counted():
    document = extract_bytes(make_pdf(["First page", "", "Third page"]), ".pdf")

    assert document.page_count == 3
    assert [b.page_number for b in document.blocks] == [1, 3]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (make_pdf([""]), "Scanned PDFs"),
        (make_encrypted_pdf(["secret"]), "password-protected"),
        (b"%PDF-1.4 this is not really a pdf", "damaged"),
    ],
)
def test_unusable_pdfs_raise_readable_errors(data, message):
    with pytest.raises(ExtractionError, match=message):
        extract_bytes(data, ".pdf")


def test_docx_headings_become_sections_and_tables_are_kept():
    data = make_docx(
        [
            ("h1", "Returns"),
            ("p", "Items can be returned within 30 days."),
            ("h2", "Damaged items"),
            ("p", "Report damage within 48 hours."),
            ("table", "Plan|Price;Basic|$9"),
            ("h1", "Shipping"),
            ("p", "We ship worldwide."),
        ]
    )

    blocks = extract_bytes(data, ".docx").blocks

    assert [b.section for b in blocks] == ["Returns", "Returns > Damaged items", "Shipping"]
    assert "Report damage within 48 hours." in blocks[1].text
    assert "Basic | $9" in blocks[1].text
    assert blocks[2].text.startswith("Shipping")  # heading text stays searchable


def test_markdown_sections_follow_heading_levels_and_ignore_code_fences():
    data = (
        b"# Shipping\nWe ship worldwide.\n## Costs\nStandard shipping is $5.\n"
        b"```\n# not a heading\n```\n# Returns\nWithin 30 days.\n"
    )

    blocks = extract_bytes(data, ".md").blocks

    assert [b.section for b in blocks] == ["Shipping", "Shipping > Costs", "Returns"]
    assert "# not a heading" in blocks[1].text


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("Café prices".encode("utf-8"), "Café prices"),
        ("Café prices".encode("utf-8-sig"), "Café prices"),
        ("Café prices".encode("cp1252"), "Café prices"),
    ],
)
def test_text_files_are_decoded_with_fallbacks(data, expected):
    assert extract_bytes(data, ".txt").blocks[0].text == expected


def test_clean_text_removes_control_characters_and_extra_blank_lines():
    assert clean_text("a\x00b\r\n\r\n\r\n\r\nc  \n") == "ab\n\nc"


def test_unsupported_extension_is_rejected():
    with pytest.raises(ExtractionError, match="Unsupported"):
        extract_bytes(b"data", ".exe")


# --------------------------------------------------------------------------- chunking


def test_chunks_respect_size_and_overlap():
    text = " ".join(f"Sentence number {i} is here." for i in range(200))

    spans = split_text(text, chunk_size=300, overlap=60)

    assert all(end - start <= 300 for start, end in spans)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    for (_, previous_end), (next_start, _) in zip(spans, spans[1:], strict=False):
        assert next_start < previous_end  # consecutive chunks overlap
        assert previous_end - next_start <= 60


def test_chunks_prefer_sentence_boundaries():
    text = " ".join(f"Sentence number {i} is here." for i in range(200))

    chunks = chunk_blocks([TextBlock(text=text)], chunk_size=300, overlap=60)

    assert all(c.content.endswith(".") for c in chunks)
    assert all(c.content.startswith("Sentence") for c in chunks)


def test_chunk_offsets_point_back_into_the_text():
    text = "Alpha paragraph one.\n\nBeta paragraph two is a little longer than the first one."

    chunks = chunk_blocks([TextBlock(text=text)], chunk_size=40, overlap=10)

    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.content


def test_chunks_never_span_pages_and_keep_their_location():
    blocks = [
        TextBlock(text="Page one text about refunds and returns policy.", page_number=1, section="Refunds"),
        TextBlock(text="Page two text about shipping times and costs.", page_number=2, section="Shipping"),
    ]

    chunks = chunk_blocks(blocks, chunk_size=500, overlap=50)

    assert [(c.page_number, c.section) for c in chunks] == [(1, "Refunds"), (2, "Shipping")]


def test_tiny_heading_only_blocks_are_merged_into_the_next_block():
    blocks = [
        TextBlock(text="Policies", section="Policies"),
        TextBlock(text="Refunds are issued within 7 business days of approval.", section="Policies > Refunds"),
    ]

    chunks = chunk_blocks(blocks, chunk_size=500, overlap=50)

    assert len(chunks) == 1
    assert chunks[0].content.startswith("Policies\nRefunds are issued")


def test_short_pages_are_not_merged_into_the_next_page():
    # Regression: a short page 1 used to be folded into page 2, so its citation was wrong.
    blocks = [TextBlock(text="Short page.", page_number=1), TextBlock(text="Page two.", page_number=2)]

    chunks = chunk_blocks(blocks, chunk_size=500, overlap=50)

    assert [(c.page_number, c.content) for c in chunks] == [(1, "Short page."), (2, "Page two.")]


def test_a_single_huge_word_is_hard_cut_instead_of_looping_forever():
    spans = split_text("x" * 1000, chunk_size=300, overlap=50)

    assert spans[-1][1] == 1000
    assert all(end - start <= 300 for start, end in spans)


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        split_text("text", chunk_size=100, overlap=100)

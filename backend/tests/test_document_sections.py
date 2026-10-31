"""T-9.4: splitting a document into the pieces that become graph nodes.

The point of splitting is citability: "this came from the PRD" is useless as
evidence, "this came from the PRD's Scope section" is not. So what is pinned
here is that author-chosen boundaries are kept, that no section is unusably
large, and that positions stay contiguous -- they are part of each section's
graph id, so a gap would make a re-upload disagree with the first upload.
"""

import pytest

from app.uploads.sections import (
    MAX_SECTION_CHARS,
    MAX_SECTIONS,
    TARGET_SECTION_CHARS,
    split_into_sections,
)


def paragraph(label: str, words: int = 40) -> str:
    return f"{label} " + " ".join(["word"] * words)


# -- Headings ------------------------------------------------------------------


def test_markdown_headings_become_section_boundaries():
    text = "# Overview\n\nWhat Cortex is.\n\n## Scope\n\nIngestion only.\n"

    sections = split_into_sections(text)

    assert [section.heading for section in sections] == ["Overview", "Scope"]
    assert sections[0].body == "What Cortex is."
    assert sections[1].body == "Ingestion only."


def test_every_markdown_level_is_a_heading():
    text = "# One\n\na\n\n###### Six\n\nb\n"

    assert [s.heading for s in split_into_sections(text)] == ["One", "Six"]


def test_a_numbered_heading_survives_losing_its_styling():
    """Word and PDF exports drop heading styles, leaving only the shape."""
    text = "1. Scope\n\nIn scope: ingestion.\n\n2. Non-goals\n\nNo billing.\n"

    sections = split_into_sections(text)

    assert [section.heading for section in sections] == ["1. Scope", "2. Non-goals"]


def test_a_title_cased_standalone_line_is_a_heading():
    text = "Acceptance Criteria\n\nThe upload must be rejected with a reason.\n"

    (section,) = split_into_sections(text)

    assert section.heading == "Acceptance Criteria"


def test_a_sentence_without_a_full_stop_is_not_a_heading():
    """A false positive orphans the paragraph it belonged to, so the test is
    conservative on purpose."""
    text = (
        "we decided to use postgres for the relational half of the system and "
        "neo4j for the graph half\n\nMore detail follows.\n"
    )

    sections = split_into_sections(text)

    assert all(section.heading is None for section in sections)


def test_a_trailing_line_with_nothing_under_it_is_not_a_heading():
    text = "Some content here.\n\nFinal Thoughts\n"

    sections = split_into_sections(text)

    assert all(section.heading is None for section in sections)


def test_a_heading_with_no_body_is_kept():
    """It is part of the document's shape, and dropping it would lose a
    boundary the author chose."""
    text = "# Appendix\n"

    (section,) = split_into_sections(text)

    assert (section.heading, section.body) == ("Appendix", "")


# -- Packing -------------------------------------------------------------------


def test_a_document_with_no_headings_packs_paragraphs_together():
    text = "\n\n".join(paragraph(f"P{index}") for index in range(8))

    sections = split_into_sections(text)

    assert len(sections) > 1
    assert all(section.heading is None for section in sections)
    # Packed rather than one node per paragraph.
    assert len(sections) < 8


def test_no_section_exceeds_the_hard_ceiling():
    text = "\n\n".join(paragraph(f"P{index}", 300) for index in range(6))

    for section in split_into_sections(text):
        assert len(section.body) <= MAX_SECTION_CHARS


def test_an_oversized_paragraph_is_split_on_sentences():
    sentence = "This is a complete sentence about ingestion. "
    text = sentence * 200

    sections = split_into_sections(text)

    assert len(sections) > 1
    # Split between sentences, so no section starts mid-sentence.
    assert all(
        section.body.startswith("This is") for section in sections
    )


def test_a_wall_of_text_with_no_sentences_is_still_split():
    """A node that cannot be rendered is worse than an inelegant break."""
    text = "x" * (MAX_SECTION_CHARS * 3)

    sections = split_into_sections(text)

    assert len(sections) > 1
    for section in sections:
        assert len(section.body) <= MAX_SECTION_CHARS


def test_a_stray_short_line_is_folded_into_its_neighbour():
    text = paragraph("Main", 200) + "\n\nok\n"

    sections = split_into_sections(text)

    assert len(sections) == 1
    assert sections[0].body.endswith("ok")


def test_a_short_section_with_its_own_heading_is_not_folded_away():
    text = "# Decision\n\nUse Postgres.\n\n# Owner\n\nAryan.\n"

    sections = split_into_sections(text)

    assert [section.heading for section in sections] == ["Decision", "Owner"]


# -- Shape ---------------------------------------------------------------------


def test_positions_are_contiguous_from_zero():
    text = "\n\n".join(f"# H{index}\n\nBody {index}." for index in range(5))

    sections = split_into_sections(text)

    assert [section.position for section in sections] == [0, 1, 2, 3, 4]


def test_the_section_count_is_capped():
    text = "\n\n".join(f"# H{index}\n\nBody." for index in range(MAX_SECTIONS + 50))

    sections = split_into_sections(text)

    assert len(sections) == MAX_SECTIONS
    assert sections[-1].position == MAX_SECTIONS - 1


def test_a_titled_section_uses_its_heading():
    (section,) = split_into_sections("# Scope\n\nIngestion only.\n")

    assert section.title == "Scope"


def test_an_untitled_section_uses_its_opening_words():
    (section,) = split_into_sections("We decided to index pull requests first.")

    assert section.title == "We decided to index pull requests first."


def test_a_long_untitled_section_has_a_shortened_title():
    (section,) = split_into_sections(paragraph("Opening", 100))

    assert len(section.title) <= 80


def test_an_empty_section_still_has_a_title():
    """A node with a blank label is unusable on the canvas."""
    (section,) = split_into_sections("# Appendix\n")

    assert section.title == "Appendix"


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
def test_nothing_in_nothing_out(text):
    assert split_into_sections(text) == []


def test_a_single_short_document_is_one_section():
    sections = split_into_sections("Decision: use Postgres.")

    assert len(sections) == 1
    assert sections[0].body == "Decision: use Postgres."


def test_sections_stay_within_the_target_where_they_can():
    text = "\n\n".join(paragraph(f"P{index}", 30) for index in range(20))

    sections = split_into_sections(text)

    # Packing stops before the target, so only an unsplittable paragraph can
    # push a section past it.
    assert all(len(section.body) <= MAX_SECTION_CHARS for section in sections)
    assert any(len(section.body) >= TARGET_SECTION_CHARS / 2 for section in sections)

"""T-9.4: splitting an extracted document into the pieces that become nodes.

A PRD uploaded whole would be one enormous node: impossible to lay out, and
useless as evidence, because "this decision came from the PRD" says nothing
about *where*. So a document becomes one `Document` node and many
`DocumentSection` nodes, each small enough to cite.

Two strategies, in order of preference:

1. **Headings.** A Markdown heading (`## Scope`) or a short standalone line in
   title case is a boundary the author already decided on, so it is used as one
   and its text becomes the section's heading.
2. **Paragraph packing.** With no headings -- a plain PDF export, most Word
   documents -- paragraphs are accumulated until adding the next would exceed
   `TARGET_SECTION_CHARS`. Splitting mid-paragraph is avoided because a sentence
   cut in half is worse evidence than a slightly oversized section.

A single paragraph longer than `MAX_SECTION_CHARS` is split on sentence
boundaries as a last resort; one that has none is split on length, because a
node that cannot be rendered is worse than an inelegant break.
"""

import re
from dataclasses import dataclass

#: What a section aims to be. Roughly a long paragraph or two: big enough to
#: carry an argument, small enough to read inside the inspector panel.
TARGET_SECTION_CHARS = 1_200
#: Hard ceiling before a paragraph is broken up.
MAX_SECTION_CHARS = 2_400
#: Below this a "section" is a stray line, so it is folded into its neighbour.
MIN_SECTION_CHARS = 40
#: A guard on one request, like the upload size limit.
MAX_SECTIONS = 500

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(?P<text>\S.*)$")
#: A standalone short line with no sentence-ending punctuation, e.g. "3. Scope"
#: or "Non-goals". Word and PDF exports lose heading styling, so this is the
#: only signal left.
_PLAIN_HEADING = re.compile(r"^(?P<text>[^\n]{1,80})$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class DocumentSection:
    position: int
    heading: str | None
    body: str

    @property
    def title(self) -> str:
        """What the canvas labels the node. The heading when there is one, the
        opening words otherwise -- never an empty string."""
        if self.heading:
            return self.heading
        opening = " ".join(self.body.split())[:80].strip()
        return opening or f"Section {self.position + 1}"


def _looks_like_heading(line: str, following: list[str]) -> bool:
    """A standalone line that introduces what comes after it.

    Conservative on purpose: a false positive turns a sentence into a heading
    and orphans the paragraph it belonged to. So it must be short, unpunctuated
    at the end, and actually followed by something.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if not _PLAIN_HEADING.match(stripped):
        return False
    if stripped[-1] in ".,;:!?":
        return False
    # A line of prose that merely lacks a full stop is not a heading; a heading
    # has something under it.
    if not any(item.strip() for item in following):
        return False
    words = stripped.split()
    if len(words) > 12:
        return False
    # Numbered or title-cased, which is what headings in a PRD look like once
    # the styling is gone.
    numbered = bool(re.match(r"^(\d+[.)]|[IVXLC]+\.)\s", stripped))
    capitalised = sum(word[:1].isupper() for word in words) >= max(1, len(words) // 2)
    return numbered or capitalised


def _paragraphs(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip():
            current.append(line.strip())
            continue
        if current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def _split_long(body: str) -> list[str]:
    """Break an oversized paragraph, preferring sentence boundaries."""
    if len(body) <= MAX_SECTION_CHARS:
        return [body]

    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(body):
        if current and len(current) + len(sentence) + 1 > TARGET_SECTION_CHARS:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current.strip())

    # No sentence boundaries to use -- a wall of text, or a table dumped as one
    # line. A node that cannot be rendered is worse than an inelegant break.
    final: list[str] = []
    for piece in pieces:
        while len(piece) > MAX_SECTION_CHARS:
            final.append(piece[:TARGET_SECTION_CHARS])
            piece = piece[TARGET_SECTION_CHARS:]
        if piece:
            final.append(piece)
    return final


def split_into_sections(text: str) -> list[DocumentSection]:
    """Ordered sections of ``text``. Never empty for a non-empty document."""
    lines = text.split("\n")
    groups: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    body: list[str] = []
    saw_heading = False

    for index, line in enumerate(lines):
        markdown = _MARKDOWN_HEADING.match(line.strip())
        following = lines[index + 1 : index + 6]
        if markdown or _looks_like_heading(line, following):
            if heading is not None or any(item.strip() for item in body):
                groups.append((heading, body))
            heading = (
                markdown.group("text").strip() if markdown else line.strip()
            )
            body = []
            saw_heading = True
            continue
        body.append(line)

    if heading is not None or any(item.strip() for item in body):
        groups.append((heading, body))

    sections: list[DocumentSection] = []
    for group_heading, group_lines in groups:
        joined = "\n".join(group_lines).strip()
        if not saw_heading:
            # No headings anywhere: pack paragraphs instead of emitting one
            # node per blank-line-separated block.
            for packed in _pack(_paragraphs(joined)):
                sections.append(
                    DocumentSection(len(sections), None, packed)
                )
            continue
        if not joined:
            # A heading with nothing under it is still a real part of the
            # document's shape, so it is kept rather than dropped.
            sections.append(DocumentSection(len(sections), group_heading, ""))
            continue
        # An oversized group becomes several sections under the one heading;
        # each still cites the heading it came from.
        for piece in _split_long(joined):
            sections.append(
                DocumentSection(len(sections), group_heading, piece)
            )

    sections = _merge_tiny(sections)
    return _renumber(sections[:MAX_SECTIONS])


def _pack(paragraphs: list[str]) -> list[str]:
    packed: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in _split_long(paragraph):
            if current and len(current) + len(piece) + 2 > TARGET_SECTION_CHARS:
                packed.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}".strip()
    if current:
        packed.append(current)
    return packed


def _merge_tiny(sections: list[DocumentSection]) -> list[DocumentSection]:
    """Fold a stray short section into the one before it.

    Only when it has no heading of its own: a heading is a boundary the author
    chose, and collapsing it would lose the structure the split exists to keep.
    """
    merged: list[DocumentSection] = []
    for section in sections:
        if (
            merged
            and section.heading is None
            and len(section.body) < MIN_SECTION_CHARS
            and len(merged[-1].body) + len(section.body) <= MAX_SECTION_CHARS
        ):
            previous = merged.pop()
            merged.append(
                DocumentSection(
                    previous.position,
                    previous.heading,
                    f"{previous.body}\n\n{section.body}".strip(),
                )
            )
            continue
        merged.append(section)
    return merged


def _renumber(sections: list[DocumentSection]) -> list[DocumentSection]:
    """Positions must be contiguous: they are part of each section's graph id,
    so a gap would leave the ids of a re-upload disagreeing with the first."""
    return [
        DocumentSection(position, section.heading, section.body)
        for position, section in enumerate(sections)
    ]

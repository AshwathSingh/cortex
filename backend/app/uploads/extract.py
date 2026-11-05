"""T-9.3: pulling readable text out of an uploaded document.

Three formats, one answer: a plain string, or a typed refusal naming what the
reader will be told. The acceptance criteria are explicit that a rejection has
to say *why* and leave the graph untouched, so every failure here happens before
anything is written -- extraction runs on bytes in memory and touches no
database.

The refusals are deliberately separate types rather than one error with a
message, because they map to different HTTP statuses: a file Cortex will never
accept is a 415, one that is too big is a 413, and one that is the right type
but unreadable is a 422. A single error class would force the endpoint to parse
its own message to decide.

What this does *not* do is OCR. A scanned PDF is a picture of text as far as
pypdf is concerned, so it extracts nothing and is reported as unreadable rather
than silently ingested as an empty document.
"""

import io
from dataclasses import dataclass

#: Extensions accepted, mapped to the reader used. Checked on the filename
#: rather than the browser's content type: the latter is client-supplied and
#: routinely wrong (``application/octet-stream`` for a .docx is common).
PDF_SUFFIXES = (".pdf",)
WORD_SUFFIXES = (".docx",)
TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".text")
SUPPORTED_SUFFIXES = PDF_SUFFIXES + WORD_SUFFIXES + TEXT_SUFFIXES

#: 10 MB. Extraction holds the whole file and its text in memory, and the
#: request is synchronous, so this is a ceiling on one request's cost rather
#: than a product limit.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: Below this, the file parsed but yielded nothing worth indexing -- an empty
#: document, or a scanned PDF with no text layer.
MIN_TEXT_LENGTH = 1


class DocumentRejected(Exception):
    """Base for every reason a document is not ingested."""


class UnsupportedDocument(DocumentRejected):
    """Not a format Cortex can read. Naming the accepted ones is the whole
    point of the message, so the reader does not have to guess."""

    def __init__(self, filename: str):
        super().__init__(
            f"{filename} is not a supported file type. "
            f"Upload a PDF, a Word document (.docx), or a text file "
            f"({', '.join(TEXT_SUFFIXES)})."
        )


class DocumentTooLarge(DocumentRejected):
    def __init__(self, filename: str, size: int):
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        super().__init__(
            f"{filename} is {size / (1024 * 1024):.1f} MB, over the {limit_mb} MB limit."
        )


class UnreadableDocument(DocumentRejected):
    """The right type, but nothing could be read from it."""


@dataclass(frozen=True)
class ExtractedDocument:
    filename: str
    text: str
    #: Which reader handled it: "pdf", "word" or "text". Stored on the graph
    #: node so the UI can say what a document came from.
    format: str


def suffix_of(filename: str) -> str:
    """The lowercased extension, or "" when there is none.

    ``rpartition`` returns the whole string as the tail when the separator is
    absent, so the separator itself is what has to be tested.
    """
    _, separator, suffix = filename.rpartition(".")
    return f".{suffix.lower()}" if separator and suffix else ""


def is_supported(filename: str) -> bool:
    return suffix_of(filename) in SUPPORTED_SUFFIXES


def extract_document(filename: str, data: bytes) -> ExtractedDocument:
    """The readable text of ``data``, or a ``DocumentRejected`` saying why not.

    Order matters: type and size are checked before the file is parsed, so an
    enormous or unsupported upload is refused without handing it to a parser.
    """
    suffix = suffix_of(filename)
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(filename)
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentTooLarge(filename, len(data))
    if not data:
        raise UnreadableDocument(f"{filename} is empty.")

    if suffix in PDF_SUFFIXES:
        text, document_format = _read_pdf(filename, data), "pdf"
    elif suffix in WORD_SUFFIXES:
        text, document_format = _read_word(filename, data), "word"
    else:
        text, document_format = _read_text(filename, data), "text"

    text = _normalise(text)
    if len(text) < MIN_TEXT_LENGTH:
        raise UnreadableDocument(
            f"No text could be read from {filename}. "
            "A scanned PDF has no text layer, so it needs to be run through OCR first."
        )
    return ExtractedDocument(filename=filename, text=text, format=document_format)


def _read_pdf(filename: str, data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # An empty-password decrypt covers the common "protected but not
            # really" case; anything else needs a password we do not have.
            try:
                reader.decrypt("")
            except Exception as error:
                raise UnreadableDocument(
                    f"{filename} is password-protected."
                ) from error
        pages = [page.extract_text() or "" for page in reader.pages]
    except UnreadableDocument:
        raise
    except (PyPdfError, ValueError, OSError, KeyError) as error:
        raise UnreadableDocument(
            f"{filename} could not be read as a PDF. It may be corrupt."
        ) from error
    # Blank line between pages: it is a real boundary, and the sectioner treats
    # it as one.
    return "\n\n".join(page.strip() for page in pages if page.strip())


def _read_word(filename: str, data: bytes) -> str:
    import zipfile

    import docx
    from docx.opc.exceptions import OpcError

    try:
        document = docx.Document(io.BytesIO(data))
    # BadZipFile is a ValueError on some Pythons and not on others, so it is
    # named explicitly: a legacy binary .doc renamed to .docx lands here.
    except (OpcError, zipfile.BadZipFile, KeyError, ValueError, OSError) as error:
        # The usual cause is a legacy .doc renamed to .docx: python-docx reads
        # the OPC package, and a binary .doc has none.
        raise UnreadableDocument(
            f"{filename} could not be read as a Word document. "
            "Only .docx is supported -- an older .doc has to be saved as .docx first."
        ) from error

    blocks = [paragraph.text.strip() for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return "\n".join(block for block in blocks if block)


def _read_text(filename: str, data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnreadableDocument(
        f"{filename} is not readable as text. Save it as UTF-8 and try again."
    )


def _normalise(text: str) -> str:
    """Collapse the whitespace the readers leave behind.

    PDF extraction in particular emits runs of blank lines and trailing spaces,
    which would otherwise turn into empty sections.
    """
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    blank = 0
    for line in lines:
        if line:
            blank = 0
            cleaned.append(line)
            continue
        blank += 1
        # One blank line is a paragraph break and is kept; more is noise.
        if blank == 1:
            cleaned.append("")
    return "\n".join(cleaned).strip()

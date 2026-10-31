"""T-9.4: writing an uploaded document and its sections into the graph.

Nodes:  (:Document {id, workspace_id}), (:DocumentSection {id, workspace_id})
Edges:  (:DocumentSection)-[:SECTION_OF]->(:Document)

Identity is the **filename**, not the file's bytes, and that choice is what
makes the acceptance criteria work:

* Re-uploading an identical copy MERGEs onto the same ids, so the existing
  nodes are updated and no second copy appears (AC4).
* Re-uploading an *edited* file under the same name replaces its sections
  rather than accumulating two versions of the same document -- which is why
  ``DELETE_TRAILING_SECTIONS`` exists. Without it, shortening a document would
  leave the sections past its new end behind as nodes nothing points at.

``content_hash`` is still stored, as the honest answer to "is this the same file
we read last time", but it is a property rather than a key: keyed on content, an
edited PRD would become a second source on the Sources page and the first would
never go away.

Ids are prefixed -- ``upload/<16 hex>`` -- for the same reason chat ids are:
``Author``-style integer ids and string ids share one graph, and
``app.graph.queries`` recovers the type by trying ``int()`` first, which only
works because a prefixed id can never parse as a number.
"""

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from neo4j import Driver

from app.github.mapper import normalise_workspace_id
from app.uploads.sections import DocumentSection

Statement = tuple[str, dict[str, Any]]

#: ``DataSource.kind`` for an uploaded file.
UPLOAD_KIND = "upload"

#: 16 hex characters of SHA-256. Enough that two filenames in one workspace will
#: not collide, short enough to read in a node key.
_ID_LENGTH = 16


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def document_id(filename: str) -> str:
    """The graph id for a filename, stable across re-uploads.

    Case-folded: "PRD.pdf" and "prd.pdf" are the same document to a reader, and
    treating them as two would defeat AC4 on any case-insensitive filesystem.
    """
    digest = hashlib.sha256(filename.strip().lower().encode("utf-8")).hexdigest()
    return f"{UPLOAD_KIND}/{digest[:_ID_LENGTH]}"


def section_id(document: str, position: int) -> str:
    return f"{document}/{position}"


@dataclass(frozen=True)
class UploadedDocument:
    """One document, ready to write."""

    filename: str
    document_format: str
    content_hash: str
    sections: list[DocumentSection]
    uploaded_at: str

    @property
    def node_id(self) -> str:
        return document_id(self.filename)


UPSERT_DOCUMENT = """
MERGE (d:Document {id: $id, workspace_id: $workspace_id})
SET d += $props
"""

UPSERT_SECTIONS = """
UNWIND $rows AS row
MERGE (s:DocumentSection {id: row.id, workspace_id: $workspace_id})
SET s += row.props
WITH s, row
MATCH (d:Document {id: row.document_id, workspace_id: $workspace_id})
MERGE (s)-[:SECTION_OF]->(d)
"""

# An edited upload may be shorter than the one before it. Its sections are
# keyed by position, so the tail of the previous version would otherwise survive
# as nodes describing text the document no longer contains.
DELETE_TRAILING_SECTIONS = """
MATCH (s:DocumentSection {workspace_id: $workspace_id})
WHERE s.document_id = $document_id AND s.position >= $section_count
DETACH DELETE s
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_statements(
    document: UploadedDocument, *, workspace_id: str | uuid.UUID
) -> list[Statement]:
    """Ordered (cypher, params) pairs: document, then sections, then the prune.

    The document comes first so the ``SECTION_OF`` MATCH has something to bind
    to, and the prune comes last so it only ever removes sections this upload
    did not write.
    """
    workspace = normalise_workspace_id(workspace_id)
    node = document.node_id

    props = {
        "id": node,
        "workspace_id": workspace,
        "filename": document.filename,
        "format": document.document_format,
        "content_hash": document.content_hash,
        "section_count": len(document.sections),
        "uploaded_at": document.uploaded_at,
        "kind": UPLOAD_KIND,
        "source_ref": document.filename,
    }

    rows = [
        {
            "id": section_id(node, section.position),
            "document_id": node,
            "props": {
                "id": section_id(node, section.position),
                "workspace_id": workspace,
                "document_id": node,
                "filename": document.filename,
                "position": section.position,
                "heading": section.heading,
                "title": section.title,
                "body": section.body,
                "kind": UPLOAD_KIND,
                "source_ref": document.filename,
            },
        }
        for section in document.sections
    ]

    statements: list[Statement] = [
        (UPSERT_DOCUMENT, {"id": node, "workspace_id": workspace, "props": props})
    ]
    if rows:
        statements.append(
            (UPSERT_SECTIONS, {"rows": rows, "workspace_id": workspace})
        )
    statements.append(
        (
            DELETE_TRAILING_SECTIONS,
            {
                "workspace_id": workspace,
                "document_id": node,
                "section_count": len(document.sections),
            },
        )
    )
    return statements


def write_document(
    driver: Driver, document: UploadedDocument, *, workspace_id: str | uuid.UUID
) -> int:
    """Write the document in one transaction. Returns statements run.

    All-or-nothing: a half-written document would leave sections pointing at a
    document node that does not exist, or a document claiming a section count it
    does not have.
    """
    statements = build_statements(document, workspace_id=workspace_id)

    def work(tx):
        for cypher, params in statements:
            tx.run(cypher, **params)

    with driver.session() as session:
        session.execute_write(work)
    return len(statements)


def prepare(
    filename: str,
    data: bytes,
    document_format: str,
    sections: Iterable[DocumentSection],
) -> UploadedDocument:
    return UploadedDocument(
        filename=filename,
        document_format=document_format,
        content_hash=content_hash(data),
        sections=list(sections),
        uploaded_at=now_iso(),
    )

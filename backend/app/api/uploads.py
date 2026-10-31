"""T-9.1: the endpoint that accepts an uploaded document.

    POST /api/workspaces/{workspace_id}/uploads   (multipart/form-data, "file")

The pipeline is deliberately the same shape as US-7's ingestion, because the
Sources page cannot tell the difference and should not have to: authorise the
workspace, record the attempt, read the thing, write the graph, record the
outcome. The difference is that there is no network call -- the bytes arrive
with the request -- so this is fast enough to stay synchronous without the
"Syncing…" window mattering.

Authorisation is ``sources.write``: uploading writes nodes, so a VIEWER (or any
custom role without it) may not. That runs before the file is read, so an
unauthorised caller cannot make the server parse a 10 MB PDF.

Every rejection maps to its own status, and nothing is written to the graph on
any of them (US-09 AC2):

    415  not a PDF, .docx or text file
    413  over the size limit
    422  the right type but unreadable -- corrupt, encrypted, or a scan with no
         text layer

A rejection before the file is identified records no sync row, for the same
reason US-7 records nothing for an unparseable URL: no real source was named.
Once the filename is known, a failure *is* recorded, because that row is then
the only evidence the upload was attempted.
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.db.neo4j_driver import get_driver
from app.models import DataSource
from app.permissions import Permission
from app.services.data_sources import (
    SyncInProgress,
    record_sync_attempt,
    record_sync_failure,
    record_sync_success,
)
from app.uploads.extract import (
    DocumentTooLarge,
    MAX_UPLOAD_BYTES,
    UnreadableDocument,
    UnsupportedDocument,
    extract_document,
)
from app.uploads.graph import UPLOAD_KIND, prepare, write_document
from app.uploads.sections import split_into_sections

router = APIRouter(prefix="/api/workspaces", tags=["uploads"])

REJECTION_STATUS = {
    UnsupportedDocument: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    DocumentTooLarge: status.HTTP_413_CONTENT_TOO_LARGE,
    UnreadableDocument: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


class UploadResponse(BaseModel):
    filename: str
    #: The file's format as Cortex read it: "pdf", "word" or "text".
    format: str
    sections: int
    #: True when this filename was already in the workspace, so the reader is
    #: told their re-upload replaced it rather than added a second copy (AC4).
    replaced: bool


def get_neo4j() -> Driver:
    """Injectable so tests can supply a fake driver (same shape as app.api.ingest)."""
    return get_driver()


def _safe_filename(raw: str | None) -> str:
    """The upload's name, with any path the browser sent stripped off.

    A filename is used as the source's key and shown on the Sources page, so a
    caller-supplied ``../`` must not survive into either. Nothing is written to
    disk, so this is about identity and display rather than path traversal.
    """
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:255]


@router.post(
    "/{workspace_id}/uploads",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: UploadFile = File(...),
    driver: Driver = Depends(get_neo4j),
) -> UploadResponse:
    load_workspace_for_user(
        session, user, workspace_id, permission=Permission.SOURCES_WRITE
    )

    filename = _safe_filename(file.filename)
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The upload has no filename.",
        )

    # Read with a ceiling rather than trusting Content-Length, which is
    # client-supplied: one byte over is enough to know it is too big, and
    # stopping there bounds what an unauthorised-but-authenticated caller can
    # make the server hold in memory.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise _rejected(
            session, workspace_id, filename, DocumentTooLarge(filename, len(data))
        )

    existing = _already_uploaded(session, workspace_id, filename)
    try:
        record_sync_attempt(
            session,
            workspace_id=workspace_id,
            external_ref=filename,
            kind=UPLOAD_KIND,
            display_name=filename,
        )
    except SyncInProgress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An upload of {filename} is already running",
        )
    session.commit()

    try:
        extracted = extract_document(filename, data)
    except tuple(REJECTION_STATUS) as rejection:
        raise _rejected(session, workspace_id, filename, rejection)

    sections = split_into_sections(extracted.text)
    document = prepare(filename, data, extracted.format, sections)

    try:
        write_document(driver, document, workspace_id=workspace_id)
    except (Neo4jError, DriverError):
        raise _rejected(
            session,
            workspace_id,
            filename,
            UnreadableDocument("Graph database unavailable"),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    record_sync_success(
        session,
        workspace_id=workspace_id,
        external_ref=filename,
        user_id=user.id,
        kind=UPLOAD_KIND,
    )
    session.commit()

    return UploadResponse(
        filename=filename,
        format=extracted.format,
        sections=len(sections),
        replaced=existing,
    )


def _already_uploaded(
    session: Session, workspace_id: uuid.UUID, filename: str
) -> bool:
    """Whether this workspace has seen this filename before.

    Read before the attempt is recorded, because recording it would create the
    very row this is looking for.
    """
    return (
        session.scalar(
            select(DataSource.id).where(
                DataSource.workspace_id == workspace_id,
                DataSource.kind == UPLOAD_KIND,
                DataSource.external_ref == filename,
            )
        )
        is not None
    )


def _rejected(
    session: Session,
    workspace_id: uuid.UUID,
    filename: str,
    rejection: Exception,
    *,
    status_code: int | None = None,
) -> HTTPException:
    """Record the failure, commit it, and return the error to raise.

    Committed before the response leaves the handler: the graph write is
    all-or-nothing, so a rejected upload leaves no nodes and this row is the
    only thing that can render a red "Needs attention" against the file.
    """
    detail = str(rejection)
    record_sync_failure(
        session,
        workspace_id=workspace_id,
        external_ref=filename,
        error=detail,
        kind=UPLOAD_KIND,
    )
    # The display name is set on the attempt, but a rejection can land before
    # one was recorded (an oversized file is refused on read).
    _set_display_name(session, workspace_id, filename)
    session.commit()
    resolved = status_code or REJECTION_STATUS.get(
        type(rejection), status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(status_code=resolved, detail=detail)


def _set_display_name(
    session: Session, workspace_id: uuid.UUID, filename: str
) -> None:
    source = session.scalar(
        select(DataSource).where(
            DataSource.workspace_id == workspace_id,
            DataSource.kind == UPLOAD_KIND,
            DataSource.external_ref == filename,
        )
    )
    if source is not None and source.display_name is None:
        source.display_name = filename

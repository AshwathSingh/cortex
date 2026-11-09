"""T-9.1 endpoint behaviour, and the US-09 acceptance criteria end to end.

The relational half is real (in-memory), so `get_current_user` and
`load_workspace_for_user` genuinely run; only Neo4j is faked. Each acceptance
criterion has a test named after what it promises.
"""

import io
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api.graph import get_neo4j as graph_neo4j
from app.api.uploads import get_neo4j as uploads_neo4j
from app.main import app
from app.models import DataSource, Role, SyncStatus, User
from app.uploads.extract import MAX_UPLOAD_BYTES
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID
from tests.test_document_extract import docx_bytes, pdf_bytes
from tests.test_ingest_api import FakeDriver
from tests.test_source_queries import SourceDriver

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/uploads"
ATTEMPTED_AT = datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc)
PRD = b"# Scope\n\nIngestion only.\n\n# Non-goals\n\nNo billing.\n"


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    for dependency in (uploads_neo4j, graph_neo4j):
        app.dependency_overrides.pop(dependency, None)


def setup(api_db, *, role=Role.OWNER, driver=None):
    client, sessions = api_db
    driver = driver or FakeDriver()
    app.dependency_overrides[uploads_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


def upload(client, filename="prd.md", data=PRD, url=URL):
    return client.post(url, files={"file": (filename, io.BytesIO(data))})


def sources(sessions) -> list[DataSource]:
    with sessions() as session:
        return list(session.scalars(select(DataSource).order_by(DataSource.external_ref)))


# -- AC1: an upload lands in the graph with no further configuration ----------


def test_a_text_file_is_indexed_with_no_configuration(api_db):
    client, driver = setup(api_db)

    response = upload(client)

    assert response.status_code == 201
    assert response.json() == {
        "filename": "prd.md",
        "format": "text",
        "sections": 2,
        "replaced": False,
    }
    # The document, its sections and the prune, in one transaction.
    assert driver.sessions == 1
    assert len(driver.tx.calls) == 3


def test_a_pdf_is_indexed(api_db):
    client, _ = setup(api_db)

    response = upload(client, "prd.pdf", pdf_bytes(["Scope", "Non-goals"]))

    assert response.status_code == 201
    assert response.json()["format"] == "pdf"
    assert response.json()["sections"] >= 1


def test_a_word_document_is_indexed(api_db):
    client, _ = setup(api_db)

    response = upload(
        client, "prd.docx", docx_bytes(["Scope", "Ingestion only."])
    )

    assert response.status_code == 201
    assert response.json()["format"] == "word"


def test_a_successful_upload_records_who_uploaded_it(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db

    upload(client)

    (source,) = sources(sessions)
    assert (source.kind, source.external_ref) == ("upload", "prd.md")
    assert source.status is SyncStatus.SUCCESS
    assert source.last_synced_at is not None
    assert source.display_name == "prd.md"
    with sessions() as session:
        assert source.last_synced_by == session.scalar(select(User.id))


# -- AC2: a rejection names the reason and adds nothing -----------------------


def test_an_unsupported_type_is_refused_with_the_reason(api_db):
    client, driver = setup(api_db)

    response = upload(client, "design.sketch", b"anything")

    assert response.status_code == 415
    assert "not a supported file type" in response.json()["detail"]
    assert "PDF" in response.json()["detail"]
    # Nothing reached the graph.
    assert driver.sessions == 0


def test_an_oversized_file_is_refused_with_the_limit(api_db):
    client, driver = setup(api_db)

    response = upload(client, "huge.txt", b"x" * (MAX_UPLOAD_BYTES + 1))

    assert response.status_code == 413
    assert "10 MB limit" in response.json()["detail"]
    assert driver.sessions == 0


def test_a_corrupt_pdf_is_refused_as_unreadable(api_db):
    client, driver = setup(api_db)

    response = upload(client, "broken.pdf", b"%PDF-1.4 not really")

    assert response.status_code == 422
    assert "could not be read as a PDF" in response.json()["detail"]
    assert driver.sessions == 0


def test_a_scanned_pdf_is_refused_rather_than_indexed_empty(api_db):
    from pypdf import PdfWriter

    client, driver = setup(api_db)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)

    response = upload(client, "scan.pdf", buffer.getvalue())

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]
    assert driver.sessions == 0


def test_a_rejected_upload_is_recorded_so_the_page_can_flag_it(api_db):
    """A rejected upload writes no nodes, so this row is the only evidence it
    was ever attempted."""
    client, _ = setup(api_db)
    _, sessions = api_db

    upload(client, "broken.pdf", b"%PDF-1.4 not really")

    (source,) = sources(sessions)
    assert source.status is SyncStatus.FAILED
    assert "could not be read as a PDF" in source.last_error
    assert source.display_name == "broken.pdf"
    # Never indexed, so there is no freshness to claim.
    assert source.last_synced_at is None


def test_an_oversized_upload_is_recorded_even_though_it_was_never_parsed(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db

    upload(client, "huge.txt", b"x" * (MAX_UPLOAD_BYTES + 1))

    (source,) = sources(sessions)
    assert source.status is SyncStatus.FAILED
    assert source.display_name == "huge.txt"


def test_an_empty_file_is_refused(api_db):
    client, _ = setup(api_db)

    response = upload(client, "empty.txt", b"")

    assert response.status_code == 422
    assert "empty" in response.json()["detail"]


# -- AC4: an identical re-upload updates rather than duplicating --------------


def test_re_uploading_the_same_file_updates_one_row(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db

    upload(client)
    response = upload(client)

    assert response.status_code == 201
    # Told plainly that this replaced what was there.
    assert response.json()["replaced"] is True
    assert len(sources(sessions)) == 1


def test_re_uploading_under_a_different_case_is_the_same_document(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db

    upload(client, "PRD.md")
    upload(client, "prd.md")

    # Two source rows -- the filename is the ref, verbatim -- but the graph ids
    # are case-folded, so the nodes are one document. See test_document_graph.
    assert {source.external_ref for source in sources(sessions)} == {"PRD.md", "prd.md"}


def test_two_different_files_are_two_sources(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db

    upload(client, "prd.md")
    upload(client, "spec.md", b"# Spec\n\nDetails.\n")

    assert [source.external_ref for source in sources(sessions)] == ["prd.md", "spec.md"]


# -- Authorisation ------------------------------------------------------------


def test_a_viewer_cannot_upload(api_db):
    client, driver = setup(api_db, role=Role.VIEWER)
    _, sessions = api_db

    response = upload(client)

    assert response.status_code == 403
    assert "sources.write" in response.json()["detail"]
    # Checked before the file is read, so the server never parsed it.
    assert driver.sessions == 0
    assert sources(sessions) == []


def test_a_non_member_cannot_discover_the_workspace_exists(api_db):
    client, driver = setup(api_db, role=None)
    _, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)

    response = upload(client)

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this workspace"
    assert driver.sessions == 0


def test_an_anonymous_caller_cannot_upload(api_db):
    client, driver = setup(api_db, role=None)

    assert upload(client).status_code == 401
    assert driver.sessions == 0


def test_a_malformed_workspace_id_is_refused_before_any_work(api_db):
    client, driver = setup(api_db)

    response = upload(client, url="/api/workspaces/not-a-uuid/uploads")

    assert response.status_code == 422
    assert driver.sessions == 0


# -- Edges --------------------------------------------------------------------


def test_a_path_in_the_filename_is_stripped(api_db):
    """The filename is the source's key and is shown on the page, so a
    browser-supplied path must not survive into either."""
    client, _ = setup(api_db)
    _, sessions = api_db

    response = upload(client, "../../etc/prd.md")

    assert response.status_code == 201
    assert response.json()["filename"] == "prd.md"
    (source,) = sources(sessions)
    assert source.external_ref == "prd.md"


def test_a_graph_outage_is_a_503_and_is_recorded(api_db):
    from neo4j.exceptions import ServiceUnavailable

    client, _ = setup(api_db, driver=FakeDriver(error=ServiceUnavailable("down")))
    _, sessions = api_db

    response = upload(client)

    assert response.status_code == 503
    (source,) = sources(sessions)
    assert source.status is SyncStatus.FAILED


def test_a_missing_file_field_is_a_422(api_db):
    client, _ = setup(api_db)

    assert client.post(URL).status_code == 422


# -- AC3: the Sources page lists the file -------------------------------------


def test_the_sources_page_lists_the_file_with_its_name_and_sections(api_db):
    """AC3: filename, upload time, and how many items it contributed."""
    client, _ = setup(api_db)
    _, sessions = api_db
    upload(client)

    app.dependency_overrides[graph_neo4j] = lambda: SourceDriver(
        upload_records=[{"source_ref": "prd.md", "sections": 2}]
    )
    (row,) = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()

    assert row["kind"] == "upload"
    assert row["repo"] == "prd.md"
    assert row["display_name"] == "prd.md"
    assert row["sections"] == 2
    # The document node counts alongside its sections.
    assert row["total_items"] == 3
    assert row["last_synced_at"] is not None
    assert row["status"] == "SUCCESS"


def test_a_failed_upload_still_appears_on_the_sources_page(api_db):
    client, _ = setup(api_db)
    upload(client, "broken.pdf", b"%PDF-1.4 not really")

    app.dependency_overrides[graph_neo4j] = lambda: SourceDriver()
    (row,) = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()

    assert row["status"] == "FAILED"
    assert row["display_name"] == "broken.pdf"
    assert row["sections"] == 0
    assert "could not be read as a PDF" in row["last_error"]


def test_uploads_and_repositories_appear_together(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    upload(client)
    with sessions() as session:
        session.add(
            DataSource(
                workspace_id=uuid.UUID(TEST_WORKSPACE_ID),
                kind="github",
                external_ref="acme/widgets",
                status=SyncStatus.SUCCESS,
                last_attempted_at=ATTEMPTED_AT,
            )
        )
        session.commit()

    app.dependency_overrides[graph_neo4j] = lambda: SourceDriver(
        records=[
            {
                "repo": "acme/widgets",
                "pull_requests": 4,
                "issues": 1,
                "total_items": 5,
            }
        ],
        upload_records=[{"source_ref": "prd.md", "sections": 2}],
    )
    rows = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()

    by_kind = {row["kind"]: row for row in rows}
    assert set(by_kind) == {"github", "upload"}
    assert by_kind["github"]["pull_requests"] == 4
    assert by_kind["upload"]["sections"] == 2

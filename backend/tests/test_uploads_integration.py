"""US-09 integration: upload -> real Neo4j -> graph endpoint.

AC4 is the reason this exists. "Re-uploading an identical copy updates the
existing items and creates no second copy" is a claim about MERGE semantics and
a DETACH DELETE, and a fake driver that records Cypher strings cannot tell you
whether either worked.

Skipped automatically when Neo4j isn't running.
"""

import io

import pytest

from app.main import app
from app.models import Role
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import TEST_WORKSPACE_ID, TEST_WORKSPACE_ID_B

pytestmark = pytest.mark.integration

PRD = b"# Scope\n\nIngestion only.\n\n# Non-goals\n\nNo billing.\n"


@pytest.fixture
def client(api_db):
    """A caller holding OWNER on both reserved test workspaces."""
    test_client, sessions = api_db
    with sessions() as session:
        owner = make_user(session, "upload-owner@example.com")
        for workspace_id, name in (
            (TEST_WORKSPACE_ID, "Primary"),
            (TEST_WORKSPACE_ID_B, "Secondary"),
        ):
            workspace = make_workspace(session, name, workspace_id)
            grant(session, workspace, owner, Role.OWNER)
        session.commit()
        session.refresh(owner)
    authenticate(test_client, sessions, owner)
    return test_client


def upload(client, filename="prd.md", data=PRD, workspace_id=TEST_WORKSPACE_ID):
    return client.post(
        f"/api/workspaces/{workspace_id}/uploads",
        files={"file": (filename, io.BytesIO(data))},
    )


def nodes_of(client, workspace_id=TEST_WORKSPACE_ID, node_type=None):
    body = client.get(f"/api/workspaces/{workspace_id}/graph").json()
    return [
        node
        for node in body["nodes"]
        if node_type is None or node["type"] == node_type
    ]


def test_an_uploaded_document_reaches_the_graph_endpoint(client, graph):
    assert upload(client).status_code == 201

    (document,) = nodes_of(client, node_type="Document")
    assert document["title"] == "prd.md"
    sections = nodes_of(client, node_type="DocumentSection")
    assert [section["title"] for section in sections] == ["Scope", "Non-goals"]


def test_each_section_is_linked_to_its_document(client, graph):
    upload(client)

    edges = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/graph").json()["edges"]

    (document,) = nodes_of(client, node_type="Document")
    assert len(edges) == 2
    assert all(edge["type"] == "SECTION_OF" for edge in edges)
    assert {edge["target"] for edge in edges} == {document["key"]}


def test_re_uploading_an_identical_copy_creates_no_second_copy(client, graph):
    """AC4, the whole point: same filename, same ids, MERGE updates in place."""
    upload(client)
    first = {node["key"] for node in nodes_of(client)}

    assert upload(client).json()["replaced"] is True

    assert {node["key"] for node in nodes_of(client)} == first
    assert len(nodes_of(client, node_type="Document")) == 1
    assert len(nodes_of(client, node_type="DocumentSection")) == 2


def test_re_uploading_an_edited_file_replaces_its_sections(client, graph):
    upload(client)

    upload(client, data=b"# Scope\n\nIngestion and chat.\n\n# Owner\n\nAryan.\n")

    sections = nodes_of(client, node_type="DocumentSection")
    assert [section["title"] for section in sections] == ["Scope", "Owner"]
    assert len(nodes_of(client, node_type="Document")) == 1


def test_shortening_a_document_removes_the_sections_it_no_longer_has(client, graph):
    """Without the prune, the tail of the previous version would survive as
    nodes describing text the document does not contain any more."""
    upload(client, data=b"# A\n\nOne.\n\n# B\n\nTwo.\n\n# C\n\nThree.\n")
    assert len(nodes_of(client, node_type="DocumentSection")) == 3

    upload(client, data=b"# A\n\nOne only now.\n")

    sections = nodes_of(client, node_type="DocumentSection")
    assert [section["title"] for section in sections] == ["A"]


def test_the_document_node_reports_its_new_section_count(client, graph):
    upload(client, data=b"# A\n\nOne.\n\n# B\n\nTwo.\n\n# C\n\nThree.\n")
    upload(client, data=b"# A\n\nOne only now.\n")

    (document,) = nodes_of(client, node_type="Document")
    details = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/nodes/Document/"
        f"{document['key'].split(':', 1)[1]}"
    ).json()

    assert details["attributes"]["section_count"] == 1


def test_two_workspaces_uploading_one_filename_keep_separate_documents(client, graph):
    upload(client, workspace_id=TEST_WORKSPACE_ID)
    upload(client, workspace_id=TEST_WORKSPACE_ID_B)

    assert len(nodes_of(client, TEST_WORKSPACE_ID, "Document")) == 1
    assert len(nodes_of(client, TEST_WORKSPACE_ID_B, "Document")) == 1


def test_a_workspace_never_sees_another_workspaces_documents(client, graph):
    upload(client, workspace_id=TEST_WORKSPACE_ID)

    assert nodes_of(client, TEST_WORKSPACE_ID_B) == []


def test_two_documents_coexist_without_sharing_sections(client, graph):
    upload(client, "prd.md")
    upload(client, "spec.md", b"# Interface\n\nREST.\n")

    documents = nodes_of(client, node_type="Document")
    assert {document["title"] for document in documents} == {"prd.md", "spec.md"}
    assert len(nodes_of(client, node_type="DocumentSection")) == 3


def test_a_section_detail_read_returns_its_text(client, graph):
    upload(client)
    (section,) = [
        node
        for node in nodes_of(client, node_type="DocumentSection")
        if node["title"] == "Scope"
    ]

    details = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/nodes/DocumentSection/"
        f"{section['key'].split(':', 1)[1]}"
    ).json()

    assert details["content"] == "Ingestion only."
    assert details["attributes"]["filename"] == "prd.md"
    assert details["attributes"]["position"] == 0


def test_the_sources_page_counts_the_uploaded_document(client, graph):
    upload(client)

    rows = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()

    (row,) = rows
    assert (row["kind"], row["display_name"], row["sections"]) == ("upload", "prd.md", 2)
    # Two sections plus the document node itself.
    assert row["total_items"] == 3


def test_a_rejected_upload_leaves_the_graph_untouched(client, graph):
    """AC2: nothing is added to the graph when the file is refused."""
    assert upload(client, "broken.pdf", b"%PDF-1.4 not really").status_code == 422

    assert nodes_of(client) == []

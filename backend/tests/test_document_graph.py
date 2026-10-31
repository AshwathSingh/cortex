"""T-9.4: writing an uploaded document into the graph.

The guarantee that matters is AC4: re-uploading the same file updates what is
already there instead of adding a second copy. That rests on identity being the
*filename* rather than the bytes, and on the prune that removes sections an
edited, shorter upload no longer has.
"""

import pytest

from app.uploads.graph import (
    DELETE_TRAILING_SECTIONS,
    UPSERT_DOCUMENT,
    UPSERT_SECTIONS,
    build_statements,
    content_hash,
    document_id,
    prepare,
    section_id,
    write_document,
)
from app.uploads.sections import DocumentSection

WS = "ccccccc0-0000-4000-8000-00000000c0de"
DATA = b"# Scope\n\nIngestion only.\n"


def sections(count: int = 2) -> list[DocumentSection]:
    return [
        DocumentSection(index, f"H{index}", f"Body {index}.") for index in range(count)
    ]


def build(filename="prd.md", data=DATA, count=2, workspace_id=WS):
    document = prepare(filename, data, "text", sections(count))
    return build_statements(document, workspace_id=workspace_id)


def queries(statements) -> list[str]:
    return [cypher for cypher, _ in statements]


def params_for(statements, query) -> dict:
    return next(params for cypher, params in statements if cypher is query)


# -- Identity ------------------------------------------------------------------


def test_a_filename_always_maps_to_the_same_id():
    assert document_id("prd.md") == document_id("prd.md")
    assert document_id("prd.md") != document_id("spec.md")


def test_identity_ignores_case_and_surrounding_space():
    """"PRD.pdf" and "prd.pdf" are the same document to a reader, and treating
    them as two would defeat AC4 on any case-insensitive filesystem."""
    assert document_id("PRD.pdf") == document_id("  prd.pdf  ")


def test_ids_are_prefixed_so_they_cannot_be_read_as_numbers():
    """`app.graph.queries.coerce_node_id` recovers an id's type by trying
    int() first, which only works because a prefixed id never parses."""
    node = document_id("prd.md")

    assert node.startswith("upload/")
    with pytest.raises(ValueError):
        int(node)
    with pytest.raises(ValueError):
        int(section_id(node, 3))


def test_a_section_id_carries_its_document_and_position():
    node = document_id("prd.md")

    assert section_id(node, 3) == f"{node}/3"


def test_the_content_hash_tracks_the_bytes_not_the_name():
    assert content_hash(b"same") == content_hash(b"same")
    assert content_hash(b"same") != content_hash(b"different")


# -- Statements ----------------------------------------------------------------


def test_the_document_is_written_before_its_sections():
    """The SECTION_OF edge MATCHes the document, so a later write binds nothing."""
    assert queries(build()) == [
        UPSERT_DOCUMENT,
        UPSERT_SECTIONS,
        DELETE_TRAILING_SECTIONS,
    ]


def test_every_node_carries_the_workspace_and_the_source_reference():
    statements = build()

    document_props = params_for(statements, UPSERT_DOCUMENT)["props"]
    assert document_props["workspace_id"] == WS
    assert document_props["source_ref"] == "prd.md"
    assert document_props["filename"] == "prd.md"

    for row in params_for(statements, UPSERT_SECTIONS)["rows"]:
        assert row["props"]["workspace_id"] == WS
        assert row["props"]["source_ref"] == "prd.md"


def test_the_document_records_what_it_was_read_from():
    props = params_for(build(), UPSERT_DOCUMENT)["props"]

    assert props["format"] == "text"
    assert props["content_hash"] == content_hash(DATA)
    assert props["section_count"] == 2
    assert props["uploaded_at"]


def test_each_section_keeps_its_heading_position_and_title():
    rows = params_for(build(), UPSERT_SECTIONS)["rows"]

    first = rows[0]["props"]
    assert (first["position"], first["heading"], first["title"]) == (0, "H0", "H0")
    assert first["body"] == "Body 0."
    assert first["document_id"] == document_id("prd.md")


def test_a_document_with_no_sections_writes_no_section_rows():
    statements = build(count=0)

    assert UPSERT_SECTIONS not in queries(statements)
    assert params_for(statements, UPSERT_DOCUMENT)["props"]["section_count"] == 0


def test_the_prune_targets_only_this_documents_trailing_sections():
    """An edited upload may be shorter; the tail of the previous version would
    otherwise survive as nodes describing text the document no longer has."""
    params = params_for(build(count=3), DELETE_TRAILING_SECTIONS)

    assert params["document_id"] == document_id("prd.md")
    assert params["section_count"] == 3
    assert params["workspace_id"] == WS
    assert "s.position >= $section_count" in DELETE_TRAILING_SECTIONS


def test_the_prune_runs_even_when_the_document_is_now_empty():
    statements = build(count=0)

    assert queries(statements)[-1] is DELETE_TRAILING_SECTIONS
    assert params_for(statements, DELETE_TRAILING_SECTIONS)["section_count"] == 0


def test_a_re_upload_reuses_every_id():
    """The whole of AC4: same filename, same ids, so MERGE updates in place."""
    first = build(data=b"original")
    second = build(data=b"edited, and longer than before")

    assert params_for(first, UPSERT_DOCUMENT)["id"] == (
        params_for(second, UPSERT_DOCUMENT)["id"]
    )
    assert [row["id"] for row in params_for(first, UPSERT_SECTIONS)["rows"]] == [
        row["id"] for row in params_for(second, UPSERT_SECTIONS)["rows"]
    ]
    # ...but the hash shows it is not the same file.
    assert params_for(first, UPSERT_DOCUMENT)["props"]["content_hash"] != (
        params_for(second, UPSERT_DOCUMENT)["props"]["content_hash"]
    )


def test_two_workspaces_uploading_one_filename_keep_separate_nodes():
    other = "ccccccc0-0000-4000-8000-00000000c0df"

    mine = params_for(build(), UPSERT_DOCUMENT)["props"]
    theirs = params_for(build(workspace_id=other), UPSERT_DOCUMENT)["props"]

    # Same id, different workspace: the composite key is what separates them.
    assert mine["id"] == theirs["id"]
    assert mine["workspace_id"] != theirs["workspace_id"]


def test_a_missing_workspace_is_refused_before_any_statement_is_built():
    with pytest.raises(ValueError, match="workspace_id"):
        build(workspace_id=None)


# -- Writing -------------------------------------------------------------------


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **params):
        self.calls.append(cypher)


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_write(self, fn):
        fn(self.tx)


class FakeDriver:
    def __init__(self):
        self.tx = FakeTx()
        self.sessions = 0

    def session(self):
        self.sessions += 1
        return FakeSession(self.tx)


def test_everything_is_written_in_one_transaction():
    """A half-written document would leave sections pointing at a document node
    that does not exist."""
    driver = FakeDriver()
    document = prepare("prd.md", DATA, "text", sections(2))

    count = write_document(driver, document, workspace_id=WS)

    assert driver.sessions == 1
    assert count == len(driver.tx.calls) == 3

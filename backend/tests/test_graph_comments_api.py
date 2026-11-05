"""T-27.5: comments on graph nodes and edges, with the authorisation checks.

No Neo4j. A comment names its target by key and nothing verifies that the target
exists -- see ``app.models.graph_comment`` for why -- so the graph is not part of
what these tests are about.
"""

import uuid

import pytest

from app.models import Role, User, Workspace, WorkspaceMembership, WorkspaceRole
from app.permissions import Permission, permission_values
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import TEST_WORKSPACE_ID, TEST_WORKSPACE_ID_B

WS = TEST_WORKSPACE_ID
OTHER_WS = TEST_WORKSPACE_ID_B
URL = f"/api/workspaces/{WS}/graph/comments"
ACTIVITY_URL = f"{URL}/activity"
SEEN_URL = f"{URL}/seen"

NODE = "Issue:42"
EDGE = "Author:7|AUTHORED|Issue:42"


@pytest.fixture
def two_members(api_db):
    """Two users on the same workspace, plus a second workspace for scoping."""
    client, sessions = api_db
    with sessions() as session:
        alice = make_user(session, "alice@example.com")
        bob = make_user(session, "bob@example.com")
        workspace = make_workspace(session, "Primary", WS)
        grant(session, workspace, alice, Role.OWNER)
        grant(session, workspace, bob, Role.VIEWER)
        other = make_workspace(session, "Secondary", OTHER_WS)
        grant(session, other, alice, Role.OWNER)
        session.commit()
        session.refresh(alice)
        session.refresh(bob)
        ids = (alice.id, bob.id)
    return client, sessions, ids


def sign_in(client, sessions, user_id: uuid.UUID):
    with sessions() as session:
        user = session.get(User, user_id)
        authenticate(client, sessions, user)


def post(client, body: str, target_key: str = NODE, target_kind: str = "node", url: str = URL):
    return client.post(
        url,
        json={"target_kind": target_kind, "target_key": target_key, "body": body},
    )


def read(client, target_key: str = NODE, target_kind: str = "node", url: str = URL):
    return client.get(
        url, params={"target_kind": target_kind, "target_key": target_key}
    )


# --- posting and reading a thread -------------------------------------------


def test_a_comment_can_be_left_on_a_node(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    response = post(client, "This decision looks wrong.")

    assert response.status_code == 201
    created = response.json()
    assert created["target_kind"] == "node"
    assert created["target_key"] == NODE
    assert created["body"] == "This decision looks wrong."
    assert created["author_name"] == "alice"


def test_a_comment_can_be_left_on_an_edge(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert post(client, "Weak evidence for this link.", EDGE, "edge").status_code == 201

    (comment,) = read(client, EDGE, "edge").json()
    assert comment["target_kind"] == "edge"


def test_a_thread_is_listed_oldest_first_with_author_and_time(two_members):
    """AC1: it is a conversation, so it only reads correctly in order."""
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, alice)
    post(client, "first")
    sign_in(client, sessions, bob)
    post(client, "second")

    thread = read(client).json()

    assert [c["body"] for c in thread] == ["first", "second"]
    assert [c["author_name"] for c in thread] == ["alice", "bob"]
    assert all(c["created_at"] for c in thread)


def test_a_thread_holds_only_its_own_target(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)
    post(client, "about the issue", NODE)
    post(client, "about the edge", EDGE, "edge")

    assert [c["body"] for c in read(client, NODE).json()] == ["about the issue"]
    assert [c["body"] for c in read(client, EDGE, "edge").json()] == ["about the edge"]


def test_a_target_with_no_comments_is_an_empty_thread(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert read(client, "Issue:999").json() == []


def test_a_viewer_can_take_part(two_members):
    """The story is about discussing a suggestion before approving it, which a
    reader who cannot say anything is excluded from."""
    client, sessions, (_, bob) = two_members
    sign_in(client, sessions, bob)

    assert post(client, "I disagree.").status_code == 201


# --- what is not a valid target ---------------------------------------------


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        ("node", "NotALabel:1"),
        ("node", "Issue"),
        ("node", "Issue:"),
        ("node", "Issue:not-a-number"),
        ("node", ""),
        ("edge", "Issue:42"),
        ("edge", "Issue:42|AUTHORED"),
        ("edge", "Issue:42||Issue:43"),
        ("edge", "bad|AUTHORED|Issue:43"),
        ("edge", "Issue:42|AUTHORED|bad"),
    ],
)
def test_a_key_that_cannot_name_anything_is_refused(two_members, kind, key):
    """A typo that creates a comment nothing can ever reach is worse than a 422."""
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert post(client, "hello", key, kind).status_code == 422


def test_an_unknown_target_kind_is_refused(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert post(client, "hello", NODE, "repository").status_code == 422


@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
def test_an_empty_comment_is_refused(two_members, body):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert post(client, body).status_code == 422


def test_an_enormous_comment_is_refused(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert post(client, "x" * 4001).status_code == 422


def test_surrounding_whitespace_is_trimmed(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert post(client, "  spaced  ").json()["body"] == "spaced"


# --- deleting ---------------------------------------------------------------


def test_an_author_can_delete_their_own_comment(two_members):
    client, sessions, (_, bob) = two_members
    sign_in(client, sessions, bob)
    comment_id = post(client, "never mind").json()["id"]

    assert client.delete(f"{URL}/{comment_id}").status_code == 204

    assert read(client).json() == []


def test_a_member_cannot_delete_someone_elses_comment(two_members):
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, alice)
    comment_id = post(client, "mine").json()["id"]
    sign_in(client, sessions, bob)

    response = client.delete(f"{URL}/{comment_id}")

    assert response.status_code == 403
    assert "your own comments" in response.json()["detail"]
    assert len(read(client).json()) == 1


def test_a_member_manager_can_remove_anyone_s_comment(two_members):
    """``members.manage`` already means "responsible for what people are doing
    in this workspace", so it is the permission that moderates."""
    client, sessions, (_, bob) = two_members
    sign_in(client, sessions, bob)
    comment_id = post(client, "theirs").json()["id"]

    with sessions() as session:
        moderator = make_user(session, "mod@example.com")
        workspace = session.get(Workspace, uuid.UUID(WS))
        role = WorkspaceRole(
            workspace_id=workspace.id,
            name="Moderator",
            permissions=permission_values(frozenset({Permission.MEMBERS_MANAGE})),
        )
        session.add(role)
        session.flush()
        session.add(
            WorkspaceMembership(
                user_id=moderator.id,
                workspace_id=workspace.id,
                custom_role_id=role.id,
            )
        )
        session.commit()
        session.refresh(moderator)
        moderator_id = moderator.id
    sign_in(client, sessions, moderator_id)

    assert client.delete(f"{URL}/{comment_id}").status_code == 204


def test_deleting_a_comment_that_does_not_exist_is_404(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert client.delete(f"{URL}/{uuid.uuid4()}").status_code == 404


# --- unseen marks (T-27.4) ---------------------------------------------------


def activity(client, url: str = ACTIVITY_URL):
    return {
        (row["target_kind"], row["target_key"]): (row["total"], row["unseen"])
        for row in client.get(url).json()
    }


def test_a_comment_from_someone_else_is_unseen(two_members):
    """AC2: the canvas marks it without the reader opening anything."""
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, alice)
    post(client, "look at this")

    sign_in(client, sessions, bob)

    assert activity(client) == {("node", NODE): (1, 1)}


def test_your_own_comment_is_not_unseen_to_you(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    post(client, "mine")

    assert activity(client) == {("node", NODE): (1, 0)}


def test_opening_a_thread_clears_its_mark(two_members):
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, alice)
    post(client, "look at this")
    sign_in(client, sessions, bob)
    assert activity(client)[("node", NODE)] == (1, 1)

    seen = client.post(SEEN_URL, json={"target_kind": "node", "target_key": NODE})

    assert seen.status_code == 200
    assert seen.json()["target_key"] == NODE
    assert activity(client)[("node", NODE)] == (1, 0)


def test_a_reply_after_reading_is_unseen_again(two_members):
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, alice)
    post(client, "one")
    sign_in(client, sessions, bob)
    client.post(SEEN_URL, json={"target_kind": "node", "target_key": NODE})
    sign_in(client, sessions, alice)
    post(client, "two")

    sign_in(client, sessions, bob)

    assert activity(client)[("node", NODE)] == (2, 1)


def test_a_read_mark_is_private_to_the_reader(two_members):
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, bob)
    post(client, "from bob")
    sign_in(client, sessions, alice)
    client.post(SEEN_URL, json={"target_kind": "node", "target_key": NODE})

    sign_in(client, sessions, bob)
    # Bob authored it, so it was never unseen to him -- but Alice reading it
    # must not have written anything into his bookkeeping either.
    assert activity(client)[("node", NODE)] == (1, 0)


def test_edges_are_marked_separately_from_nodes(two_members):
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, alice)
    post(client, "on the node", NODE)
    post(client, "on the edge", EDGE, "edge")
    sign_in(client, sessions, bob)

    client.post(SEEN_URL, json={"target_kind": "node", "target_key": NODE})

    assert activity(client) == {
        ("node", NODE): (1, 0),
        ("edge", EDGE): (1, 1),
    }


def test_a_workspace_with_no_comments_has_no_activity(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    assert client.get(ACTIVITY_URL).json() == []


def test_marking_an_invalid_target_seen_is_refused(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)

    response = client.post(
        SEEN_URL, json={"target_kind": "node", "target_key": "nonsense"}
    )

    assert response.status_code == 422


# --- workspace isolation (AC3) ----------------------------------------------


def test_a_comment_is_invisible_from_another_workspace(two_members):
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)
    post(client, "secret")

    other_url = f"/api/workspaces/{OTHER_WS}/graph/comments"

    assert read(client, url=other_url).json() == []
    assert client.get(f"{other_url}/activity").json() == []


def test_a_comment_cannot_be_deleted_through_another_workspace(two_members):
    """Scoped by id as well as by list: the other workspace answers the same 404
    as a comment that never existed."""
    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)
    comment_id = post(client, "secret").json()["id"]

    response = client.delete(f"/api/workspaces/{OTHER_WS}/graph/comments/{comment_id}")

    assert response.status_code == 404
    assert len(read(client).json()) == 1


def test_a_non_member_cannot_read_or_post(two_members):
    client, sessions, _ = two_members
    with sessions() as session:
        outsider = make_user(session, "outsider@example.com")
        session.commit()
        session.refresh(outsider)
        outsider_id = outsider.id
    sign_in(client, sessions, outsider_id)

    assert read(client).status_code == 403
    assert post(client, "hello").status_code == 403
    assert client.get(ACTIVITY_URL).status_code == 403


def test_an_unauthenticated_caller_is_401(api_db):
    client, _ = api_db

    assert client.get(URL, params={"target_kind": "node", "target_key": NODE}).status_code == 401


def test_deleting_a_workspace_takes_its_comments_with_it(two_members):
    """US-05 clears Postgres by deleting the workspace row, so both tables have
    to cascade from it or the delete trips their foreign keys."""
    from app.models import GraphComment, GraphCommentView

    client, sessions, (alice, _) = two_members
    sign_in(client, sessions, alice)
    post(client, "about to vanish")
    client.post(SEEN_URL, json={"target_kind": "node", "target_key": NODE})

    with sessions() as session:
        session.delete(session.get(Workspace, uuid.UUID(WS)))
        session.commit()
        assert session.query(GraphComment).count() == 0
        assert session.query(GraphCommentView).count() == 0


def test_a_comment_outlives_its_author(two_members):
    """SET NULL, not CASCADE: removing someone must not rewrite a discussion
    other people took decisions from."""
    client, sessions, (alice, bob) = two_members
    sign_in(client, sessions, bob)
    post(client, "bob's argument")

    with sessions() as session:
        session.delete(session.get(User, bob))
        session.commit()

    sign_in(client, sessions, alice)
    (comment,) = read(client).json()
    assert comment["body"] == "bob's argument"
    assert comment["author_id"] is None
    assert comment["author_name"] is None

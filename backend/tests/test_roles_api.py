"""US-21: custom roles, permission enforcement, and member role assignment."""

import uuid

import pytest

from app.models import Role, WorkspaceMembership
from tests.authz import authenticate, grant, make_user, make_workspace

WS = "00000000-0000-4000-8000-0000000000a1"
OTHER_WS = "00000000-0000-4000-8000-0000000000a2"


class World:
    """A workspace with an owner, plus helpers to act as anyone in it."""

    def __init__(self, api_db):
        self.client, self.sessions = api_db
        with self.sessions() as s:
            self.ws = make_workspace(s, "Team", WS)
            self.users = {"owner": make_user(s, "owner@example.com")}
            grant(s, self.ws, self.users["owner"], Role.OWNER)
            s.commit()

    def add(self, name, role=None, custom_role_id=None):
        with self.sessions() as s:
            user = make_user(s, f"{name}@example.com")
            s.add(
                WorkspaceMembership(
                    user_id=user.id,
                    workspace_id=uuid.UUID(WS),
                    role=role,
                    custom_role_id=custom_role_id,
                )
            )
            s.commit()
            self.users[name] = user
        return user

    def as_(self, name):
        self.client.cookies.clear()
        authenticate(self.client, self.sessions, self.users[name])
        return self.client

    def role(self, name, permissions, actor="owner", description=None):
        r = self.as_(actor).post(
            f"/api/workspaces/{WS}/roles",
            json={"name": name, "permissions": permissions, "description": description},
        )
        assert r.status_code == 201, r.text
        return r.json()

    def assign(self, actor, target, **body):
        return self.as_(actor).patch(
            f"/api/workspaces/{WS}/members/{self.users[target].id}/role", json=body
        )


@pytest.fixture
def w(api_db):
    return World(api_db)


# --- catalogue and listing -------------------------------------------------


def test_permission_catalogue_marks_owner_only(w):
    r = w.as_("owner").get("/api/permissions")
    assert r.status_code == 200
    by_key = {p["key"]: p for p in r.json()}
    assert by_key["workspace.delete"]["grantable"] is False
    assert by_key["sources.write"]["grantable"] is True


def test_catalogue_requires_login(w):
    w.client.cookies.clear()
    assert w.client.get("/api/permissions").status_code == 401


def test_list_roles_has_builtins_and_custom_with_counts(w):
    w.add("viewer1", role=Role.VIEWER)
    w.role("Reviewer", ["sources.write"])
    roles = w.as_("viewer1").get(f"/api/workspaces/{WS}/roles").json()
    by_name = {r["name"]: r for r in roles}
    assert by_name["OWNER"]["built_in"] and by_name["OWNER"]["member_count"] == 1
    assert by_name["VIEWER"]["member_count"] == 1
    assert by_name["Reviewer"]["built_in"] is False
    assert by_name["Reviewer"]["permissions"] == ["sources.write"]


def test_non_member_cannot_list_roles_or_members(w):
    with w.sessions() as s:
        stranger = make_user(s, "stranger@example.com")
        s.commit()
    w.users["stranger"] = stranger
    c = w.as_("stranger")
    assert c.get(f"/api/workspaces/{WS}/roles").status_code == 403
    assert c.get(f"/api/workspaces/{WS}/members").status_code == 403


def test_members_listing_shows_roles_and_permissions(w):
    w.add("ed", role=Role.EDITOR)
    rows = w.as_("ed").get(f"/api/workspaces/{WS}/members").json()
    by_email = {m["email"]: m for m in rows}
    assert by_email["owner@example.com"]["role"] == "OWNER"
    assert by_email["ed@example.com"]["permissions"] == ["sources.write"]


# --- creating, editing, deleting roles -----------------------------------


def test_owner_creates_custom_role_with_chosen_permissions(w):
    created = w.role("Librarian", ["sources.write", "members.manage"], description="x")
    assert created["permissions"] == ["sources.write", "members.manage"]
    assert created["built_in"] is False and created["description"] == "x"


def test_viewer_and_editor_cannot_manage_roles(w):
    w.add("v", role=Role.VIEWER)
    w.add("e", role=Role.EDITOR)
    for who in ("v", "e"):
        r = w.as_(who).post(f"/api/workspaces/{WS}/roles", json={"name": "X"})
        assert r.status_code == 403, who
        assert "roles.manage" in r.json()["detail"]


def test_unknown_or_owner_only_permission_is_rejected(w):
    c = w.as_("owner")
    r = c.post(f"/api/workspaces/{WS}/roles", json={"name": "X", "permissions": ["nope"]})
    assert r.status_code == 422
    r = c.post(
        f"/api/workspaces/{WS}/roles",
        json={"name": "X", "permissions": ["workspace.delete"]},
    )
    assert r.status_code == 400
    assert "workspace.delete" in r.json()["detail"]


def test_role_name_must_be_valid_and_unique_per_workspace(w):
    w.role("Reviewer", [])
    c = w.as_("owner")
    assert c.post(f"/api/workspaces/{WS}/roles", json={"name": "  "}).status_code == 422
    assert c.post(f"/api/workspaces/{WS}/roles", json={"name": "x" * 51}).status_code == 422
    assert c.post(f"/api/workspaces/{WS}/roles", json={"name": "reviewer"}).status_code == 409
    assert c.post(f"/api/workspaces/{WS}/roles", json={"name": "owner"}).status_code == 409


def test_same_role_name_allowed_in_different_workspaces(w):
    w.role("Reviewer", [])
    with w.sessions() as s:
        other = make_workspace(s, "Other", OTHER_WS)
        grant(s, other, w.users["owner"], Role.OWNER)
        s.commit()
    r = w.as_("owner").post(f"/api/workspaces/{OTHER_WS}/roles", json={"name": "Reviewer"})
    assert r.status_code == 201


def test_edit_role_applies_to_holders_on_next_request(w):
    role = w.role("Ingest", ["sources.write"])
    w.add("holder", custom_role_id=uuid.UUID(role["id"]))
    me = lambda: w.as_("holder").get(f"/api/workspaces/{WS}").json()["permissions"]
    assert me() == ["sources.write"]
    r = w.as_("owner").patch(f"/api/workspaces/{WS}/roles/{role['id']}", json={"permissions": []})
    assert r.status_code == 200 and r.json()["member_count"] == 1
    assert me() == []


def test_edit_role_can_rename_and_clear_description(w):
    role = w.role("Ingest", [], description="old")
    r = w.as_("owner").patch(
        f"/api/workspaces/{WS}/roles/{role['id']}", json={"name": "Loader", "description": None}
    )
    assert r.json()["name"] == "Loader" and r.json()["description"] is None


def test_cannot_delete_role_that_is_assigned(w):
    role = w.role("Ingest", [])
    w.add("holder", custom_role_id=uuid.UUID(role["id"]))
    r = w.as_("owner").delete(f"/api/workspaces/{WS}/roles/{role['id']}")
    assert r.status_code == 409
    assert w.as_("owner").get(f"/api/workspaces/{WS}/roles").json()[-1]["name"] == "Ingest"


def test_delete_unassigned_role(w):
    role = w.role("Ingest", [])
    assert w.as_("owner").delete(f"/api/workspaces/{WS}/roles/{role['id']}").status_code == 204
    names = [r["name"] for r in w.as_("owner").get(f"/api/workspaces/{WS}/roles").json()]
    assert "Ingest" not in names


def test_role_of_another_workspace_is_not_found(w):
    with w.sessions() as s:
        other = make_workspace(s, "Other", OTHER_WS)
        grant(s, other, w.users["owner"], Role.OWNER)
        s.commit()
    foreign = w.as_("owner").post(f"/api/workspaces/{OTHER_WS}/roles", json={"name": "F"}).json()
    r = w.as_("owner").patch(f"/api/workspaces/{WS}/roles/{foreign['id']}", json={"name": "G"})
    assert r.status_code == 404


# --- no privilege escalation ---------------------------------------------


def test_role_manager_cannot_grant_permissions_they_lack(w):
    mgr = w.role("RoleAdmin", ["roles.manage"])
    w.add("mgr", custom_role_id=uuid.UUID(mgr["id"]))
    r = w.as_("mgr").post(
        f"/api/workspaces/{WS}/roles", json={"name": "Sneaky", "permissions": ["members.manage"]}
    )
    assert r.status_code == 403
    # ...nor add one to their own role.
    r = w.as_("mgr").patch(
        f"/api/workspaces/{WS}/roles/{mgr['id']}", json={"permissions": ["roles.manage", "sources.write"]}
    )
    assert r.status_code == 403
    # What they hold, they may grant.
    r = w.as_("mgr").post(
        f"/api/workspaces/{WS}/roles", json={"name": "Peer", "permissions": ["roles.manage"]}
    )
    assert r.status_code == 201


def test_member_manager_cannot_assign_a_role_stronger_than_their_own(w):
    mm = w.role("MemberAdmin", ["members.manage"])
    strong = w.role("Strong", ["sources.write", "roles.manage"])
    w.add("mm", custom_role_id=uuid.UUID(mm["id"]))
    w.add("target", role=Role.VIEWER)
    assert w.assign("mm", "target", role_id=strong["id"]).status_code == 403
    assert w.assign("mm", "target", role="EDITOR").status_code == 403  # sources.write
    assert w.assign("mm", "target", role_id=mm["id"]).status_code == 200


# --- assigning roles to members (the US-21 acceptance criteria) -----------


def test_owner_sets_member_to_viewer_or_editor_and_it_applies_next_request(w):
    w.add("m", role=Role.EDITOR)
    ws_perms = lambda: w.as_("m").get(f"/api/workspaces/{WS}").json()
    assert ws_perms()["permissions"] == ["sources.write"]

    r = w.assign("owner", "m", role="VIEWER")
    assert r.status_code == 200
    assert r.json()["role"] == "VIEWER" and r.json()["permissions"] == []
    assert ws_perms()["role"] == "VIEWER"

    assert w.assign("owner", "m", role="EDITOR").json()["role"] == "EDITOR"
    assert ws_perms()["role"] == "EDITOR"


def test_assign_custom_role_then_back_to_builtin(w):
    role = w.role("Ingest", ["sources.write"])
    w.add("m", role=Role.VIEWER)
    r = w.assign("owner", "m", role_id=role["id"])
    assert r.json()["role"] == "Ingest" and r.json()["role_id"] == role["id"]
    r = w.assign("owner", "m", role="VIEWER")
    assert r.json()["role"] == "VIEWER" and r.json()["role_id"] is None
    with w.sessions() as s:
        m = s.query(WorkspaceMembership).filter_by(user_id=w.users["m"].id).one()
        assert m.role is Role.VIEWER and m.custom_role_id is None


def test_member_with_members_manage_can_change_roles(w):
    mm = w.role("MemberAdmin", ["members.manage"])
    w.add("mm", custom_role_id=uuid.UUID(mm["id"]))
    w.add("t", role=Role.EDITOR)
    assert w.assign("mm", "t", role="VIEWER").status_code == 200


def test_viewer_and_editor_cannot_change_roles(w):
    w.add("v", role=Role.VIEWER)
    w.add("e", role=Role.EDITOR)
    w.add("t", role=Role.VIEWER)
    for who in ("v", "e"):
        r = w.assign(who, "t", role="EDITOR")
        assert r.status_code == 403, who
        assert "members.manage" in r.json()["detail"]
    assert w.as_("t").get(f"/api/workspaces/{WS}").json()["role"] == "VIEWER"


def test_invalid_role_value_is_rejected_and_role_unchanged(w):
    w.add("t", role=Role.EDITOR)
    for body in ({"role": "SUPERUSER"}, {}, {"role": "VIEWER", "role_id": str(uuid.uuid4())}):
        assert w.assign("owner", "t", **body).status_code == 422, body
    assert w.assign("owner", "t", role_id="not-a-uuid").status_code == 422
    assert w.assign("owner", "t", role_id=str(uuid.uuid4())).status_code == 404
    assert w.as_("t").get(f"/api/workspaces/{WS}").json()["role"] == "EDITOR"


def test_assigning_to_a_non_member_is_404(w):
    with w.sessions() as s:
        w.users["ghost"] = make_user(s, "ghost@example.com")
        s.commit()
    assert w.assign("owner", "ghost", role="VIEWER").status_code == 404


def test_only_owner_can_grant_or_change_owner(w):
    mm = w.role("MemberAdmin", ["members.manage"])
    w.add("mm", custom_role_id=uuid.UUID(mm["id"]))
    w.add("t", role=Role.VIEWER)
    assert w.assign("mm", "t", role="OWNER").status_code == 403
    assert w.assign("mm", "owner", role="VIEWER").status_code == 403
    assert w.assign("owner", "t", role="OWNER").status_code == 200


def test_cannot_demote_last_owner_but_can_once_another_exists(w):
    r = w.assign("owner", "owner", role="VIEWER")
    assert r.status_code == 409 and "at least one owner" in r.json()["detail"]
    w.add("co", role=Role.OWNER)
    assert w.assign("co", "owner", role="EDITOR").status_code == 200
    # co is now the last owner.
    assert w.assign("co", "co", role="VIEWER").status_code == 409


# --- permission enforcement on write endpoints (T-21.3) -------------------


def test_custom_role_with_sources_write_may_reach_ingest_and_without_may_not(w):
    can = w.role("Ingest", ["sources.write"])
    cannot = w.role("Reader", [])
    w.add("can", custom_role_id=uuid.UUID(can["id"]))
    w.add("cannot", custom_role_id=uuid.UUID(cannot["id"]))
    body = {"repo_url": "not a url", "workspace_id": WS}
    # Permitted callers get past authorisation to URL validation (422); others stop at 403.
    assert w.as_("can").post("/api/ingest/github", json=body).status_code == 422
    r = w.as_("cannot").post("/api/ingest/github", json=body)
    assert r.status_code == 403 and "sources.write" in r.json()["detail"]

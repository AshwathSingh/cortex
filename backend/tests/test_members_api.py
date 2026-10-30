"""US-04: removing members from a workspace."""

import uuid

import pytest
from sqlalchemy import select

from app.models import InviteStatus, Role, WorkspaceInvite, WorkspaceMembership
from tests.test_roles_api import WS, World


@pytest.fixture
def w(api_db):
    return World(api_db)


def remove(w, actor, target):
    return w.as_(actor).delete(f"/api/workspaces/{WS}/members/{w.users[target].id}")


def member_ids(w):
    with w.sessions() as s:
        return {m.user_id for m in s.scalars(select(WorkspaceMembership))}


def can_see_workspace(w, who):
    return w.as_(who).get(f"/api/workspaces/{WS}/members").status_code == 200


def manager(w, name="mgr"):
    role = w.role("Manager", ["members.manage"])
    return w.add(name, custom_role_id=uuid.UUID(role["id"]))


def test_owner_removes_member_who_loses_access_immediately(w):
    w.add("ed", role=Role.EDITOR)
    assert can_see_workspace(w, "ed")
    r = remove(w, "owner", "ed")
    assert r.status_code == 204 and r.content == b""
    assert w.users["ed"].id not in member_ids(w)
    assert not can_see_workspace(w, "ed")
    assert w.as_("ed").get(f"/api/workspaces/{WS}").status_code == 403


def test_removed_member_cannot_write_either(w):
    w.add("ed", role=Role.EDITOR)
    remove(w, "owner", "ed")
    r = w.as_("ed").post(f"/api/workspaces/{WS}/roles", json={"name": "X"})
    assert r.status_code == 403


def test_manager_with_custom_role_can_remove_members(w):
    manager(w)
    w.add("v", role=Role.VIEWER)
    assert remove(w, "mgr", "v").status_code == 204
    assert w.users["v"].id not in member_ids(w)


@pytest.mark.parametrize("role", [Role.VIEWER, Role.EDITOR])
def test_members_without_permission_cannot_remove_others(w, role):
    w.add("a", role=role)
    w.add("b", role=Role.VIEWER)
    r = remove(w, "a", "b")
    assert r.status_code == 403
    assert w.users["b"].id in member_ids(w)


def test_removing_a_non_member_is_404(w):
    from tests.authz import make_user

    with w.sessions() as s:
        w.users["ghost"] = make_user(s, "ghost@example.com")
        s.commit()
    r = remove(w, "owner", "ghost")
    assert r.status_code == 404


def test_non_member_caller_is_403(w):
    from tests.authz import make_user

    with w.sessions() as s:
        w.users["stranger"] = make_user(s, "stranger@example.com")
        s.commit()
    assert remove(w, "stranger", "owner").status_code == 403
    assert w.users["owner"].id in member_ids(w)


def test_requires_login(w):
    w.client.cookies.clear()
    r = w.client.delete(f"/api/workspaces/{WS}/members/{w.users['owner'].id}")
    assert r.status_code == 401


def test_only_owner_can_remove_an_owner(w):
    manager(w)
    w.add("owner2", role=Role.OWNER)
    r = remove(w, "mgr", "owner2")
    assert r.status_code == 403 and "owner" in r.json()["detail"]
    assert w.users["owner2"].id in member_ids(w)
    assert remove(w, "owner", "owner2").status_code == 204


def test_last_owner_cannot_be_removed_or_leave(w):
    r = remove(w, "owner", "owner")
    assert r.status_code == 409 and "at least one owner" in r.json()["detail"]
    assert w.users["owner"].id in member_ids(w)


def test_owner_can_leave_when_another_owner_remains(w):
    w.add("owner2", role=Role.OWNER)
    assert remove(w, "owner", "owner").status_code == 204
    assert not can_see_workspace(w, "owner")
    assert can_see_workspace(w, "owner2")
    assert remove(w, "owner2", "owner2").status_code == 409  # now the last one


def test_any_member_can_leave_without_manage_permission(w):
    w.add("v", role=Role.VIEWER)
    assert remove(w, "v", "v").status_code == 204
    assert not can_see_workspace(w, "v")


def test_removal_leaves_invites_they_sent(w):
    manager(w)
    w.as_("mgr").post(
        f"/api/workspaces/{WS}/invites", json={"email": "n@example.com", "role": "VIEWER"}
    ).raise_for_status()
    assert remove(w, "owner", "mgr").status_code == 204
    with w.sessions() as s:
        (inv,) = s.scalars(select(WorkspaceInvite)).all()
        assert inv.status is InviteStatus.PENDING


def test_removed_member_can_be_invited_back(w):
    w.add("ed", role=Role.EDITOR)
    remove(w, "owner", "ed")
    token = (
        w.as_("owner")
        .post(f"/api/workspaces/{WS}/invites", json={"email": "ed@example.com"})
        .json()["token"]
    )
    assert w.as_("ed").post(f"/api/invites/{token}/accept").status_code == 200
    assert can_see_workspace(w, "ed")

"""US-03 T-1.1 / T-1.2: the invite schema and POST /api/workspaces/{id}/invites."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import InviteStatus, Role, WorkspaceInvite, WorkspaceMembership
from app.security import hash_invite_token
from tests.test_roles_api import WS, World

URL = f"/api/workspaces/{WS}/invites"


@pytest.fixture
def w(api_db):
    return World(api_db)


def invite(w, actor, **body):
    body.setdefault("email", "new@example.com")
    return w.as_(actor).post(URL, json=body)


def stored(w) -> list[WorkspaceInvite]:
    with w.sessions() as s:
        return list(s.scalars(select(WorkspaceInvite)))


# --- T-1.2: creating an invite ----------------------------------------------


def test_owner_invite_returns_token_and_creates_pending_invite(w):
    r = invite(w, "owner")
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"id", "email", "role", "role_id", "expires_at", "token"}
    assert body["email"] == "new@example.com"
    assert body["role"] == "EDITOR" and body["role_id"] is None  # default
    assert len(body["token"]) >= 40

    (row,) = stored(w)
    assert str(row.id) == body["id"]
    assert row.status is InviteStatus.PENDING
    assert row.invited_by == w.users["owner"].id


def test_only_the_hash_of_the_token_is_stored(w):
    token = invite(w, "owner").json()["token"]
    (row,) = stored(w)
    assert row.token_hash == hash_invite_token(token)
    assert token not in row.token_hash and row.token_hash != token
    assert len(row.token_hash) == 64


def test_tokens_are_unique_per_invite(w):
    a = invite(w, "owner", email="a@example.com").json()["token"]
    b = invite(w, "owner", email="b@example.com").json()["token"]
    assert a != b


def test_expiry_defaults_to_seven_days_and_follows_config(w, monkeypatch):
    def days_until(r):
        exp = datetime.fromisoformat(r.json()["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return (exp - datetime.now(timezone.utc)).total_seconds() / 86400

    assert 6.99 < days_until(invite(w, "owner", email="a@example.com")) <= 7
    monkeypatch.setattr(settings, "invite_ttl_days", 2)
    assert 1.99 < days_until(invite(w, "owner", email="b@example.com")) <= 2


def test_email_is_normalised_and_validated(w):
    r = invite(w, "owner", email="  Mixed.Case@Example.COM ")
    assert r.status_code == 201 and r.json()["email"] == "mixed.case@example.com"
    for bad in ("not-an-email", "", "a@b"):
        assert invite(w, "owner", email=bad).status_code == 422, bad
    assert w.as_("owner").post(URL, json={}).status_code == 422


def test_invite_with_builtin_role(w):
    r = invite(w, "owner", role="VIEWER")
    assert r.json()["role"] == "VIEWER"
    (row,) = stored(w)
    assert row.role is Role.VIEWER and row.custom_role_id is None


def test_invite_with_custom_role(w):
    role = w.role("Reviewer", ["sources.write"])
    r = invite(w, "owner", role_id=role["id"])
    assert r.status_code == 201
    assert r.json()["role"] == "Reviewer" and r.json()["role_id"] == role["id"]
    (row,) = stored(w)
    assert row.role is None and str(row.custom_role_id) == role["id"]


def test_role_and_role_id_together_or_invalid_are_rejected(w):
    role = w.role("Reviewer", [])
    assert invite(w, "owner", role="VIEWER", role_id=role["id"]).status_code == 422
    assert invite(w, "owner", role="SUPERUSER").status_code == 422
    assert invite(w, "owner", role_id="nope").status_code == 422
    assert invite(w, "owner", role_id=str(uuid.uuid4())).status_code == 404
    assert stored(w) == []


def test_custom_role_of_another_workspace_is_not_found(w):
    from tests.authz import grant, make_workspace

    other_ws = "00000000-0000-4000-8000-0000000000a2"
    with w.sessions() as s:
        other = make_workspace(s, "Other", other_ws)
        grant(s, other, w.users["owner"], Role.OWNER)
        s.commit()
    foreign = w.as_("owner").post(
        f"/api/workspaces/{other_ws}/roles", json={"name": "F"}
    ).json()
    assert invite(w, "owner", role_id=foreign["id"]).status_code == 404


# --- who may invite -----------------------------------------------------------


@pytest.mark.parametrize("builtin", [Role.VIEWER, Role.EDITOR])
def test_members_without_members_manage_get_403(w, builtin):
    w.add("m", role=builtin)
    r = invite(w, "m")
    assert r.status_code == 403 and "members.manage" in r.json()["detail"]
    assert stored(w) == []


def test_non_member_and_anonymous_are_refused(w):
    with w.sessions() as s:
        from tests.authz import make_user

        w.users["stranger"] = make_user(s, "stranger@example.com")
        s.commit()
    assert invite(w, "stranger").status_code == 403
    w.client.cookies.clear()
    assert w.client.post(URL, json={"email": "x@example.com"}).status_code == 401


def test_custom_role_with_members_manage_can_invite(w):
    mm = w.role("MemberAdmin", ["members.manage"])
    w.add("mm", custom_role_id=uuid.UUID(mm["id"]))
    assert invite(w, "mm", role="VIEWER").status_code == 201


def test_only_an_owner_may_invite_an_owner(w):
    mm = w.role("MemberAdmin", ["members.manage"])
    w.add("mm", custom_role_id=uuid.UUID(mm["id"]))
    r = invite(w, "mm", role="OWNER")
    assert r.status_code == 403 and "owner" in r.json()["detail"].lower()
    assert invite(w, "owner", role="OWNER").status_code == 201


def test_inviter_cannot_offer_permissions_they_lack(w):
    mm = w.role("MemberAdmin", ["members.manage"])
    strong = w.role("Strong", ["sources.write", "roles.manage"])
    w.add("mm", custom_role_id=uuid.UUID(mm["id"]))
    assert invite(w, "mm", role_id=strong["id"]).status_code == 403
    assert invite(w, "mm", role="EDITOR").status_code == 403  # carries sources.write
    assert invite(w, "mm", role_id=mm["id"]).status_code == 201  # what they hold
    assert len(stored(w)) == 1


# --- conflicts -----------------------------------------------------------------


def test_duplicate_pending_invite_is_409_regardless_of_case(w):
    assert invite(w, "owner").status_code == 201
    for email in ("new@example.com", "NEW@Example.com"):
        r = invite(w, "owner", email=email)
        assert r.status_code == 409 and "pending" in r.json()["detail"]
    assert len(stored(w)) == 1


def test_inviting_an_existing_member_is_409(w):
    w.add("already", role=Role.VIEWER)
    r = invite(w, "owner", email="ALREADY@example.com")
    assert r.status_code == 409 and "already a member" in r.json()["detail"]
    assert stored(w) == []


def test_member_of_another_workspace_can_still_be_invited(w):
    from tests.authz import grant, make_workspace

    with w.sessions() as s:
        other = make_workspace(s, "Other", "00000000-0000-4000-8000-0000000000a2")
        grant(s, other, w.users["owner"], Role.OWNER)
        s.commit()
    # owner@example.com belongs to Other too, but is invited here under a new address.
    assert invite(w, "owner", email="elsewhere@example.com").status_code == 201


def test_an_expired_pending_invite_does_not_block_a_new_one(w):
    first = invite(w, "owner").json()
    with w.sessions() as s:
        row = s.get(WorkspaceInvite, uuid.UUID(first["id"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    second = invite(w, "owner")
    assert second.status_code == 201 and second.json()["id"] != first["id"]
    by_id = {str(r.id): r.status for r in stored(w)}
    assert by_id[first["id"]] is InviteStatus.EXPIRED
    assert by_id[second.json()["id"]] is InviteStatus.PENDING


def test_a_revoked_or_accepted_invite_does_not_block_a_new_one(w):
    first = invite(w, "owner").json()
    with w.sessions() as s:
        s.get(WorkspaceInvite, uuid.UUID(first["id"])).status = InviteStatus.REVOKED
        s.commit()
    assert invite(w, "owner").status_code == 201


# --- T-1.1: schema ---------------------------------------------------------------


def test_database_allows_only_one_pending_invite_per_workspace_and_email(w):
    from app.security import new_invite_token

    def row(status):
        return WorkspaceInvite(
            workspace_id=uuid.UUID(WS),
            email="x@example.com",
            token_hash=hash_invite_token(new_invite_token()),
            role=Role.EDITOR,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            status=status,
        )

    with w.sessions() as s:
        s.add_all([row(InviteStatus.ACCEPTED), row(InviteStatus.REVOKED)])
        s.add(row(InviteStatus.PENDING))
        s.commit()  # history rows never conflict
        s.add(row(InviteStatus.PENDING))
        with pytest.raises(IntegrityError):
            s.commit()


def test_database_requires_exactly_one_role_on_an_invite(w):
    with w.sessions() as s:
        s.add(
            WorkspaceInvite(
                workspace_id=uuid.UUID(WS),
                email="x@example.com",
                token_hash="h" * 64,
                role=None,
                custom_role_id=None,
                expires_at=datetime.now(timezone.utc),
                status=InviteStatus.PENDING,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_new_memberships_default_to_active_with_no_inviter(w):
    with w.sessions() as s:
        memberships = s.scalars(select(WorkspaceMembership)).all()
        assert memberships and all(
            m.status == "active" and m.invited_by is None for m in memberships
        )


# --- T-1.3 / T-1.4: accepting an invite -------------------------------------


def accept(w, who, token):
    return w.as_(who).post(f"/api/invites/{token}/accept")


def outsider(w, name="guest"):
    from tests.authz import make_user

    with w.sessions() as s:
        w.users[name] = make_user(s, f"{name}@example.com")
        s.commit()
    return name


def members(w) -> list[WorkspaceMembership]:
    with w.sessions() as s:
        return list(s.scalars(select(WorkspaceMembership)))


def test_accept_adds_member_with_invite_role_and_grants_access(w):
    token = invite(w, "owner", role="VIEWER").json()["token"]
    guest = outsider(w)
    assert w.as_(guest).get(f"/api/workspaces/{WS}/members").status_code == 403

    r = accept(w, guest, token)
    assert r.status_code == 200, r.text
    assert r.json() == {"workspace_id": WS, "role": "VIEWER"}

    row = next(m for m in members(w) if m.user_id == w.users[guest].id)
    assert row.role is Role.VIEWER and row.invited_by == w.users["owner"].id
    assert row.status == "active"
    assert w.as_(guest).get(f"/api/workspaces/{WS}/members").status_code == 200
    (inv,) = stored(w)
    assert inv.status is InviteStatus.ACCEPTED and inv.accepted_at is not None


def test_accept_custom_role_invite(w):
    role = w.role("Reviewer", ["sources.write"])
    token = invite(w, "owner", role_id=role["id"]).json()["token"]
    r = accept(w, outsider(w), token)
    assert r.status_code == 200 and r.json()["role"] == "Reviewer"


def test_accept_requires_login(w):
    token = invite(w, "owner").json()["token"]
    w.client.cookies.clear()
    assert w.client.post(f"/api/invites/{token}/accept").status_code == 401
    assert stored(w)[0].status is InviteStatus.PENDING


def test_unknown_token_is_404_and_creates_nothing(w):
    before = len(members(w))
    r = accept(w, outsider(w), "nope")
    assert r.status_code == 404
    assert len(members(w)) == before


def test_expired_token_is_410_marked_expired_and_creates_no_member(w):
    token = invite(w, "owner").json()["token"]
    with w.sessions() as s:
        inv = s.scalars(select(WorkspaceInvite)).one()
        inv.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    before = len(members(w))
    guest = outsider(w)
    r = accept(w, guest, token)
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert len(members(w)) == before
    assert stored(w)[0].status is InviteStatus.EXPIRED
    assert accept(w, guest, token).status_code == 410  # stays rejected


def test_used_token_is_409_and_creates_no_second_member(w):
    token = invite(w, "owner").json()["token"]
    assert accept(w, outsider(w, "a"), token).status_code == 200
    before = len(members(w))
    r = accept(w, outsider(w, "b"), token)
    assert r.status_code == 409 and "already been used" in r.json()["detail"]
    assert len(members(w)) == before


def test_revoked_token_is_409(w):
    token = invite(w, "owner").json()["token"]
    with w.sessions() as s:
        s.scalars(select(WorkspaceInvite)).one().status = InviteStatus.REVOKED
        s.commit()
    before = len(members(w))
    r = accept(w, outsider(w), token)
    assert r.status_code == 409 and "revoked" in r.json()["detail"]
    assert len(members(w)) == before


def test_existing_member_consumes_invite_without_duplicate_row(w):
    token = invite(w, "owner", email="x@example.com", role="VIEWER").json()["token"]
    w.add("ed", role=Role.EDITOR)
    before = len(members(w))
    r = accept(w, "ed", token)
    assert r.status_code == 200 and r.json()["role"] == "EDITOR"  # role unchanged
    assert len(members(w)) == before
    assert stored(w)[0].status is InviteStatus.ACCEPTED


def test_invite_for_one_workspace_does_not_leak_to_others(w):
    token = invite(w, "owner").json()["token"]
    guest = outsider(w)
    accept(w, guest, token)
    assert all(str(m.workspace_id) == WS for m in members(w))

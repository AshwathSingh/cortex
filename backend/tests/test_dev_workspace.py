"""scripts.dev_workspace: the `list` command must handle custom-role members."""

import argparse
import uuid

from app.models import Role, WorkspaceMembership, WorkspaceRole
from scripts import dev_workspace
from tests.authz import grant, make_user, make_workspace

WS = "00000000-0000-4000-8000-0000000000b1"


def test_list_shows_builtin_and_custom_roles(db_sessions, capsys):
    with db_sessions() as s:
        ws = make_workspace(s, "Team", WS)
        owner = make_user(s, "owner@example.com")
        grant(s, ws, owner, Role.OWNER)
        role = WorkspaceRole(workspace_id=ws.id, name="Reviewer", permissions=[])
        s.add(role)
        s.flush()
        member = make_user(s, "rev@example.com")
        s.add(
            WorkspaceMembership(
                user_id=member.id, workspace_id=ws.id, custom_role_id=role.id
            )
        )
        s.commit()

    with db_sessions() as s:
        dev_workspace._list(s, argparse.Namespace())  # raised AttributeError on role=None

    out = capsys.readouterr().out
    assert "owner = OWNER" in out
    assert "rev = Reviewer" in out

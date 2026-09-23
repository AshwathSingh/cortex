"""Local-only helper for creating the rows the workspace endpoints read.

Usage:
    python -m scripts.dev_workspace trial             # ADD the whole check scenario
    python -m scripts.dev_workspace --reset           # DELETE everything, add nothing
    python -m scripts.dev_workspace list
    python -m scripts.dev_workspace create-user      --github-id 12345 --name "Aryan" --email a@b.com --password "local-development-password"
    python -m scripts.dev_workspace create-workspace --owner <user-id> --name "Cortex"
    python -m scripts.dev_workspace add-member       --workspace <ws-id> --user <user-id> --role VIEWER

``trial`` adds two users, four workspaces and five memberships, then prints the
curl commands that check every acceptance criterion against them. It only ever
adds. ``--reset`` only ever deletes. To start clean, run ``--reset`` and then
``trial``.

This talks to Postgres directly through SQLAlchemy -- it does NOT go through the
API, so it works whether or not uvicorn is running.

NOTE: This is a developer convenience, not a fixture loader and not part of the API.
Creating a workspace through the product is a separate user story; until that
endpoint exists this script is how a workspace comes into being locally. Each
command prints the id it created. API access still requires signing in normally.
"""

import argparse
import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.postgres import dispose_engine, get_session_factory
from app.models import Role, User, Workspace, WorkspaceMembership
from app.security import hash_password

TRIAL_PASSWORD = "local-development-password"


def _user_name(user: User) -> str:
    return user.display_name or user.email


def _create_user(session, args: argparse.Namespace) -> None:
    user = User(
        github_id=int(args.github_id),
        display_name=args.name,
        email=args.email,
        password_hash=hash_password(args.password),
    )
    session.add(user)
    session.commit()
    print(f"user {user.id}  {_user_name(user)} <{user.email}>")


def _create_workspace(session, args: argparse.Namespace) -> None:
    owner = session.get(User, uuid.UUID(args.owner))
    if owner is None:
        raise SystemExit(f"no user with id {args.owner}")

    workspace = Workspace(name=args.name, owner_id=owner.id)
    session.add(workspace)
    session.flush()  # assign workspace.id before the membership references it

    # The owner is a member like anyone else; every access check reads this table.
    session.add(
        WorkspaceMembership(
            user_id=owner.id, workspace_id=workspace.id, role=Role.OWNER
        )
    )
    session.commit()
    print(f"workspace {workspace.id}  {workspace.name}  owner={owner.id}")


def _add_member(session, args: argparse.Namespace) -> None:
    workspace = session.get(Workspace, uuid.UUID(args.workspace))
    if workspace is None:
        raise SystemExit(f"no workspace with id {args.workspace}")
    user = session.get(User, uuid.UUID(args.user))
    if user is None:
        raise SystemExit(f"no user with id {args.user}")

    membership = WorkspaceMembership(
        user_id=user.id, workspace_id=workspace.id, role=Role(args.role)
    )
    session.add(membership)
    session.commit()
    print(
        f"membership {membership.id}  {_user_name(user)} -> "
        f"{workspace.name} as {args.role}"
    )


def _list(session, args: argparse.Namespace) -> None:
    users = session.scalars(select(User).order_by(User.created_at)).all()
    print("users:")
    for user in users:
        print(f"  {user.id}  {_user_name(user)} <{user.email}>")

    print("workspaces:")
    rows = session.execute(
        select(Workspace, WorkspaceMembership, User)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .order_by(Workspace.name)
    ).all()
    for workspace, membership, user in rows:
        print(
            f"  {workspace.id}  {workspace.name:<20} "
            f"{_user_name(user)} = {membership.role.value}"
        )


def _reset(session, args: argparse.Namespace) -> None:
    """Delete every user, workspace and membership. Adds nothing back.

    Run ``trial`` afterwards if you want the check scenario rebuilt.
    """
    # CASCADE also clears workspace_memberships via its foreign keys.
    session.execute(text("TRUNCATE users, workspaces, workspace_memberships CASCADE"))
    session.commit()
    print("deleted all users, workspaces and memberships")


def _trial(session, args: argparse.Namespace) -> None:
    """Add the US-41 check scenario, then print the curls that exercise it.

    Adds only -- it never deletes. Run ``--reset`` first if the tables already
    hold data, or the unique constraints on the trial users will reject it.

    Two users, four workspaces, five memberships.
    """
    owner = User(
        github_id=900001,
        display_name="Aryan Jumani",
        email="trial-owner@cortex.test",
        password_hash=hash_password(TRIAL_PASSWORD),
    )
    outsider = User(
        github_id=900002,
        display_name="Outsider",
        email="trial-outsider@cortex.test",
        password_hash=hash_password(TRIAL_PASSWORD),
    )
    session.add_all([owner, outsider])
    session.flush()

    def workspace(name: str, holder: User, role: Role = Role.OWNER) -> Workspace:
        ws = Workspace(name=name, owner_id=holder.id)
        session.add(ws)
        session.flush()
        session.add(
            WorkspaceMembership(user_id=holder.id, workspace_id=ws.id, role=role)
        )
        return ws

    apollo = workspace("Apollo", owner)
    cortex = workspace("Cortex", owner)
    private = workspace("Private Project", outsider)
    shared = workspace("Shared", outsider)

    # I can see Shared without owning it.
    session.add(
        WorkspaceMembership(
            user_id=owner.id, workspace_id=shared.id, role=Role.VIEWER
        )
    )
    session.commit()

    print("users")
    print(f"  {owner.id}  {_user_name(owner)}")
    print(
        f"  {outsider.id}  {_user_name(outsider)}  "
        "<- a second user, to prove access is enforced"
    )
    print("\nworkspaces, and who can see each one")
    print(f"  {apollo.id}  {'Apollo':<16} {_user_name(owner)} = OWNER")
    print(f"  {cortex.id}  {'Cortex':<16} {_user_name(owner)} = OWNER")
    print(
        f"  {shared.id}  {'Shared':<16} {_user_name(outsider)} = OWNER, "
        f"{_user_name(owner)} = VIEWER"
    )
    print(
        f"  {private.id}  {'Private Project':<16} {_user_name(outsider)} = OWNER  "
        f"({_user_name(owner)} has no access to this one)"
    )

    base = "http://127.0.0.1:8000"
    print("\nstart the API, sign in, then check it:\n")
    print("  # create a cookie jar for the trial owner")
    print(
        f"  curl -c /tmp/cortex.cookies -H 'Content-Type: application/json' "
        f"-d '{{\"email\":\"{owner.email}\",\"password\":\"{TRIAL_PASSWORD}\"}}' "
        f"{base}/api/auth/login\n"
    )
    print("  # the workspace list: Apollo, Cortex and Shared.")
    print("  # Private Project must NOT appear -- this user has no role on it.")
    print(f"  curl -b /tmp/cortex.cookies {base}/api/workspaces\n")
    print("  # open a workspace held only as VIEWER, not owned -> 200")
    print(f"  curl -b /tmp/cortex.cookies {base}/api/workspaces/{shared.id}\n")
    print("  # open a workspace with no role on it -> 403")
    print(f"  curl -i -b /tmp/cortex.cookies {base}/api/workspaces/{private.id}\n")
    print("  # a workspace id that does not exist -> the same 403, so nobody")
    print("  # can probe which workspace ids are real")
    print(f"  curl -i -b /tmp/cortex.cookies {base}/api/workspaces/{uuid.uuid4()}\n")
    print("  # no session cookie at all -> 401")
    print(f'  curl -i {base}/api/workspaces')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev_workspace", description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete all users, workspaces and memberships; adds nothing back",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("create-user")
    p.add_argument("--github-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.set_defaults(func=_create_user)

    p = sub.add_parser("create-workspace")
    p.add_argument("--owner", required=True, help="user id")
    p.add_argument("--name", required=True)
    p.set_defaults(func=_create_workspace)

    p = sub.add_parser("add-member")
    p.add_argument("--workspace", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--role", required=True, choices=[r.value for r in Role])
    p.set_defaults(func=_add_member)

    p = sub.add_parser("list")
    p.set_defaults(func=_list)

    p = sub.add_parser("trial", help="add the full US-41 check scenario")
    p.set_defaults(func=_trial)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # --reset stands alone: it is the only thing that deletes, and it never
    # runs alongside a subcommand.
    if args.reset:
        action = _reset
    elif args.command:
        action = args.func
    else:
        parser.print_help()
        raise SystemExit(1)

    session = get_session_factory()()
    try:
        action(session, args)
    except IntegrityError:
        session.rollback()
        raise SystemExit(
            "conflicts with rows already in the database — "
            "run `--reset` first, then re-run this."
        )
    finally:
        session.close()
        dispose_engine()


if __name__ == "__main__":
    main()

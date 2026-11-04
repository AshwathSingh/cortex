"use client";

import { type ReactNode, useEffect, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { MemberActionsDialog } from "@/components/workspaces/member-actions-dialog";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { ApiError } from "@/lib/api";
import type {
  WorkspaceMember,
  WorkspacePermission,
} from "@/lib/api-types";
import { listWorkspaceMembers } from "@/lib/member-client";

type MemberListState =
  | { kind: "loading" }
  | { kind: "ready"; members: WorkspaceMember[] }
  | { kind: "error"; message: string };

function memberInitials(member: WorkspaceMember) {
  const label = member.name?.trim() || member.email?.split("@")[0] || "Member";
  const words = label.split(/\s+/).filter(Boolean);
  const initials =
    words.length > 1
      ? `${words[0][0]}${words[words.length - 1][0]}`
      : words[0].slice(0, 2);

  return initials.toUpperCase();
}

function memberName(member: WorkspaceMember) {
  return member.name?.trim() || member.email || "Workspace member";
}

export function WorkspaceMemberList({
  workspaceId,
  currentUserId,
  currentRole,
  permissions,
  action,
}: {
  workspaceId: string;
  currentUserId?: string;
  currentRole: string;
  permissions: WorkspacePermission[];
  action?: ReactNode;
}) {
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [state, setState] = useState<MemberListState>({ kind: "loading" });
  const [activeMember, setActiveMember] = useState<WorkspaceMember | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    void listWorkspaceMembers(workspaceId, controller.signal)
      .then((members) => {
        if (!controller.signal.aborted) {
          setState({ kind: "ready", members });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message:
            error instanceof ApiError
              ? error.message
              : "Could not load workspace members. The Cortex server is unreachable.",
        });
      });

    return () => controller.abort();
  }, [loadAttempt, workspaceId]);

  let content: ReactNode;

  if (state.kind === "loading") {
    content = (
      <div className="border-t border-border/20 px-6 py-6">
        <p role="status" className="sr-only">
          Loading workspace members…
        </p>
        <div aria-hidden="true" className="space-y-4">
          {[0, 1].map((row) => (
            <div key={row} className="flex animate-pulse items-center gap-4 py-1">
              <div className="size-10 rounded-full bg-surface-raised" />
              <div className="min-w-0 flex-1 space-y-2">
                <div className="h-3 w-36 rounded-full bg-surface-raised" />
                <div className="h-2.5 w-48 rounded-full bg-surface-raised/70" />
              </div>
              <div className="h-6 w-16 rounded-full bg-surface-raised" />
            </div>
          ))}
        </div>
      </div>
    );
  } else if (state.kind === "error") {
    content = (
      <div className="border-t border-border/20 px-6 pb-6">
        <FeedbackAlert message={state.message} />
        <button
          type="button"
          onClick={() => {
            setState({ kind: "loading" });
            setLoadAttempt((attempt) => attempt + 1);
          }}
          className="mt-3 text-sm font-semibold text-accent-bright transition-colors hover:text-foreground"
        >
          Try again
        </button>
      </div>
    );
  } else if (state.members.length === 0) {
    content = (
      <p className="border-t border-border/20 px-6 py-8 text-sm text-muted">
        No active members found.
      </p>
    );
  } else {
    const members = [...state.members].sort(
      (first, second) =>
        Number(second.user_id === currentUserId) -
        Number(first.user_id === currentUserId),
    );

    content = (
      <ul
        aria-label="Workspace members"
        tabIndex={0}
        className="max-h-[22rem] divide-y divide-border/20 overflow-y-auto overscroll-contain border-t border-border/20 focus-visible:outline-offset-[-3px]"
      >
        {members.map((member) => {
          const name = memberName(member);
          const isCurrentUser = member.user_id === currentUserId;

          return (
            <li key={member.user_id}>
              <button
                type="button"
                aria-haspopup="dialog"
                onClick={() => setActiveMember(member)}
                className="group grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-6 px-6 py-4 text-left transition-colors hover:bg-surface-raised/35"
              >
                <div className="flex min-w-0 items-center gap-4">
                  <span
                    aria-hidden="true"
                    className="flex size-10 shrink-0 items-center justify-center rounded-full border border-accent/20 bg-accent/10 text-[0.7rem] font-semibold tracking-wide text-accent-bright"
                  >
                    {memberInitials(member)}
                  </span>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-semibold text-foreground">
                        {name}
                      </span>
                      {isCurrentUser ? (
                        <span className="shrink-0 rounded-full bg-surface-raised px-2 py-0.5 text-[0.65rem] font-medium text-muted">
                          You
                        </span>
                      ) : null}
                    </div>
                    {member.name && member.email ? (
                      <p className="mt-0.5 truncate text-xs leading-5 text-subtle">
                        {member.email}
                      </p>
                    ) : null}
                  </div>
                </div>
                <span className="flex items-center gap-3">
                  <RoleBadge role={member.role} />
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 20 20"
                    className="size-4 text-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-muted"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m8 5 5 5-5 5" />
                  </svg>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section aria-labelledby="workspace-members-title">
      <div className="flex flex-wrap items-center justify-between gap-5 px-6 py-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h3
              id="workspace-members-title"
              className="text-sm font-semibold text-foreground"
            >
              Workspace members
            </h3>
            {state.kind === "ready" ? (
              <span className="rounded-full border border-border/30 bg-background/30 px-2 py-0.5 text-[0.65rem] font-medium text-subtle">
                {state.members.length}
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-xl text-sm leading-6 text-muted">
            People who can open and contribute to this workspace.
          </p>
        </div>
        {action}
      </div>
      {content}
      {activeMember ? (
        <MemberActionsDialog
          member={activeMember}
          workspaceId={workspaceId}
          currentUserId={currentUserId}
          currentRole={currentRole}
          permissions={permissions}
          onClose={() => setActiveMember(null)}
          onMemberUpdated={(updatedMember) => {
            setState((current) =>
              current.kind === "ready"
                ? {
                    kind: "ready",
                    members: current.members.map((member) =>
                      member.user_id === updatedMember.user_id
                        ? updatedMember
                        : member,
                    ),
                  }
                : current,
            );
            setActiveMember(updatedMember);
          }}
          onMemberRemoved={(userId) => {
            setState((current) =>
              current.kind === "ready"
                ? {
                    kind: "ready",
                    members: current.members.filter(
                      (member) => member.user_id !== userId,
                    ),
                  }
                : current,
            );
          }}
        />
      ) : null}
    </section>
  );
}

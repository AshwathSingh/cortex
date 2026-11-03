"use client";

import { useEffect, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { ApiError } from "@/lib/api";
import type { WorkspaceMember } from "@/lib/api-types";
import { listWorkspaceMembers } from "@/lib/member-client";

type MemberListState =
  | { kind: "loading" }
  | { kind: "ready"; members: WorkspaceMember[] }
  | { kind: "error"; message: string };

const joinedDate = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

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
}: {
  workspaceId: string;
  currentUserId?: string;
}) {
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [state, setState] = useState<MemberListState>({ kind: "loading" });

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

  if (state.kind === "loading") {
    return (
      <div className="px-6 py-5">
        <p role="status" className="sr-only">
          Loading workspace members…
        </p>
        <div aria-hidden="true" className="space-y-3">
          {[0, 1].map((row) => (
            <div key={row} className="flex animate-pulse items-center gap-3 py-1.5">
              <div className="size-9 rounded-full bg-surface-raised" />
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
  }

  if (state.kind === "error") {
    return (
      <div className="px-6 pb-5">
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
  }

  if (state.members.length === 0) {
    return (
      <p className="px-6 py-5 text-sm text-muted">
        No active members found.
      </p>
    );
  }

  return (
    <div className="px-6 py-5">
      <p className="mb-3 text-xs font-medium text-subtle">
        {state.members.length} active {state.members.length === 1 ? "member" : "members"}
      </p>
      <ul
        aria-label="Workspace members"
        className="divide-y divide-border/20 overflow-hidden rounded-xl border border-border/25 bg-background/20"
      >
        {state.members.map((member) => {
          const name = memberName(member);
          const isCurrentUser = member.user_id === currentUserId;

          return (
            <li
              key={member.user_id}
              className="flex min-w-0 items-center justify-between gap-4 px-4 py-3.5"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden="true"
                  className="flex size-9 shrink-0 items-center justify-center rounded-full border border-border/30 bg-surface-raised text-[0.68rem] font-semibold tracking-wide text-muted"
                >
                  {memberInitials(member)}
                </span>
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm font-medium text-foreground">
                      {name}
                    </span>
                    {isCurrentUser ? (
                      <span className="shrink-0 text-xs text-subtle">You</span>
                    ) : null}
                  </div>
                  <p className="truncate text-xs leading-5 text-subtle">
                    {member.name && member.email ? `${member.email} · ` : ""}
                    Joined {joinedDate.format(new Date(member.created_at))}
                  </p>
                </div>
              </div>
              <RoleBadge role={member.role} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

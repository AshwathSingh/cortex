"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  InviteMemberModal,
  type InviteRoleOption,
} from "@/components/workspaces/invite-member-modal";
import { ApiError } from "@/lib/api";
import type {
  WorkspacePermission,
  WorkspaceRoleDefinition,
} from "@/lib/api-types";
import {
  createWorkspaceInvite,
  listWorkspaceRoles,
} from "@/lib/invite-client";
import { assignableWorkspaceRoles } from "@/lib/workspace-role-options";

export function WorkspaceInviteAction({
  workspaceId,
  workspaceName,
  currentRole,
  permissions,
}: {
  workspaceId: string;
  workspaceName: string;
  currentRole: string;
  permissions: WorkspacePermission[];
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [roles, setRoles] = useState<WorkspaceRoleDefinition[]>([]);
  const [isLoadingRoles, setIsLoadingRoles] = useState(false);
  const [rolesError, setRolesError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();

    async function loadRoles() {
      setRoles([]);
      setRolesError(null);
      setIsLoadingRoles(true);
      try {
        setRoles(await listWorkspaceRoles(workspaceId, controller.signal));
      } catch (error) {
        if (controller.signal.aborted) return;
        setRolesError(
          error instanceof ApiError
            ? error.message
            : "Unable to load workspace roles.",
        );
      } finally {
        if (!controller.signal.aborted) setIsLoadingRoles(false);
      }
    }

    void loadRoles();
    return () => controller.abort();
  }, [isOpen, loadAttempt, workspaceId]);

  const roleOptions = useMemo(
    () => assignableWorkspaceRoles(roles, currentRole, permissions),
    [currentRole, permissions, roles],
  ) satisfies InviteRoleOption[];

  const availableRolesError =
    rolesError ??
    (!isLoadingRoles && roles.length > 0 && roleOptions.length === 0
      ? "You cannot grant any of the available roles."
      : null);

  return (
    <>
      <Button
        type="button"
        size="small"
        variant="primary"
        aria-haspopup="dialog"
        onClick={() => setIsOpen(true)}
      >
        Invite member
      </Button>
      {isOpen ? (
        <InviteMemberModal
          workspaceName={workspaceName}
          roles={roleOptions}
          rolesError={availableRolesError}
          isLoadingRoles={isLoadingRoles}
          onRetryRoles={() => setLoadAttempt((attempt) => attempt + 1)}
          onClose={() => setIsOpen(false)}
          onInvite={(email, selection) =>
            createWorkspaceInvite(workspaceId, { email, ...selection })
          }
        />
      ) : null}
    </>
  );
}

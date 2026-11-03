"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  InviteMemberModal,
  type InviteRoleOption,
  type InviteRoleSelection,
} from "@/components/workspaces/invite-member-modal";
import { ApiError } from "@/lib/api";
import type {
  WorkspacePermission,
  WorkspaceRole,
  WorkspaceRoleDefinition,
} from "@/lib/api-types";
import {
  createWorkspaceInvite,
  listWorkspaceRoles,
} from "@/lib/invite-client";

const BUILT_IN_ROLE_DESCRIPTIONS: Record<WorkspaceRole, string> = {
  OWNER: "Full workspace access",
  EDITOR: "Can contribute and sync sources",
  VIEWER: "Can view workspace knowledge",
};

function isBuiltInRole(name: string): name is WorkspaceRole {
  return name === "OWNER" || name === "EDITOR" || name === "VIEWER";
}

function roleName(role: WorkspaceRoleDefinition) {
  if (!role.built_in) return role.name;
  return `${role.name[0]}${role.name.slice(1).toLowerCase()}`;
}

function roleDescription(role: WorkspaceRoleDefinition) {
  if (isBuiltInRole(role.name)) return BUILT_IN_ROLE_DESCRIPTIONS[role.name];
  if (role.description) return role.description;
  return role.permissions.length === 0
    ? "Can view workspace knowledge"
    : `${role.permissions.length} workspace permission${role.permissions.length === 1 ? "" : "s"}`;
}

function canGrantRole(
  role: WorkspaceRoleDefinition,
  currentRole: string,
  permissions: WorkspacePermission[],
) {
  if (role.built_in && role.name === "OWNER") return currentRole === "OWNER";
  return role.permissions.every((permission) => permissions.includes(permission));
}

function toRoleOption(role: WorkspaceRoleDefinition): InviteRoleOption | null {
  let selection: InviteRoleSelection;
  if (role.built_in && isBuiltInRole(role.name)) {
    selection = { role: role.name };
  } else if (role.id) {
    selection = { role_id: role.id };
  } else {
    return null;
  }

  return {
    key: role.id ? `custom:${role.id}` : `builtin:${role.name}`,
    name: roleName(role),
    description: roleDescription(role),
    selection,
    isDefault: role.built_in && role.name === "EDITOR",
  };
}

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
    () =>
      roles
        .filter((role) => canGrantRole(role, currentRole, permissions))
        .map(toRoleOption)
        .filter((role): role is InviteRoleOption => role !== null),
    [currentRole, permissions, roles],
  );

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

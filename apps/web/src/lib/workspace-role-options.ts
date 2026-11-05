import type {
  WorkspacePermission,
  WorkspaceRole,
  WorkspaceRoleDefinition,
} from "@/lib/api-types";

export type WorkspaceRoleSelection =
  | { role: WorkspaceRole; role_id?: never }
  | { role?: never; role_id: string };

export type WorkspaceRoleOption = {
  key: string;
  name: string;
  description: string;
  selection: WorkspaceRoleSelection;
  isDefault?: boolean;
};

const BUILT_IN_ROLE_DESCRIPTIONS: Record<WorkspaceRole, string> = {
  OWNER: "Full workspace access",
  EDITOR: "Can contribute and sync sources",
  VIEWER: "Can view workspace knowledge",
};

function isBuiltInRole(name: string): name is WorkspaceRole {
  return name === "OWNER" || name === "EDITOR" || name === "VIEWER";
}

function canGrantRole(
  role: WorkspaceRoleDefinition,
  currentRole: string,
  permissions: WorkspacePermission[],
) {
  if (role.built_in && role.name === "OWNER") return currentRole === "OWNER";
  return role.permissions.every((permission) => permissions.includes(permission));
}

function toRoleOption(
  role: WorkspaceRoleDefinition,
): WorkspaceRoleOption | null {
  let selection: WorkspaceRoleSelection;
  if (role.built_in && isBuiltInRole(role.name)) {
    selection = { role: role.name };
  } else if (role.id) {
    selection = { role_id: role.id };
  } else {
    return null;
  }

  const name = role.built_in
    ? `${role.name[0]}${role.name.slice(1).toLowerCase()}`
    : role.name;
  const description = isBuiltInRole(role.name)
    ? BUILT_IN_ROLE_DESCRIPTIONS[role.name]
    : role.description ||
      (role.permissions.length === 0
        ? "Can view workspace knowledge"
        : `${role.permissions.length} workspace permission${role.permissions.length === 1 ? "" : "s"}`);

  return {
    key: role.id ? `custom:${role.id}` : `builtin:${role.name}`,
    name,
    description,
    selection,
    isDefault: role.built_in && role.name === "EDITOR",
  };
}

export function assignableWorkspaceRoles(
  roles: WorkspaceRoleDefinition[],
  currentRole: string,
  permissions: WorkspacePermission[],
) {
  return roles
    .filter((role) => canGrantRole(role, currentRole, permissions))
    .map(toRoleOption)
    .filter((role): role is WorkspaceRoleOption => role !== null);
}

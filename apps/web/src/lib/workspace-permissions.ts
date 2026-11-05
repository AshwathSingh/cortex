import type { WorkspacePermission } from "@/lib/api-types";

export function canManageSources(
  permissions: WorkspacePermission[] | null | undefined,
) {
  return permissions?.includes("sources.write") ?? false;
}

export function canManageMembers(
  permissions: WorkspacePermission[] | null | undefined,
) {
  return permissions?.includes("members.manage") ?? false;
}

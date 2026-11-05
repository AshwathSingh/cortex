import type { WorkspacePermission } from "@/lib/api-types";

/**
 * What the signed-in member may do in a workspace.
 *
 * Read from the `permissions` the API returns, not from the role name. US-21
 * added custom per-workspace roles: a role called "Librarian" may hold
 * `sources.write` while a built-in VIEWER does not, so comparing against
 * OWNER/EDITOR would hide controls the server would happily accept.
 *
 * The server re-checks every one of these; this only decides what to render.
 */
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

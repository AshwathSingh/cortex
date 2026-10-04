import type { WorkspaceRole } from "@/lib/api-types";

export function canManageSources(role: WorkspaceRole | null | undefined) {
  return role === "OWNER" || role === "EDITOR";
}

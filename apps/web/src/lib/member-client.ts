import { apiRequest } from "@/lib/api";
import type { WorkspaceMember } from "@/lib/api-types";
import type { WorkspaceRoleSelection } from "@/lib/workspace-role-options";

export function listWorkspaceMembers(
  workspaceId: string,
  signal?: AbortSignal,
) {
  return apiRequest<WorkspaceMember[]>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/members`,
    { signal },
  );
}

export function updateWorkspaceMemberRole(
  workspaceId: string,
  userId: string,
  selection: WorkspaceRoleSelection,
) {
  return apiRequest<WorkspaceMember>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}/role`,
    {
      method: "PATCH",
      body: JSON.stringify(selection),
    },
  );
}

export function removeWorkspaceMember(workspaceId: string, userId: string) {
  return apiRequest<void>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
}

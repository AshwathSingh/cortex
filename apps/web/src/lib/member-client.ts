import { apiRequest } from "@/lib/api";
import type { WorkspaceMember } from "@/lib/api-types";

export function listWorkspaceMembers(
  workspaceId: string,
  signal?: AbortSignal,
) {
  return apiRequest<WorkspaceMember[]>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/members`,
    { signal },
  );
}

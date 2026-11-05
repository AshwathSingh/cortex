import { apiRequest } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/api-types";

export type UpdateWorkspaceProfileInput = {
  name: string;
  description: string | null;
};

export function updateWorkspaceProfile(
  workspaceId: string,
  input: UpdateWorkspaceProfileInput,
) {
  return apiRequest<WorkspaceSummary>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}

export function deleteWorkspace(workspaceId: string, confirmName: string) {
  return apiRequest<void>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}`,
    {
      method: "DELETE",
      body: JSON.stringify({ confirm_name: confirmName }),
    },
  );
}

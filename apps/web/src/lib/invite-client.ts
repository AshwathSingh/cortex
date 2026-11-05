import { apiRequest } from "@/lib/api";
import type {
  WorkspaceInvite,
  WorkspaceInviteAcceptance,
  WorkspaceRole,
  WorkspaceRoleDefinition,
} from "@/lib/api-types";

export type CreateInviteInput = {
  email: string;
  role?: WorkspaceRole;
  role_id?: string;
};

export function listWorkspaceRoles(workspaceId: string, signal?: AbortSignal) {
  return apiRequest<WorkspaceRoleDefinition[]>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/roles`,
    { signal },
  );
}

export function createWorkspaceInvite(
  workspaceId: string,
  input: CreateInviteInput,
) {
  return apiRequest<WorkspaceInvite>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/invites`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function acceptWorkspaceInvite(token: string) {
  return apiRequest<WorkspaceInviteAcceptance>("/api/invites/accept", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

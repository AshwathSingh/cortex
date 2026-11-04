"use client";

import { useState } from "react";

import {
  SettingsSection,
  SettingsValue,
} from "@/components/settings/settings-section";
import {
  UnavailableAction,
} from "@/components/settings/settings-row";
import { Button } from "@/components/ui/button";
import { PageShell } from "@/components/ui/page-layout";
import { EditWorkspaceModal } from "@/components/workspaces/edit-workspace-modal";
import { useWorkspace } from "@/components/workspaces/workspace-context";
import { WorkspaceInviteAction } from "@/components/workspaces/workspace-invite-action";
import { WorkspaceMemberList } from "@/components/workspaces/workspace-member-list";
import { canManageMembers } from "@/lib/workspace-permissions";

export function WorkspaceSettings() {
  const {
    workspaceId,
    workspace,
    user,
    isLoading,
    updateWorkspace,
  } = useWorkspace();
  const [copied, setCopied] = useState(false);
  const [isEditingWorkspace, setIsEditingWorkspace] = useState(false);

  const workspaceName = workspace?.name ?? "Loading workspace…";
  const description = workspace?.description || "No description added";
  const isOwner = workspace?.role === "OWNER";
  const canInviteMembers = canManageMembers(workspace?.permissions);

  async function copyWorkspaceId() {
    try {
      await navigator.clipboard.writeText(workspaceId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <PageShell>
      <h1 id="workspace-settings-title" className="sr-only">
        Workspace settings
      </h1>

      {isLoading && !workspace ? (
        <div
          role="status"
          className="mt-10 rounded-2xl border border-border/30 bg-surface/55 px-6 py-10 text-sm text-muted"
        >
          Loading workspace settings…
        </div>
      ) : (
        <div className="space-y-5">
          <SettingsSection
            id="workspace-profile"
            title="Workspace profile"
            description="The shared identity members see across Cortex."
          >
            <div className="grid gap-5 px-6 py-5 sm:grid-cols-2">
              <SettingsValue label="Workspace name" value={workspaceName} />
              <SettingsValue label="Description" value={description} />
            </div>
            <div className="flex items-center justify-between gap-5 border-t border-border/20 px-6 py-4">
              <p className="text-xs leading-5 text-subtle">
                {isOwner
                  ? "Workspace details can be changed by owners."
                  : "Only workspace owners can change these details."}
              </p>
              {isOwner ? (
                <Button
                  type="button"
                  size="small"
                  variant="muted"
                  aria-haspopup="dialog"
                  onClick={() => setIsEditingWorkspace(true)}
                >
                  Edit details
                </Button>
              ) : (
                <UnavailableAction>Edit details</UnavailableAction>
              )}
            </div>
          </SettingsSection>

          <SettingsSection
            id="members-access"
            title="Members and access"
            description="Control who can open and contribute to this workspace."
          >
            <div>
              {workspace ? (
                <WorkspaceMemberList
                  key={workspaceId}
                  workspaceId={workspaceId}
                  currentUserId={user?.id}
                  currentRole={workspace.role}
                  permissions={workspace.permissions}
                  action={
                    canInviteMembers ? (
                      <WorkspaceInviteAction
                        workspaceId={workspaceId}
                        workspaceName={workspace.name}
                        currentRole={workspace.role}
                        permissions={workspace.permissions}
                      />
                    ) : undefined
                  }
                />
              ) : null}
            </div>
          </SettingsSection>

          <SettingsSection
            id="workspace-identifier"
            title="Workspace identifier"
            description="Use this stable identifier when connecting tools or reporting issues."
          >
            <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-5">
              <code className="break-all rounded-lg border border-border/25 bg-background/45 px-3 py-2 font-mono text-xs text-muted">
                {workspaceId}
              </code>
              <Button
                type="button"
                onClick={copyWorkspaceId}
                size="small"
                variant="muted"
              >
                {copied ? "Copied" : "Copy ID"}
              </Button>
            </div>
          </SettingsSection>

          <SettingsSection
            id="workspace-lifecycle"
            title={isOwner ? "Delete workspace" : "Leave workspace"}
            description={
              isOwner
                ? "Permanently remove this workspace and its project memory."
                : "Remove your access to this workspace."
            }
            danger
          >
            <div className="flex items-center justify-between gap-5 px-6 py-5">
              <p className="max-w-2xl text-sm leading-6 text-muted">
                {isOwner
                  ? "Deletion cannot be undone. Connected sources and graph data will also be removed."
                  : "You will need another member to invite you before you can return."}
              </p>
              <UnavailableAction danger>
                {isOwner ? "Delete workspace" : "Leave workspace"}
              </UnavailableAction>
            </div>
          </SettingsSection>

          {workspace && isEditingWorkspace ? (
            <EditWorkspaceModal
              workspace={workspace}
              onClose={() => setIsEditingWorkspace(false)}
              onSaved={(updated) => updateWorkspace?.(updated)}
            />
          ) : null}
        </div>
      )}
    </PageShell>
  );
}

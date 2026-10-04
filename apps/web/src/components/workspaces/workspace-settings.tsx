"use client";

import { useState } from "react";

import {
  SettingsSection,
  SettingsValue,
} from "@/components/settings/settings-section";
import {
  SettingsRow,
  UnavailableAction,
} from "@/components/settings/settings-row";
import { Button } from "@/components/ui/button";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { useWorkspace } from "@/components/workspaces/workspace-context";

export function WorkspaceSettings() {
  const { workspaceId, workspace, isLoading } = useWorkspace();
  const [copied, setCopied] = useState(false);

  const workspaceName = workspace?.name ?? "Loading workspace…";
  const description = workspace?.description || "No description added";
  const isOwner = workspace?.role === "OWNER";

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
      <PageHeader
        description={
          workspace
            ? `Manage identity, access, and lifecycle for ${workspaceName}.`
            : "Manage this workspace's identity, access, and lifecycle."
        }
        eyebrow="Workspace"
        headingId="workspace-settings-title"
        title="Workspace settings"
      />

      {isLoading && !workspace ? (
        <div
          role="status"
          className="mt-10 rounded-2xl border border-border/30 bg-surface/55 px-6 py-10 text-sm text-muted"
        >
          Loading workspace settings…
        </div>
      ) : (
        <div className="mt-10 space-y-5">
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
              <UnavailableAction>Edit details</UnavailableAction>
            </div>
          </SettingsSection>

          <SettingsSection
            id="members-access"
            title="Members and access"
            description="Control who can open and contribute to this workspace."
          >
            <div className="divide-y divide-border/20">
              <SettingsRow
                title="Your access"
                description="Your current permissions in this workspace."
                action={workspace ? <RoleBadge role={workspace.role} /> : null}
              />
              <SettingsRow
                title="Team members"
                description="Invite collaborators and assign workspace roles."
                action={<UnavailableAction>Manage members</UnavailableAction>}
              />
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
        </div>
      )}
    </PageShell>
  );
}

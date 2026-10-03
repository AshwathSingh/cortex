"use client";

import { useState } from "react";

import {
  SettingsSection,
  SettingsValue,
} from "@/components/settings/settings-section";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { useWorkspace } from "@/components/workspaces/workspace-context";

const unavailableActionClass =
  "min-h-9 shrink-0 cursor-not-allowed rounded-lg border border-border/30 px-3 text-xs font-semibold text-subtle opacity-60";

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
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <header>
          <p className="text-sm font-medium text-accent-bright">Workspace</p>
          <h1 className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]">
            Workspace settings
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
            {workspace
              ? `Manage identity, access, and lifecycle for ${workspaceName}.`
              : "Manage this workspace's identity, access, and lifecycle."}
          </p>
        </header>

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
              <button type="button" disabled className={unavailableActionClass}>
                Edit details
              </button>
            </div>
          </SettingsSection>

          <SettingsSection
            id="members-access"
            title="Members and access"
            description="Control who can open and contribute to this workspace."
          >
            <div className="flex items-center justify-between gap-5 px-6 py-5">
              <div>
                <h3 className="text-sm font-medium text-foreground">Your access</h3>
                <p className="mt-1 text-sm leading-6 text-muted">
                  Your current permissions in this workspace.
                </p>
              </div>
              {workspace ? <RoleBadge role={workspace.role} /> : null}
            </div>
            <div className="flex items-center justify-between gap-5 border-t border-border/20 px-6 py-5">
              <div>
                <h3 className="text-sm font-medium text-foreground">Team members</h3>
                <p className="mt-1 text-sm leading-6 text-muted">
                  Invite collaborators and assign workspace roles.
                </p>
              </div>
              <button type="button" disabled className={unavailableActionClass}>
                Manage members
              </button>
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
              <button
                type="button"
                onClick={copyWorkspaceId}
                className="min-h-9 shrink-0 rounded-lg border border-border/40 px-3 text-xs font-semibold text-muted transition-colors hover:border-border hover:bg-surface-raised hover:text-foreground"
              >
                {copied ? "Copied" : "Copy ID"}
              </button>
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
              <button
                type="button"
                disabled
                className="min-h-9 shrink-0 cursor-not-allowed rounded-lg border border-red-400/25 px-3 text-xs font-semibold text-red-300/60"
              >
                {isOwner ? "Delete workspace" : "Leave workspace"}
              </button>
            </div>
          </SettingsSection>
        </div>
        )}
      </div>
    </main>
  );
}

import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Manage workspace | Cortex",
  description: "Manage a Cortex workspace.",
};

export default async function ManageWorkspacePage({
  params,
}: PageProps<"/workspaces/[workspaceId]/manage">) {
  const { workspaceId } = await params;

  return (
    <WorkspaceRoutePlaceholder
      workspaceId={workspaceId}
      eyebrow="Workspace settings"
      title="Manage"
      description="Manage workspace settings, access, and project configuration."
    />
  );
}

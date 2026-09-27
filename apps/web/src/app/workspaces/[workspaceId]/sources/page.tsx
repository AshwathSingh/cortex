import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Sources | Cortex",
  description: "Manage source data for a Cortex workspace.",
};

export default async function SourcesPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/sources">) {
  const { workspaceId } = await params;

  return (
    <WorkspaceRoutePlaceholder
      workspaceId={workspaceId}
      eyebrow="Workspace sources"
      title="Sources"
      description="Connect and manage the source data that powers this workspace."
    />
  );
}

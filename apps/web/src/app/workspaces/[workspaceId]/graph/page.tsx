import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Graph | Cortex",
  description: "Explore the relationships in a Cortex workspace.",
};

export default async function GraphPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/graph">) {
  const { workspaceId } = await params;

  return (
    <WorkspaceRoutePlaceholder
      workspaceId={workspaceId}
      eyebrow="Workspace graph"
      title="Graph"
      description="Explore project decisions, evidence, and their relationships."
    />
  );
}

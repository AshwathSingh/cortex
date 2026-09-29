import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Graph | Cortex",
  description: "Explore the relationships in a Cortex workspace.",
};

export default function GraphPage() {
  return (
    <WorkspaceRoutePlaceholder
      eyebrow="Workspace graph"
      title="Graph"
      description="Explore project decisions, evidence, and their relationships."
    />
  );
}

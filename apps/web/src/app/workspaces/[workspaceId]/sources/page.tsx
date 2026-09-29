import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Sources | Cortex",
  description: "Manage source data for a Cortex workspace.",
};

export default function SourcesPage() {
  return (
    <WorkspaceRoutePlaceholder
      eyebrow="Workspace sources"
      title="Sources"
      description="Connect and manage the source data that powers this workspace."
    />
  );
}

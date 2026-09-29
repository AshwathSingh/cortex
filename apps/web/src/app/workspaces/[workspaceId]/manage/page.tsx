import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Workspace settings | Cortex",
  description: "Manage a Cortex workspace.",
};

export default function ManageWorkspacePage() {
  return (
    <WorkspaceRoutePlaceholder
      eyebrow="Workspace settings"
      title="Workspace settings"
      description="Manage workspace settings, access, and project configuration."
    />
  );
}

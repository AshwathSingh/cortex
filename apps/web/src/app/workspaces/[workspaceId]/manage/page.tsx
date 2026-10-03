import type { Metadata } from "next";

import { WorkspaceSettings } from "@/components/workspaces/workspace-settings";

export const metadata: Metadata = {
  title: "Workspace settings | Cortex",
  description: "Manage a Cortex workspace.",
};

export default function ManageWorkspacePage() {
  return <WorkspaceSettings />;
}

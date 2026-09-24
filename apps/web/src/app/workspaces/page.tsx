import type { Metadata } from "next";

import { WorkspaceSelector } from "@/components/workspaces/workspace-selector";

export const metadata: Metadata = {
  title: "Workspaces | Cortex",
  description: "Choose a Cortex workspace.",
};

export default function WorkspacesPage() {
  return <WorkspaceSelector />;
}

import type { Metadata } from "next";

import { WorkspaceDetail } from "@/components/workspaces/workspace-detail";

export const metadata: Metadata = {
  title: "Workspace | Cortex",
  description: "View a Cortex workspace.",
};

export default async function WorkspacePage({
  params,
}: PageProps<"/workspaces/[workspaceId]">) {
  const { workspaceId } = await params;
  return <WorkspaceDetail workspaceId={workspaceId} />;
}

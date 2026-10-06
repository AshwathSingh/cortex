import type { Metadata } from "next";

import { WorkspaceDetail } from "@/components/workspaces/workspace-detail";

export const metadata: Metadata = {
  title: "Home | Cortex",
  description: "Ask Cortex about your workspace.",
};

export default async function WorkspacePage({
  params,
}: PageProps<"/workspaces/[workspaceId]">) {
  const { workspaceId } = await params;
  return <WorkspaceDetail workspaceId={workspaceId} />;
}

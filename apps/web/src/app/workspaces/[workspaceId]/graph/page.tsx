import type { Metadata } from "next";

import { GraphExplorer } from "@/components/graph/graph-explorer";

export const metadata: Metadata = {
  title: "Graph Explorer | Cortex",
  description: "View a Cortex workspace's knowledge base as a visual graph.",
};

export default async function GraphPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/graph">) {
  const { workspaceId } = await params;
  return <GraphExplorer workspaceId={workspaceId} />;
}

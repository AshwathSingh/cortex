import type { Metadata } from "next";

import { SourceInventory } from "@/components/sources/source-inventory";

export const metadata: Metadata = {
  title: "Sources | Cortex",
  description: "View the repositories connected to a Cortex workspace.",
};

export default async function SourcesPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/sources">) {
  const { workspaceId } = await params;
  return <SourceInventory workspaceId={workspaceId} />;
}

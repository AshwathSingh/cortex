import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Review | Cortex",
  description: "Review flagged issues in a Cortex workspace.",
};

export default async function ReviewPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/review">) {
  const { workspaceId } = await params;

  return (
    <WorkspaceRoutePlaceholder
      workspaceId={workspaceId}
      eyebrow="Workspace review"
      title="Review"
      description="Review contradictions, unresolved questions, and other flagged issues."
    />
  );
}

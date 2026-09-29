import type { Metadata } from "next";

import { WorkspaceRoutePlaceholder } from "@/components/workspaces/workspace-route-placeholder";

export const metadata: Metadata = {
  title: "Review queue | Cortex",
  description: "Review flagged issues in a Cortex workspace.",
};

export default function ReviewPage() {
  return (
    <WorkspaceRoutePlaceholder
      eyebrow="Workspace review"
      title="Review queue"
      description="Review contradictions, unresolved questions, and other flagged issues."
    />
  );
}

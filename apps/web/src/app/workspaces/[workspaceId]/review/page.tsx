import type { Metadata } from "next";

import { ReviewQueue } from "@/components/review/review-queue";

export const metadata: Metadata = {
  title: "Review queue | Cortex",
  description: "Review flagged issues in a Cortex workspace.",
};

export default async function ReviewPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/review">) {
  const { workspaceId } = await params;
  return <ReviewQueue workspaceId={workspaceId} />;
}

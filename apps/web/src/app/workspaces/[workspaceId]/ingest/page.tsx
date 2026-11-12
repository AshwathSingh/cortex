import type { Metadata } from "next";

import { RepoIngestForm } from "@/components/ingest/repo-ingest-form";
import { PageShell } from "@/components/ui/page-layout";

export const metadata: Metadata = {
  title: "Connect GitHub | Cortex",
  description: "Connect GitHub to a Cortex workspace.",
};

export default async function IngestPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/ingest">) {
  const { workspaceId } = await params;
  return (
    <PageShell>
      <RepoIngestForm workspaceId={workspaceId} />
    </PageShell>
  );
}

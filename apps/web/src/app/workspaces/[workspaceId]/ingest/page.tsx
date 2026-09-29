import type { Metadata } from "next";

import { RepoIngestForm } from "@/components/ingest/repo-ingest-form";

export const metadata: Metadata = {
  title: "Add repository | Cortex",
  description: "Add a GitHub repository to a Cortex workspace.",
};

export default async function IngestPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/ingest">) {
  const { workspaceId } = await params;
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-12">
      <div className="mx-auto max-w-[38rem]">
        <RepoIngestForm workspaceId={workspaceId} />
      </div>
    </main>
  );
}

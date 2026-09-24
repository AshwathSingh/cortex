import type { Metadata } from "next";

import { RepoIngestForm } from "@/components/ingest/repo-ingest-form";

export const metadata: Metadata = {
  title: "Add repository | Cortex",
  description: "Add a GitHub repository to Cortex.",
};

export default function IngestPage() {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-12">
      <div className="mx-auto max-w-[38rem]">
        <RepoIngestForm />
      </div>
    </main>
  );
}

import type { Metadata } from "next";

import { CreateWorkspaceForm } from "@/components/workspaces/create-workspace-form";

export const metadata: Metadata = {
  title: "New workspace | Cortex",
  description: "Create a Cortex workspace.",
};

export default function NewWorkspacePage() {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto max-w-[38rem]">
        <CreateWorkspaceForm />
      </div>
    </main>
  );
}

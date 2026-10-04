import type { Metadata } from "next";

import { PageShell } from "@/components/ui/page-layout";
import { CreateWorkspaceForm } from "@/components/workspaces/create-workspace-form";

export const metadata: Metadata = {
  title: "New workspace | Cortex",
  description: "Create a Cortex workspace.",
};

export default function NewWorkspacePage() {
  return (
    <PageShell width="form">
      <CreateWorkspaceForm />
    </PageShell>
  );
}

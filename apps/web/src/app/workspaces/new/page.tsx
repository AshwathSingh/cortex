import type { Metadata } from "next";

import { PageShell } from "@/components/ui/page-layout";
import { CreateWorkspaceForm } from "@/components/workspaces/create-workspace-form";
import { routes } from "@/lib/routes";

export const metadata: Metadata = {
  title: "New workspace | Cortex",
  description: "Create a Cortex workspace.",
};

export default async function NewWorkspacePage({
  searchParams,
}: PageProps<"/workspaces/new">) {
  const { from } = await searchParams;
  const workspaceId = typeof from === "string" ? from : null;

  return (
    <PageShell width="form">
      <CreateWorkspaceForm
        backHref={workspaceId ? routes.workspace.home(workspaceId) : undefined}
      />
    </PageShell>
  );
}

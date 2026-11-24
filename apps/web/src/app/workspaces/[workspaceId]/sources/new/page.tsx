import type { Metadata } from "next";
import { SourceChooser } from "@/components/sources/source-chooser";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import { routes } from "@/lib/routes";

export const metadata: Metadata = {
  title: "Add source | Cortex",
  description:
    "Choose a repository, document or chat channel to add to Cortex.",
};
export default async function AddSourcePage({
  params,
}: PageProps<"/workspaces/[workspaceId]/sources/new">) {
  const { workspaceId } = await params;
  return (
    <PageShell>
      <PageHeader
        headingId="add-source-title"
        backHref={routes.workspace.sources(workspaceId)}
        backLabel="Back to sources"
        eyebrow="Knowledge inputs"
        title="Add a source"
        description="Choose what Cortex should use to build this workspace's project memory."
      />
      <SourceChooser workspaceId={workspaceId} />
    </PageShell>
  );
}

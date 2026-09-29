import { WorkspaceShell } from "@/components/workspaces/workspace-shell";

export default async function WorkspaceLayout({
  children,
  params,
}: LayoutProps<"/workspaces/[workspaceId]">) {
  const { workspaceId } = await params;

  return <WorkspaceShell workspaceId={workspaceId}>{children}</WorkspaceShell>;
}

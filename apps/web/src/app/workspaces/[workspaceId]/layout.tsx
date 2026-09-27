export default async function WorkspaceLayout({
  children,
  params,
}: LayoutProps<"/workspaces/[workspaceId]">) {
  const { workspaceId } = await params;

  return <div data-workspace-id={workspaceId}>{children}</div>;
}

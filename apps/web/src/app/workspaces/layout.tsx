import { redirectUnauthenticatedUser } from "@/lib/server-auth";

export default async function WorkspacesLayout({
  children,
}: LayoutProps<"/workspaces">) {
  await redirectUnauthenticatedUser();

  return children;
}

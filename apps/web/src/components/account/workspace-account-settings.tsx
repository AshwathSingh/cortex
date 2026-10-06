"use client";

import { AccountSettings } from "@/components/account/account-settings";
import { useWorkspace } from "@/components/workspaces/workspace-context";

export function WorkspaceAccountSettings() {
  const { user } = useWorkspace();

  return <AccountSettings user={user} />;
}

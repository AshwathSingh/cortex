import type { Metadata } from "next";

import { WorkspaceAccountSettings } from "@/components/account/workspace-account-settings";

export const metadata: Metadata = {
  title: "Account | Cortex",
  description: "Manage your Cortex account.",
};

export default function WorkspaceAccountPage() {
  return <WorkspaceAccountSettings />;
}

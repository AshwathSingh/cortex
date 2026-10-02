import type { Metadata } from "next";

import { AccountSettings } from "@/components/account/account-settings";

export const metadata: Metadata = {
  title: "Account | Cortex",
  description: "Manage your Cortex account.",
};

export default function WorkspaceAccountPage() {
  return <AccountSettings />;
}

import type { Metadata } from "next";

import { StandaloneAccountSettings } from "@/components/account/standalone-account-settings";

export const metadata: Metadata = {
  title: "Account | Cortex",
  description: "Manage your Cortex account.",
};

export default function AccountPage() {
  return <StandaloneAccountSettings />;
}

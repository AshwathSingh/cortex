import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { AcceptInvite } from "@/components/workspaces/accept-invite";

export const metadata: Metadata = {
  title: "Accept workspace invitation | Cortex",
  description: "Join a shared Cortex workspace.",
};

export default function AcceptInvitePage() {
  return (
    <AuthShell>
      <AcceptInvite />
    </AuthShell>
  );
}

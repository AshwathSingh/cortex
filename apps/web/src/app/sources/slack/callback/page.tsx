import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { ChatInstallCallback } from "@/components/sources/chat-install-callback";

export const metadata: Metadata = {
  title: "Connecting Slack | Cortex",
  description: "Completing the Slack connection.",
};

function first(value: string | string[] | undefined): string | null {
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

export default async function SlackCallbackPage({
  searchParams,
}: PageProps<"/sources/slack/callback">) {
  const params = await searchParams;
  return (
    <AuthShell>
      <ChatInstallCallback
        provider="slack"
        code={first(params.code)}
        state={first(params.state)}
        error={first(params.error)}
      />
    </AuthShell>
  );
}

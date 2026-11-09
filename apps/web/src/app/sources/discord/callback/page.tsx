import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { ChatInstallCallback } from "@/components/sources/chat-install-callback";

export const metadata: Metadata = {
  title: "Connecting Discord | Cortex",
  description: "Completing the Discord connection.",
};

function first(value: string | string[] | undefined): string | null {
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

export default async function DiscordCallbackPage({
  searchParams,
}: PageProps<"/sources/discord/callback">) {
  const params = await searchParams;
  return (
    <AuthShell>
      <ChatInstallCallback
        provider="discord"
        code={first(params.code)}
        state={first(params.state)}
        error={first(params.error)}
      />
    </AuthShell>
  );
}

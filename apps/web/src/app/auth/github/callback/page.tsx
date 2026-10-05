import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { GitHubCallback } from "@/components/auth/github-callback";

export const metadata: Metadata = {
  title: "Signing in | Cortex",
  description: "Completing GitHub sign-in.",
};

function first(value: string | string[] | undefined): string | null {
  return (Array.isArray(value) ? value[0] : value) ?? null;
}

export default async function GitHubCallbackPage({
  searchParams,
}: PageProps<"/auth/github/callback">) {
  const params = await searchParams;
  return (
    <AuthShell>
      <GitHubCallback
        code={first(params.code)}
        state={first(params.state)}
        error={first(params.error)}
      />
    </AuthShell>
  );
}

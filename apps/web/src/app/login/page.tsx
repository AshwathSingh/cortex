import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/login-form";
import { redirectAuthenticatedUser } from "@/lib/server-auth";

export const metadata: Metadata = {
  title: "Log in | Cortex",
  description: "Return to your Cortex workspace and project memory.",
};

export default async function LoginPage() {
  await redirectAuthenticatedUser();

  return (
    <AuthShell>
      <LoginForm />
    </AuthShell>
  );
}

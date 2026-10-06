import type { Metadata } from "next";

import { AuthShell } from "@/components/auth/auth-shell";
import { SignupForm } from "@/components/auth/signup-form";
import { redirectAuthenticatedUser } from "@/lib/server-auth";

export const metadata: Metadata = {
  title: "Create your account | Cortex",
  description: "Create a Cortex workspace for durable engineering memory.",
};

export default async function SignupPage() {
  await redirectAuthenticatedUser();

  return (
    <AuthShell>
      <SignupForm />
    </AuthShell>
  );
}

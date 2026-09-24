"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import {
  AuthFormLayout,
  AuthFormError,
  AuthSubmitButton,
  FormField,
} from "@/components/auth/auth-form-primitives";
import { ApiError, apiRequest } from "@/lib/api";

type AuthenticatedUser = {
  id: string;
  email: string;
  display_name: string | null;
};

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    try {
      await apiRequest<AuthenticatedUser>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: formData.get("email"),
          password: formData.get("password"),
        }),
      });
      router.replace("/workspaces");
      router.refresh();
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to reach Cortex. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthFormLayout
      headingId="login-form-heading"
      title="Welcome back"
      description="Return to your workspace with your project context intact."
      switchPrompt="New to Cortex?"
      switchHref="/signup"
      switchLabel="Create an account"
    >
      <form onSubmit={handleSubmit}>
        <fieldset className="space-y-6">
          <legend className="sr-only">Login details</legend>
          <FormField
            id="login-email"
            label="Email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="you@example.com"
            required
          />
          <FormField
            id="login-password"
            label="Password"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="Enter your password"
            required
          />
        </fieldset>
        <AuthFormError message={error} />
        <AuthSubmitButton disabled={isSubmitting}>
          {isSubmitting ? "Logging in…" : "Log in"}
        </AuthSubmitButton>
      </form>
    </AuthFormLayout>
  );
}

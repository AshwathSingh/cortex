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

/** Developer-focused account flow with GitHub and email options. */
export function SignupForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    try {
      await apiRequest<AuthenticatedUser>("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          display_name: formData.get("display_name") || null,
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
      headingId="signup-form-heading"
      title="Create your account"
      description="Bring your project context together in one private workspace."
      switchPrompt="Already have an account?"
      switchHref="/login"
      switchLabel="Log in"
    >
      <form onSubmit={handleSubmit}>
        <fieldset className="space-y-6">
          <legend className="sr-only">Account details</legend>
          <FormField
            id="signup-name"
            label="Name"
            name="display_name"
            type="text"
            autoComplete="name"
            maxLength={100}
            placeholder="Your name"
          />
          <FormField
            id="signup-email"
            label="Email"
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="you@example.com"
            required
          />
          <FormField
            id="signup-password"
            label="Password"
            hint="At least 15 characters"
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={15}
            maxLength={128}
            placeholder="Create a secure password"
            required
          />
        </fieldset>
        <AuthFormError message={error} />
        <AuthSubmitButton disabled={isSubmitting}>
          {isSubmitting ? "Creating account…" : "Create account"}
        </AuthSubmitButton>
      </form>
    </AuthFormLayout>
  );
}

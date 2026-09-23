"use client";

import type { FormEvent } from "react";

import {
  AuthFormLayout,
  AuthSubmitButton,
  FormField,
} from "@/components/auth/auth-form-primitives";

/** Developer-focused account flow with GitHub and email options. */
export function SignupForm() {
  function preventPrototypeSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
      <form onSubmit={preventPrototypeSubmission}>
        <fieldset className="space-y-6">
          <legend className="sr-only">Account details</legend>
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
        <AuthSubmitButton>Create account</AuthSubmitButton>
      </form>
    </AuthFormLayout>
  );
}

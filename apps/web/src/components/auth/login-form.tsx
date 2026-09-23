"use client";

import type { FormEvent } from "react";

import {
  AuthFormLayout,
  AuthSubmitButton,
  FormField,
} from "@/components/auth/auth-form-primitives";

export function LoginForm() {
  function preventPrototypeSubmission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
      <form onSubmit={preventPrototypeSubmission}>
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
        <AuthSubmitButton>Log in</AuthSubmitButton>
      </form>
    </AuthFormLayout>
  );
}

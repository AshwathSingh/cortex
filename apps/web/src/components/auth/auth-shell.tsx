import Link from "next/link";
import type { ReactNode } from "react";

import { AuthProductPreview } from "@/components/auth/auth-product-preview";

type AuthShellProps = {
  children: ReactNode;
};

/**
 * Authentication-page template: a focused account flow paired with a visual
 * product trailer that demonstrates the experience awaiting new users.
 */
export function AuthShell({ children }: AuthShellProps) {
  return (
    <main className="min-h-screen">
      <div className="relative min-h-screen w-full">
        <header className="absolute inset-x-0 top-0 z-20 mx-auto max-w-[var(--cortex-content-width)] px-[var(--cortex-page-gutter)] pt-5 sm:pt-6">
          <nav className="-mx-5 flex h-[4.5rem] items-center justify-between gap-4 px-4 sm:px-7 lg:w-[calc(58%+1.25rem)]">
            <Link
              href="/"
              aria-label="Cortex home"
              className="flex min-h-11 items-center rounded-md text-[1.35rem] font-semibold tracking-[-0.025em] text-foreground transition-colors hover:text-accent-bright"
            >
              Cortex
            </Link>
            <Link
              href="/"
              className="flex min-h-11 items-center gap-2 rounded-md text-sm font-medium text-muted transition-colors hover:text-foreground"
            >
              <span aria-hidden="true">←</span>
              Back to home
            </Link>
          </nav>
        </header>

        <div className="grid min-h-screen lg:grid-cols-[minmax(0,58fr)_minmax(30rem,42fr)]">
          <div className="auth-form-column flex items-center justify-center px-6 pb-14 pt-32 sm:px-10 lg:py-32">
            {children}
          </div>
          <AuthProductPreview />
        </div>
      </div>
    </main>
  );
}

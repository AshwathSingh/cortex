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
      <div className="mx-auto min-h-screen max-w-[var(--cortex-content-width)]">
        <header className="flex h-20 items-center justify-between px-[var(--cortex-page-gutter)]">
          <Link
            href="/"
            aria-label="Cortex home"
            className="rounded-md text-xl font-semibold tracking-[-0.025em] text-foreground transition-colors hover:text-accent-bright"
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
        </header>

        <div className="grid gap-10 px-[var(--cortex-page-gutter)] pb-8 lg:min-h-[calc(100vh-6.5rem)] lg:grid-cols-[minmax(22rem,0.82fr)_minmax(32rem,1.18fr)] lg:items-stretch lg:gap-12">
          <div className="flex items-center justify-center py-10 lg:py-12">
            {children}
          </div>
          <AuthProductPreview />
        </div>
      </div>
    </main>
  );
}

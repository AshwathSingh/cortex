import type { Metadata } from "next";
import Link from "next/link";

import { routes } from "@/lib/routes";

export const metadata: Metadata = {
  title: "Account | Cortex",
  description: "Manage your Cortex account.",
};

export default function AccountPage() {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <Link
          href={routes.workspaces}
          className="text-sm font-medium text-muted transition-colors hover:text-foreground"
        >
          ← All workspaces
        </Link>
        <section className="mt-10" aria-labelledby="account-title">
          <p className="text-sm font-medium text-accent-bright">User settings</p>
          <h1
            id="account-title"
            className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]"
          >
            Account
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
            Manage your Cortex profile and account preferences.
          </p>
        </section>
      </div>
    </main>
  );
}

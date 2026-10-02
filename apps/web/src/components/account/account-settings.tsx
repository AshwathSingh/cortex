import Link from "next/link";

type AccountSettingsProps = {
  backHref?: string;
  backLabel?: string;
};

export function AccountSettings({ backHref, backLabel }: AccountSettingsProps) {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        {backHref && backLabel ? (
          <Link
            href={backHref}
            className="text-sm font-medium text-muted transition-colors hover:text-foreground"
          >
            ← {backLabel}
          </Link>
        ) : null}

        <section className={backHref ? "mt-10" : undefined} aria-labelledby="account-title">
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

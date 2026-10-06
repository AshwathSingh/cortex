import Link from "next/link";
import type { ReactNode } from "react";

const contentWidths = {
  default: "max-w-[64rem]",
  form: "max-w-[38rem]",
} as const;

export function PageShell({
  children,
  width = "default",
}: {
  children: ReactNode;
  width?: keyof typeof contentWidths;
}) {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className={`mx-auto w-full ${contentWidths[width]}`}>{children}</div>
    </main>
  );
}

export function PageHeader({
  action,
  backHref,
  backLabel,
  description,
  eyebrow,
  headingId,
  title,
}: {
  action?: ReactNode;
  backHref?: string;
  backLabel?: string;
  description: ReactNode;
  eyebrow?: ReactNode;
  headingId: string;
  title: ReactNode;
}) {
  const backLink =
    backHref && backLabel ? { href: backHref, label: backLabel } : null;

  return (
    <>
      {backLink ? (
        <Link
          href={backLink.href}
          className="text-sm font-medium text-muted transition-colors hover:text-foreground"
        >
          ← {backLink.label}
        </Link>
      ) : null}

      <header
        className={`${backLink ? "mt-10 " : ""}flex flex-wrap items-end justify-between gap-6`}
      >
        <div>
          {eyebrow ? (
            <p className="text-sm font-medium text-accent-bright">{eyebrow}</p>
          ) : null}
          <h1
            id={headingId}
            className={`${eyebrow ? "mt-3 " : ""}text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]`}
          >
            {title}
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
            {description}
          </p>
        </div>
        {action}
      </header>
    </>
  );
}

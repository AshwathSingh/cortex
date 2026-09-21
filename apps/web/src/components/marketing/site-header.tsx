import Link from "next/link";

const primaryLinks = [
  { href: "#product", label: "Product" },
  { href: "#principles", label: "Principles" },
  { href: "#docs", label: "Docs" },
] as const;

/**
 * Homepage navigation template: the rounded top bar containing the Cortex
 * wordmark, primary page links, login action, and main signup call to action.
 */
export function SiteHeader() {
  return (
    <header className="mx-auto max-w-[var(--cortex-content-width)] px-[var(--cortex-page-gutter)] pt-5 sm:pt-6">
      <nav
        aria-label="Primary navigation"
        className="-mx-5 flex h-[4.5rem] w-[calc(100%+2.5rem)] items-center justify-between gap-4 rounded-[1.25rem] border border-border bg-surface/90 px-4 shadow-[0_18px_60px_rgb(0_0_0/18%)] backdrop-blur-xl sm:px-7"
      >
        <Link
          href="/"
          aria-label="Cortex home"
          className="flex min-h-11 items-center rounded-md text-[1.35rem] font-semibold tracking-[-0.025em] text-foreground transition-colors hover:text-accent-bright"
        >
          Cortex
        </Link>

        <div className="ml-auto hidden items-center gap-1 lg:flex">
          {primaryLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="flex min-h-11 items-center rounded-lg px-4 text-[0.95rem] font-medium text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="hidden min-h-11 items-center justify-center rounded-control border border-border px-5 text-[0.95rem] font-medium text-foreground transition-colors hover:bg-surface-raised md:flex"
          >
            Log in
          </Link>
          <Link
            href="/signup"
            aria-label="Start building memory"
            className="flex min-h-11 items-center justify-center rounded-control bg-accent px-5 text-[0.95rem] font-semibold text-foreground transition-colors hover:bg-accent-hover sm:px-6"
          >
            <span aria-hidden="true" className="sm:hidden">
              Start
            </span>
            <span aria-hidden="true" className="hidden sm:inline">
              Start building memory
            </span>
          </Link>
        </div>
      </nav>
    </header>
  );
}

import Link from "next/link";

const primaryLinks = [
  { href: "#product", label: "Product" },
  { href: "#principles", label: "Principles" },
] as const;

/**
 * Homepage navigation template: the rounded top bar containing the Cortex
 * wordmark, primary page links, login action, and main signup call to action.
 */
export function SiteHeader() {
  return (
    <header className="mx-auto max-w-[var(--cortex-content-width)] px-[var(--cortex-page-gutter)] pt-3 sm:pt-4">
      <nav
        aria-label="Primary navigation"
        className="grid h-16 grid-cols-[auto_1fr] items-center gap-5 border-b border-border/30 lg:grid-cols-[1fr_auto_1fr]"
      >
        <Link
          href="/"
          aria-label="Cortex home"
          className="flex min-h-11 items-center rounded-md text-[1.35rem] font-semibold tracking-[-0.025em] text-foreground transition-colors hover:text-accent-bright"
        >
          Cortex
        </Link>

        <div className="hidden items-center justify-center gap-1 lg:flex">
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

        <div className="ml-auto flex items-center gap-2 sm:gap-3 lg:ml-0 lg:justify-self-end">
          <Link
            href="/login"
            className="flex min-h-11 items-center justify-center rounded-md px-2 text-sm font-medium text-muted transition-colors hover:text-foreground sm:px-4 sm:text-[0.95rem]"
          >
            Log in
          </Link>
          <Link
            href="/signup"
            aria-label="Ask Cortex"
            className="flex min-h-11 items-center justify-center rounded-control bg-accent px-4 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover sm:px-5 sm:text-[0.95rem]"
          >
            Ask Cortex
          </Link>
        </div>
      </nav>
    </header>
  );
}

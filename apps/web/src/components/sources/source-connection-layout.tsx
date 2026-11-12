import Link from "next/link";
import type { ReactNode } from "react";

export type SourceDataItem = {
  label: string;
  description: string;
};

export function SourceConnectionLayout({
  backHref,
  backLabel,
  children,
  controls,
  dataDescription,
  dataItems,
  dataTitle,
  description,
  methodDescription,
  methodTitle,
  sourceName,
  workspaceName,
}: {
  backHref: string;
  backLabel: string;
  children: ReactNode;
  controls?: ReactNode;
  dataDescription: string;
  dataItems: readonly SourceDataItem[];
  dataTitle: string;
  description: string;
  methodDescription: string;
  methodTitle: string;
  sourceName: string;
  workspaceName: string;
}) {
  return (
    <section
      aria-labelledby="source-connection-title"
      className="mx-auto max-w-4xl"
    >
      <Link
        href={backHref}
        className="text-sm font-medium text-muted transition-colors hover:text-foreground"
      >
        ← {backLabel}
      </Link>

      <header className="mt-8 max-w-2xl">
        <h1
          id="source-connection-title"
          className="text-3xl font-semibold leading-tight tracking-[-0.035em] text-foreground sm:text-[2.5rem]"
        >
          Connect {sourceName}
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted">
          to <span className="font-medium text-foreground">{workspaceName}</span>
        </p>
        <p className="mt-4 max-w-xl text-sm leading-6 text-muted">
          {description}
        </p>
      </header>

      <div className="mt-10 border-t border-border/30">
        <section
          aria-labelledby="connection-method-heading"
          className="grid gap-5 border-b border-border/30 py-8 md:grid-cols-[11rem_minmax(0,1fr)] md:gap-10"
        >
          <div>
            <h2
              id="connection-method-heading"
              className="text-base font-semibold text-foreground"
            >
              {methodTitle}
            </h2>
            <p className="mt-2 text-xs leading-5 text-muted">
              {methodDescription}
            </p>
          </div>
          <div className="min-w-0">{children}</div>
        </section>

        <section
          aria-labelledby="source-data-heading"
          className="grid gap-5 border-b border-border/30 py-8 md:grid-cols-[11rem_minmax(0,1fr)] md:gap-10"
        >
          <div>
            <h2
              id="source-data-heading"
              className="text-base font-semibold text-foreground"
            >
              {dataTitle}
            </h2>
            <p className="mt-2 text-xs leading-5 text-muted">
              {dataDescription}
            </p>
          </div>

          <div className="min-w-0">
            <ul className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
              {dataItems.map((item) => (
                <li key={item.label} className="border-l border-border/30 pl-4">
                  <p className="text-sm font-medium text-foreground">
                    {item.label}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    {item.description}
                  </p>
                </li>
              ))}
            </ul>
            {controls ? (
              <div className="mt-7 border-t border-border/20 pt-6">
                {controls}
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </section>
  );
}

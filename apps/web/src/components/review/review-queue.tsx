import Link from "next/link";

import { routes } from "@/lib/routes";

export type ReviewItem = {
  id: string;
  title: string;
  summary: string;
  kind: "Contradiction" | "Evidence gap" | "Unresolved question";
  priority: "High" | "Medium" | "Low";
  sourceCount: number;
};

function ReviewIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-5">
      <path d="M12 3 2.8 19h18.4L12 3Z" />
      <path d="M12 9v4M12 16.5h.01" />
    </svg>
  );
}

const priorityStyles: Record<ReviewItem["priority"], string> = {
  High: "border-red-400/25 bg-red-400/10 text-red-300",
  Medium: "border-amber-400/25 bg-amber-400/10 text-amber-200",
  Low: "border-border/35 bg-surface-raised text-muted",
};

export function ReviewQueue({ workspaceId, items = [] }: { workspaceId: string; items?: ReviewItem[] }) {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <header>
          <p className="text-sm font-medium text-accent-bright">Project signals</p>
          <h1 className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]">Review queue</h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">Investigate contradictions, missing evidence, and unresolved project questions.</p>
        </header>

        {items.length === 0 ? (
          <section className="mt-12 border-y border-border/25 py-16 text-center">
            <span className="mx-auto grid size-11 place-items-center rounded-xl border border-border/35 bg-surface-raised text-muted"><ReviewIcon /></span>
            <h2 className="mt-5 text-lg font-semibold text-foreground">No review items yet</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted">
              Signals will appear here when Cortex identifies conflicting claims, evidence gaps, or questions that need a teammate&apos;s judgement.
            </p>
            <Link href={routes.workspace.sources(workspaceId)} className="mt-6 inline-flex min-h-10 items-center rounded-lg border border-border/40 px-4 text-sm font-semibold text-foreground transition-colors hover:border-border hover:bg-surface-raised">
              Review indexed sources
            </Link>
          </section>
        ) : (
          <section aria-labelledby="open-review-heading" className="mt-12">
            <div className="border-b border-border/30 pb-4">
              <h2 id="open-review-heading" className="text-base font-semibold">Open items</h2>
              <p className="mt-1 text-sm text-muted">{items.length} {items.length === 1 ? "signal needs" : "signals need"} review</p>
            </div>
            <ol className="divide-y divide-border/20">
              {items.map((item) => (
                <li key={item.id} className="py-6">
                  <article aria-labelledby={`review-${item.id}-title`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md border border-border/30 bg-surface-raised px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted">{item.kind}</span>
                      <span className={`rounded-md border px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] ${priorityStyles[item.priority]}`}>{item.priority} priority</span>
                    </div>
                    <h3 id={`review-${item.id}-title`} className="mt-4 text-lg font-semibold tracking-[-0.02em] text-foreground">{item.title}</h3>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">{item.summary}</p>
                    <p className="mt-4 font-mono text-xs text-subtle">{item.sourceCount} {item.sourceCount === 1 ? "source" : "sources"}</p>
                  </article>
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </main>
  );
}

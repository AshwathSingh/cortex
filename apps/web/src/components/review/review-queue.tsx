import Link from "next/link";

import { ReviewIcon } from "@/components/navigation/sidebar-icons";
import { buttonClassName } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import { routes } from "@/lib/routes";

export type ReviewItem = {
  id: string;
  title: string;
  summary: string;
  kind: "Contradiction" | "Evidence gap" | "Unresolved question";
  priority: "High" | "Medium" | "Low";
  sourceCount: number;
};

const priorityStyles: Record<ReviewItem["priority"], string> = {
  High: "border-red-400/25 bg-red-400/10 text-red-300",
  Medium: "border-amber-400/25 bg-amber-400/10 text-amber-200",
  Low: "border-border/35 bg-surface-raised text-muted",
};

export function ReviewQueue({
  workspaceId,
  items = [],
}: {
  workspaceId: string;
  items?: ReviewItem[];
}) {
  return (
    <PageShell>
      <PageHeader
        headingId="review-title"
        eyebrow="Project signals"
        title="Review queue"
        description="Investigate contradictions, missing evidence, and unresolved project questions."
      />

      {items.length === 0 ? (
        <EmptyState
          icon={<ReviewIcon className="size-5" />}
          title="No review items yet"
          description="Signals will appear here when Cortex identifies conflicting claims, evidence gaps, or questions that need a teammate's judgement."
          action={
            <Link
              href={routes.workspace.sources(workspaceId)}
              className={buttonClassName({ className: "mt-6" })}
            >
              Review indexed sources
            </Link>
          }
        />
      ) : (
        <section aria-labelledby="open-review-heading" className="mt-12">
          <div className="border-b border-border/30 pb-4">
            <h2 id="open-review-heading" className="text-base font-semibold">
              Open items
            </h2>
            <p className="mt-1 text-sm text-muted">
              {items.length}{" "}
              {items.length === 1 ? "signal needs" : "signals need"} review
            </p>
          </div>
          <ol className="divide-y divide-border/20">
            {items.map((item) => (
              <li key={item.id} className="py-6">
                <article aria-labelledby={`review-${item.id}-title`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-md border border-border/30 bg-surface-raised px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted">
                      {item.kind}
                    </span>
                    <span
                      className={`rounded-md border px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] ${priorityStyles[item.priority]}`}
                    >
                      {item.priority} priority
                    </span>
                  </div>
                  <h3
                    id={`review-${item.id}-title`}
                    className="mt-4 text-lg font-semibold tracking-[-0.02em] text-foreground"
                  >
                    {item.title}
                  </h3>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
                    {item.summary}
                  </p>
                  <p className="mt-4 font-mono text-xs text-subtle">
                    {item.sourceCount}{" "}
                    {item.sourceCount === 1 ? "source" : "sources"}
                  </p>
                </article>
              </li>
            ))}
          </ol>
        </section>
      )}
    </PageShell>
  );
}

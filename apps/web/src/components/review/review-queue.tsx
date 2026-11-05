"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ReviewIcon } from "@/components/navigation/sidebar-icons";
import { Button, buttonClassName } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import type { FlagSeverity, WorkspaceFlag } from "@/lib/api-types";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/relative-time";
import { routes } from "@/lib/routes";
import { useWorkspaceFlags } from "@/lib/use-workspace-flags";

/**
 * T-28.2: the Pruning Agent's findings.
 *
 * The queue is ordered by the server, worst first, and rendered in that order.
 * Sorting it again here would be a second opinion about severity in a place
 * that cannot see the rule that assigned it.
 *
 * Every flag shows its evidence inline rather than behind a disclosure. The
 * reader's job on this page is to decide whether the agent was right (AC4), and
 * a finding they have to click to check is one they will take on trust.
 */

const severityStyles: Record<FlagSeverity, string> = {
  HIGH: "border-red-400/25 bg-red-400/10 text-red-300",
  MEDIUM: "border-amber-400/25 bg-amber-400/10 text-amber-200",
  LOW: "border-border/35 bg-surface-raised text-muted",
};

const severityWords: Record<FlagSeverity, string> = {
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
};

function FlagTargets({ flag }: { flag: WorkspaceFlag }) {
  return (
    <ul className="mt-4 flex flex-wrap gap-2">
      {flag.targets.map((target) => (
        <li key={target.key}>
          {target.url ? (
            <a
              href={target.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex max-w-[22rem] items-center gap-1.5 rounded-md border border-border/30 bg-surface-raised px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-border hover:text-foreground"
            >
              <span className="truncate">{target.title}</span>
              <span className="shrink-0 font-mono text-[0.625rem] text-subtle">
                {target.type}
              </span>
              <span className="sr-only"> (opens on GitHub)</span>
            </a>
          ) : (
            <span className="inline-flex max-w-[22rem] items-center gap-1.5 rounded-md border border-border/30 bg-surface-raised px-2.5 py-1.5 text-xs text-muted">
              <span className="truncate">{target.title}</span>
              <span className="shrink-0 font-mono text-[0.625rem] text-subtle">
                {target.type}
              </span>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function FlagEvidenceList({ flag }: { flag: WorkspaceFlag }) {
  if (flag.evidence.length === 0) return null;
  return (
    <div className="mt-4 border-l-2 border-border/30 pl-4">
      <p className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">
        Why this was flagged
      </p>
      <dl className="mt-2 space-y-1">
        {flag.evidence.map((item) => (
          <div key={item.label} className="flex flex-wrap gap-x-2 text-xs leading-6">
            <dt className="text-subtle">{item.label}:</dt>
            <dd className="text-muted">{item.detail}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ReviewQueue({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { state, refresh, isChecking } = useWorkspaceFlags(workspaceId);

  useEffect(() => {
    if (state.kind === "error" && state.status === 401) {
      router.replace("/login");
    }
  }, [router, state]);

  const flags = state.kind === "ready" ? state.data.flags : [];
  const generatedAt = state.kind === "ready" ? state.data.generated_at : null;

  return (
    <PageShell>
      <PageHeader
        headingId="review-title"
        eyebrow="Project signals"
        title="Review queue"
        description="Information Cortex thinks has gone out of date, contradicts something else, or rests on too little evidence."
        action={
          <Button type="button" variant="outline" onClick={refresh} disabled={isChecking}>
            {isChecking ? "Checking…" : "Check again"}
          </Button>
        }
      />

      {state.kind === "loading" ? (
        <p role="status" className="mt-12 text-sm text-muted">
          Checking this workspace…
        </p>
      ) : null}

      {state.kind === "error" ? (
        <div className="mt-10 max-w-2xl">
          <FeedbackAlert message={state.message} />
          <button
            type="button"
            onClick={refresh}
            className="mt-4 text-sm font-semibold text-accent-bright transition-colors hover:text-foreground"
          >
            Try again
          </button>
        </div>
      ) : null}

      {state.kind === "ready" && flags.length === 0 ? (
        <EmptyState
          icon={<ReviewIcon className="size-5" />}
          title="Nothing needs review"
          description="No item in this workspace is out of date, contradicted, or short of evidence. Connect more sources and Cortex will keep checking."
          action={
            <Link
              href={routes.workspace.sources(workspaceId)}
              className={buttonClassName({ className: "mt-6" })}
            >
              Review indexed sources
            </Link>
          }
        />
      ) : null}

      {state.kind === "ready" && flags.length > 0 ? (
        <section aria-labelledby="open-review-heading" className="mt-12">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/30 pb-4">
            <div>
              <h2 id="open-review-heading" className="text-base font-semibold">
                Open items
              </h2>
              <p className="mt-1 text-sm text-muted">
                {flags.length} {flags.length === 1 ? "signal needs" : "signals need"}{" "}
                review
                {generatedAt ? (
                  <>
                    {" · checked "}
                    <span title={formatAbsoluteTime(generatedAt) ?? undefined}>
                      {formatRelativeTime(generatedAt)}
                    </span>
                  </>
                ) : null}
              </p>
            </div>
          </div>

          {state.kind === "ready" && state.data.truncated ? (
            <p role="status" className="mt-4 text-xs text-amber-200">
              This workspace is larger than one check can cover, so these
              findings come from part of it.
            </p>
          ) : null}

          <ol className="divide-y divide-border/20">
            {flags.map((flag) => (
              <li key={flag.id} className="py-6">
                <article aria-labelledby={`flag-${flag.id}-title`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-md border border-border/30 bg-surface-raised px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-muted">
                      {flag.label}
                    </span>
                    <span
                      className={`rounded-md border px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] ${severityStyles[flag.severity]}`}
                    >
                      {severityWords[flag.severity]} priority
                    </span>
                  </div>
                  <h3
                    id={`flag-${flag.id}-title`}
                    className="mt-4 max-w-3xl text-lg font-semibold leading-7 tracking-[-0.02em] text-foreground"
                  >
                    {flag.summary}
                  </h3>
                  <FlagTargets flag={flag} />
                  <FlagEvidenceList flag={flag} />
                </article>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </PageShell>
  );
}

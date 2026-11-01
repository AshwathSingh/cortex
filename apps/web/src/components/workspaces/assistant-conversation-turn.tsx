import Link from "next/link";

import { CortexMark } from "@/components/brand/cortex-mark";
import { routes } from "@/lib/routes";

import type { AssistantTurn } from "./assistant-conversation-context";

const followUpSuggestions = [
  "Trace the related decisions",
  "Show the supporting sources",
  "Find possible contradictions",
];

function CopyIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-3.5">
      <rect x="6.5" y="6.5" width="9" height="9" rx="2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M5 12.5h-.5a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2V5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-3.5">
      <path d="m4.5 10.25 3.4 3.4 7.6-7.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function initialsFor(label: string) {
  const initials = label
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
  return initials || "Y";
}

function citationHref(workspaceId: string, kind: "graph" | "sources") {
  return kind === "graph"
    ? routes.workspace.graph(workspaceId)
    : routes.workspace.sources(workspaceId);
}

export function AssistantConversationTurn({
  turn,
  turnIndex,
  workspaceId,
  userLabel,
  isCopied,
  onCopy,
  onRetry,
  onSelectSuggestion,
  onFocusComposer,
}: {
  turn: AssistantTurn;
  turnIndex: number;
  workspaceId: string;
  userLabel: string;
  isCopied: boolean;
  onCopy: () => void;
  onRetry: () => void;
  onSelectSuggestion: (suggestion: string) => void;
  onFocusComposer: () => void;
}) {
  return (
    <article aria-label={`Conversation turn ${turnIndex + 1}`}>
      <section aria-label="Your message" className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3.5">
        <span aria-hidden="true" className="grid size-8 place-items-center rounded-lg border border-border/25 bg-surface/55 font-mono text-[0.625rem] font-semibold text-muted">
          {initialsFor(userLabel)}
        </span>
        <div className="min-w-0 pt-0.5">
          <p className="text-sm font-semibold text-foreground">
            {userLabel}
            {userLabel !== "You" ? <span className="ml-2 text-xs font-normal text-subtle">You</span> : null}
          </p>
          <p className="mt-2 whitespace-pre-wrap text-[0.9375rem] leading-7 text-foreground">{turn.question}</p>
        </div>
      </section>

      <section aria-label="Cortex response" className="mt-7 grid grid-cols-[2rem_minmax(0,1fr)] gap-3.5">
        <CortexMark className="size-8" />
        <div className="min-w-0 pt-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-foreground">Cortex</h3>
            <span className="rounded-full border border-border/25 bg-surface/60 px-2 py-0.5 font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.1em] text-subtle">
              Preview
            </span>
          </div>

          {turn.status === "pending" ? (
            <p role="status" className="mt-3 text-[0.9375rem] leading-7 text-muted">
              Tracing the project graph and indexed sources…
            </p>
          ) : null}

          {turn.status === "error" ? (
            <div role="alert" className="mt-3 rounded-lg border border-red-400/25 bg-red-500/5 px-3 py-2.5 text-sm text-red-200">
              <p>{turn.error ?? "The assistant could not answer this question."}</p>
              <button type="button" onClick={onRetry} className="mt-2 min-h-7 rounded-md border border-border/30 px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-surface/60">
                Try again
              </button>
            </div>
          ) : null}

          {turn.status === "complete" ? (
            <>
              <p className="mt-3 whitespace-pre-wrap text-[0.9375rem] leading-7 text-muted">{turn.answer}</p>

              {turn.references.length > 0 ? (
                <nav aria-label={`References for question ${turnIndex + 1}`} className="mt-5 flex flex-wrap items-center gap-y-2">
                  <p className="mr-3 font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.12em] text-subtle">Evidence</p>
                  <ol className="flex flex-wrap items-center gap-y-2">
                    {turn.references.map((reference, referenceIndex) => (
                      <li key={`${reference.kind}:${reference.id}`} className="flex items-center">
                        {referenceIndex > 0 ? <span aria-hidden="true" className="h-px w-4 bg-border/35" /> : null}
                        <Link
                          href={citationHref(workspaceId, reference.kind)}
                          aria-label={reference.label}
                          title={reference.description}
                          className="group inline-flex min-h-7 items-center gap-1.5 rounded-full px-1.5 text-xs text-subtle transition-colors hover:text-foreground"
                        >
                          <span className="grid size-3.5 shrink-0 place-items-center rounded-full border border-accent-bright/45 transition-[background,border-color] group-hover:border-accent-bright group-hover:bg-accent/15">
                            <span className="size-1.5 rounded-full bg-accent-bright" />
                          </span>
                          <span className="underline decoration-border/40 underline-offset-4 group-hover:decoration-accent-bright/60">{reference.label}</span>
                        </Link>
                      </li>
                    ))}
                  </ol>
                </nav>
              ) : null}

              <div className="mt-4 flex items-center gap-2 border-t border-border/15 pt-3">
                <button type="button" onClick={onCopy} className="inline-flex min-h-7 items-center gap-1.5 rounded-md px-2 text-[0.6875rem] font-medium text-subtle transition-colors hover:bg-surface/55 hover:text-foreground">
                  {isCopied ? <CheckIcon /> : <CopyIcon />}
                  {isCopied ? "Copied" : "Copy answer"}
                </button>
                <button type="button" onClick={onFocusComposer} className="min-h-7 rounded-md px-2 text-[0.6875rem] font-medium text-subtle transition-colors hover:bg-surface/55 hover:text-foreground">
                  Ask a follow-up
                </button>
              </div>

              <section aria-labelledby={`follow-up-heading-${turn.id}`} className="mt-5">
                <h4 id={`follow-up-heading-${turn.id}`} className="font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.12em] text-subtle">Continue exploring</h4>
                <div className="mt-2 flex flex-wrap gap-2">
                  {followUpSuggestions.map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => onSelectSuggestion(suggestion)} className="min-h-8 rounded-full border border-border/20 bg-surface/30 px-3 text-xs text-muted transition-[background,border-color,color] hover:border-border/45 hover:bg-surface/60 hover:text-foreground">
                      {suggestion}
                    </button>
                  ))}
                </div>
              </section>
            </>
          ) : null}
        </div>
      </section>
    </article>
  );
}

"use client";

import Link from "next/link";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { CortexMark } from "@/components/brand/cortex-mark";
import { routes } from "@/lib/routes";

import { useWorkspace } from "./workspace-context";

const promptSuggestions = [
  "Why was this architecture chosen?",
  "Show open contradictions",
  "Summarize recent decisions",
];

const followUpSuggestions = [
  "Trace the related decisions",
  "Show the supporting sources",
  "Find possible contradictions",
];

const placeholderResponse =
  "This placeholder demonstrates how Cortex will present a concise, evidence-backed answer. Once the assistant service is connected, each claim will be grounded in the project graph and its indexed sources.";

type ChatReference = {
  label: string;
  description: string;
  href: string;
};

type ConversationTurn = {
  id: number;
  question: string;
  answer: string;
  references: ChatReference[];
};

const headingVariants = [
  ["What should we explore in", "?"],
  ["What would you like to understand about", "?"],
  ["What should Cortex investigate in", "?"],
  ["Where should we begin in", "?"],
  ["What needs a closer look in", "?"],
  ["What question should we answer about", "?"],
  ["What should we trace through", "?"],
] as const;

function chooseHeadingVariant(workspaceId: string) {
  const storageKey = `cortex:home-heading:${workspaceId}`;
  let previousVariant: number | null = null;

  try {
    const storedValue = window.sessionStorage.getItem(storageKey);
    const storedVariant = storedValue === null ? Number.NaN : Number(storedValue);
    if (
      Number.isInteger(storedVariant) &&
      storedVariant >= 0 &&
      storedVariant < headingVariants.length
    ) {
      previousVariant = storedVariant;
    }
  } catch {
    // Browser storage is optional; the heading can still vary without it.
  }

  const availableVariants =
    previousVariant === null ? headingVariants.length : headingVariants.length - 1;
  const randomOffset = Math.floor(Math.random() * availableVariants);
  const nextVariant =
    previousVariant === null
      ? randomOffset
      : (previousVariant + 1 + randomOffset) % headingVariants.length;

  try {
    window.sessionStorage.setItem(storageKey, String(nextVariant));
  } catch {
    // Ignore unavailable browser storage.
  }

  return nextVariant;
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

function ArrowUpIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      className="size-5"
    >
      <path
        d="M10 15.5v-11m0 0L5.75 8.75M10 4.5l4.25 4.25"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      className="size-4"
    >
      <path
        d="M10 4v12M4 10h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      className="size-3.5"
    >
      <rect
        x="6.5"
        y="6.5"
        width="9"
        height="9"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path
        d="M5 12.5h-.5a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2V5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      className="size-3.5"
    >
      <path
        d="m4.5 10.25 3.4 3.4 7.6-7.6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function WorkspaceDetail({ workspaceId }: { workspaceId: string }) {
  const { user, workspace } = useWorkspace();
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const conversationHistory = useRef<HTMLDivElement>(null);
  const nextTurnId = useRef(0);
  const previousWorkspaceId = useRef(workspaceId);
  const [headingVariantIndex, setHeadingVariantIndex] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [copiedTurnId, setCopiedTurnId] = useState<number | null>(null);

  useEffect(() => {
    const workspaceChanged = previousWorkspaceId.current !== workspaceId;
    previousWorkspaceId.current = workspaceId;

    if (workspaceChanged) {
      nextTurnId.current = 0;
      setPrompt("");
      setTurns([]);
      setCopiedTurnId(null);
    }

    const timeout = window.setTimeout(() => {
      setHeadingVariantIndex(chooseHeadingVariant(workspaceId));
      if (workspaceChanged) {
        promptInput.current?.focus();
      }
    }, 0);

    return () => window.clearTimeout(timeout);
  }, [workspaceId]);

  useEffect(() => {
    const history = conversationHistory.current;
    if (history) {
      history.scrollTop = history.scrollHeight;
    }
  }, [turns]);

  useEffect(() => {
    if (turns.length === 0 && nextTurnId.current > 0) {
      promptInput.current?.focus();
    }
  }, [turns.length]);

  function selectSuggestion(suggestion: string) {
    setPrompt(suggestion);
    promptInput.current?.focus();
  }

  function startNewConversation() {
    setTurns([]);
    setPrompt("");
    setCopiedTurnId(null);
  }

  async function copyAnswer(turn: ConversationTurn) {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setCopiedTurnId(turn.id);
    } catch {
      setCopiedTurnId(null);
    }
  }

  function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = prompt.trim();
    if (!question) return;

    setTurns((currentTurns) => [
      ...currentTurns,
      {
        id: nextTurnId.current++,
        question,
        answer: placeholderResponse,
        references: [
          {
            label: "Graph explorer",
            description: "Inspect entities and relationships",
            href: routes.workspace.graph(workspaceId),
          },
          {
            label: "Project sources",
            description: "Review the indexed source material",
            href: routes.workspace.sources(workspaceId),
          },
        ],
      },
    ]);
    setPrompt("");
    promptInput.current?.focus();
  }

  function handlePromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  const [headingPrefix, headingSuffix] = headingVariants[headingVariantIndex];
  const hasMessages = turns.length > 0;
  const userLabel = user?.display_name?.trim() || user?.email || "You";
  const conversationTitle = turns[0]?.question ?? "Graph-Aware Assistant";

  return (
    <main className="flex h-screen flex-col overflow-hidden">
      {hasMessages ? (
        <header className="flex h-[4.25rem] shrink-0 items-center justify-between gap-6 border-b border-border/20 px-[var(--cortex-page-gutter)]">
          <div className="flex min-w-0 items-center gap-3">
            <CortexMark className="size-7 shrink-0" />
            <span className="shrink-0 text-sm font-medium text-muted">Cortex</span>
            <span aria-hidden="true" className="text-lg text-subtle/70">
              /
            </span>
            <h1
              id="assistant-session-heading"
              title={conversationTitle}
              className="truncate text-base font-medium tracking-[-0.015em] text-foreground"
            >
              {conversationTitle}
            </h1>
          </div>

          <button
            type="button"
            onClick={startNewConversation}
            className="flex min-h-9 shrink-0 items-center gap-2 rounded-lg border border-border/30 bg-surface/35 px-3 text-xs font-medium text-muted transition-[background,border-color,color] hover:border-border/55 hover:bg-surface/65 hover:text-foreground"
          >
            <PlusIcon />
            New conversation
          </button>
        </header>
      ) : null}

      <div className="mx-auto flex min-h-0 w-full max-w-[76rem] flex-1 flex-col px-[var(--cortex-page-gutter)] pb-8 pt-6">
        <section
          aria-labelledby={
            hasMessages ? "assistant-session-heading" : "ask-cortex-heading"
          }
          className={`mx-auto flex min-h-0 w-full max-w-[51rem] flex-1 flex-col ${
            hasMessages ? "" : "justify-center pb-24"
          }`}
        >
          {!hasMessages ? (
            <>
              <h1
                id="ask-cortex-heading"
                className="text-center text-[clamp(1.65rem,3vw,2.25rem)] font-medium leading-tight tracking-[-0.035em] text-foreground"
              >
                {headingPrefix}{" "}
                <span className="decoration-border decoration-dotted underline underline-offset-4">
                  {workspace?.name ?? "this workspace"}
                </span>
                {headingSuffix}
              </h1>
              <p className="mx-auto mt-3 max-w-[38rem] text-center text-sm leading-6 text-subtle">
                Trace project decisions, surface contradictions, and connect
                answers to workspace evidence.
              </p>
            </>
          ) : null}

          {hasMessages ? (
            <div
              ref={conversationHistory}
              aria-label="Conversation history"
              className="mt-5 min-h-0 flex-1 overflow-y-auto pr-2"
            >
              <ol aria-live="polite" className="divide-y divide-border/20">
                {turns.map((turn, turnIndex) => (
                  <li key={turn.id} className="py-8 first:pt-3">
                    <article aria-label={`Conversation turn ${turnIndex + 1}`}>
                      <section
                        aria-label="Your message"
                        className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3.5"
                      >
                        <span
                          aria-hidden="true"
                          className="grid size-8 place-items-center rounded-lg border border-border/25 bg-surface/55 font-mono text-[0.625rem] font-semibold text-muted"
                        >
                          {initialsFor(userLabel)}
                        </span>
                        <div className="min-w-0 pt-0.5">
                          <p className="text-sm font-semibold text-foreground">
                            {userLabel}
                            {userLabel !== "You" ? (
                              <span className="ml-2 text-xs font-normal text-subtle">
                                You
                              </span>
                            ) : null}
                          </p>
                          <p className="mt-2 whitespace-pre-wrap text-[0.9375rem] leading-7 text-foreground">
                            {turn.question}
                          </p>
                        </div>
                      </section>

                      <section
                        aria-label="Cortex response"
                        className="mt-7 grid grid-cols-[2rem_minmax(0,1fr)] gap-3.5"
                      >
                        <CortexMark className="size-8" />
                        <div className="min-w-0 pt-0.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-sm font-semibold text-foreground">
                              Cortex
                            </h3>
                            <span className="rounded-full border border-border/25 bg-surface/60 px-2 py-0.5 font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.1em] text-subtle">
                              Preview
                            </span>
                          </div>

                          <p className="mt-3 text-[0.9375rem] leading-7 text-muted">
                            {turn.answer}
                          </p>

                          <nav
                            aria-label={`References for question ${turnIndex + 1}`}
                            className="mt-5 flex flex-wrap items-center gap-y-2"
                          >
                            <p className="mr-3 font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.12em] text-subtle">
                              Evidence
                            </p>
                            <ol className="flex flex-wrap items-center gap-y-2">
                              {turn.references.map((reference, referenceIndex) => (
                                <li
                                  key={reference.href}
                                  className="flex items-center"
                                >
                                  {referenceIndex > 0 ? (
                                    <span
                                      aria-hidden="true"
                                      className="h-px w-4 bg-border/35"
                                    />
                                  ) : null}
                                  <Link
                                    href={reference.href}
                                    aria-label={reference.label}
                                    title={reference.description}
                                    className="group inline-flex min-h-7 items-center gap-1.5 rounded-full px-1.5 text-xs text-subtle transition-colors hover:text-foreground"
                                  >
                                    <span className="grid size-3.5 shrink-0 place-items-center rounded-full border border-accent-bright/45 transition-[background,border-color] group-hover:border-accent-bright group-hover:bg-accent/15">
                                      <span className="size-1.5 rounded-full bg-accent-bright" />
                                    </span>
                                    <span className="underline decoration-border/40 underline-offset-4 group-hover:decoration-accent-bright/60">
                                      {reference.label}
                                    </span>
                                  </Link>
                                </li>
                              ))}
                            </ol>
                          </nav>

                          <div className="mt-4 flex items-center gap-2 border-t border-border/15 pt-3">
                            <button
                              type="button"
                              onClick={() => void copyAnswer(turn)}
                              className="inline-flex min-h-7 items-center gap-1.5 rounded-md px-2 text-[0.6875rem] font-medium text-subtle transition-colors hover:bg-surface/55 hover:text-foreground"
                            >
                              {copiedTurnId === turn.id ? (
                                <CheckIcon />
                              ) : (
                                <CopyIcon />
                              )}
                              {copiedTurnId === turn.id ? "Copied" : "Copy answer"}
                            </button>
                            <button
                              type="button"
                              onClick={() => promptInput.current?.focus()}
                              className="min-h-7 rounded-md px-2 text-[0.6875rem] font-medium text-subtle transition-colors hover:bg-surface/55 hover:text-foreground"
                            >
                              Ask a follow-up
                            </button>
                          </div>

                          <section
                            aria-labelledby={`follow-up-heading-${turn.id}`}
                            className="mt-5"
                          >
                            <h4
                              id={`follow-up-heading-${turn.id}`}
                              className="font-mono text-[0.5625rem] font-semibold uppercase tracking-[0.12em] text-subtle"
                            >
                              Continue exploring
                            </h4>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {followUpSuggestions.map((suggestion) => (
                                <button
                                  key={suggestion}
                                  type="button"
                                  onClick={() => selectSuggestion(suggestion)}
                                  className="min-h-8 rounded-full border border-border/20 bg-surface/30 px-3 text-xs text-muted transition-[background,border-color,color] hover:border-border/45 hover:bg-surface/60 hover:text-foreground"
                                >
                                  {suggestion}
                                </button>
                              ))}
                            </div>
                          </section>
                        </div>
                      </section>
                    </article>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          <div className={hasMessages ? "mt-6 shrink-0" : "mt-9"}>
            <form
              onSubmit={submitQuestion}
              aria-label="Ask Cortex"
              autoComplete="off"
              className="relative z-10 overflow-hidden rounded-[1.125rem] border border-border/30 bg-composer shadow-[0_20px_60px_rgb(0_0_0/28%)] transition-[border-color,box-shadow] duration-200 focus-within:border-border/65 focus-within:shadow-[0_22px_70px_rgb(0_0_0/34%)]"
            >
              <label htmlFor="cortex-question" className="sr-only">
                Ask Cortex about this workspace
              </label>
              <textarea
                ref={promptInput}
                id="cortex-question"
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={handlePromptKeyDown}
                autoComplete="off"
                rows={hasMessages ? 2 : 3}
                placeholder="Ask about a decision, contradiction, or source"
                className={`cortex-composer-input block w-full resize-none bg-transparent px-5 pb-3 pt-5 text-[0.95rem] leading-6 text-foreground placeholder:text-subtle ${
                  hasMessages ? "min-h-20" : "min-h-28"
                }`}
              />

              <div className="flex min-h-13 items-center justify-between gap-4 px-3.5 pb-3">
                <div className="flex min-w-0 items-center gap-1">
                  <Link
                    href={routes.workspace.ingest(workspaceId)}
                    aria-label="Add source"
                    title="Add source"
                    className="flex min-h-8 items-center gap-2 rounded-lg px-2 text-xs font-medium text-muted transition-colors hover:bg-surface/70 hover:text-foreground"
                  >
                    <PlusIcon />
                    Add source
                  </Link>
                </div>

                <button
                  type="submit"
                  disabled={!prompt.trim()}
                  aria-disabled={!prompt.trim()}
                  aria-label="Send question"
                  className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-foreground transition-[background,opacity,transform] enabled:hover:bg-accent-hover enabled:active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-25"
                >
                  <ArrowUpIcon />
                </button>
              </div>
            </form>

            <div className="relative mx-5 -mt-px flex min-h-10 items-center justify-between gap-4 rounded-b-xl border border-border/25 bg-surface/45 px-4 pt-px text-[0.6875rem] text-subtle">
              <span className="min-w-0 truncate">
                Workspace · {workspace?.name ?? "Loading…"}
              </span>
              <nav aria-label="Available answer context" className="flex shrink-0 items-center gap-2.5">
                <Link
                  href={routes.workspace.graph(workspaceId)}
                  className="inline-flex items-center gap-1.5 transition-colors hover:text-foreground"
                >
                  <span className="size-1.5 rounded-full bg-accent-bright" />
                  Graph
                </Link>
                <Link
                  href={routes.workspace.sources(workspaceId)}
                  className="inline-flex items-center gap-1.5 transition-colors hover:text-foreground"
                >
                  <span className="size-1.5 rounded-full bg-accent-bright" />
                  Sources
                </Link>
              </nav>
            </div>
          </div>

          {!hasMessages ? (
            <section aria-labelledby="prompt-suggestions" className="mt-6">
              <h2 id="prompt-suggestions" className="sr-only">
                Try asking
              </h2>
              <div className="flex items-center justify-center gap-1 text-xs text-subtle">
                {promptSuggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => selectSuggestion(suggestion)}
                    className="min-h-8 rounded-lg px-3 transition-colors hover:bg-surface/45 hover:text-muted"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </section>
          ) : null}
        </section>
      </div>
    </main>
  );
}

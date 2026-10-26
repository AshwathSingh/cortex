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

export function WorkspaceDetail({ workspaceId }: { workspaceId: string }) {
  const { user, workspace } = useWorkspace();
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const conversationHistory = useRef<HTMLDivElement>(null);
  const nextTurnId = useRef(0);
  const [headingVariantIndex, setHeadingVariantIndex] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setHeadingVariantIndex(chooseHeadingVariant(workspaceId));
    }, 0);

    return () => window.clearTimeout(timeout);
  }, [workspaceId]);

  useEffect(() => {
    const history = conversationHistory.current;
    if (history) {
      history.scrollTop = history.scrollHeight;
    }
  }, [turns]);

  function selectSuggestion(suggestion: string) {
    setPrompt(suggestion);
    promptInput.current?.focus();
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

  return (
    <main className="h-screen overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[76rem] flex-col px-[var(--cortex-page-gutter)] pb-8 pt-8">
        <section
          aria-labelledby="ask-cortex-heading"
          className={`mx-auto flex min-h-0 w-full max-w-[51rem] flex-1 flex-col ${
            hasMessages ? "" : "justify-center pb-24"
          }`}
        >
          <h1
            id="ask-cortex-heading"
            className={`font-medium leading-tight tracking-[-0.035em] text-foreground ${
              hasMessages
                ? "text-xl"
                : "text-center text-[clamp(1.65rem,3vw,2.25rem)]"
            }`}
          >
            {hasMessages ? (
              "Graph-Aware Assistant"
            ) : (
              <>
                {headingPrefix}{" "}
                <span className="decoration-border decoration-dotted underline underline-offset-4">
                  {workspace?.name ?? "this workspace"}
                </span>
                {headingSuffix}
              </>
            )}
          </h1>

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
                              Placeholder answer
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
              <Link
                href={routes.workspace.sources(workspaceId)}
                className="shrink-0 transition-colors hover:text-foreground"
              >
                All sources
              </Link>
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

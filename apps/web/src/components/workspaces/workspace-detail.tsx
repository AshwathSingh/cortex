"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { routes } from "@/lib/routes";

import { useWorkspace } from "./workspace-context";

const promptSuggestions = [
  "Why was this architecture chosen?",
  "Show open contradictions",
  "Summarize recent decisions",
];

const placeholderResponse =
  "This is a placeholder response from Cortex. Graph-aware answers will appear here once the assistant service is connected.";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
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
  const { workspace } = useWorkspace();
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const conversationHistory = useRef<HTMLDivElement>(null);
  const nextMessageId = useRef(0);
  const [headingVariantIndex, setHeadingVariantIndex] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);

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
  }, [messages]);

  function selectSuggestion(suggestion: string) {
    setPrompt(suggestion);
    promptInput.current?.focus();
  }

  function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = prompt.trim();
    if (!question) return;

    setMessages((currentMessages) => [
      ...currentMessages,
      {
        id: nextMessageId.current++,
        role: "user",
        content: question,
      },
      {
        id: nextMessageId.current++,
        role: "assistant",
        content: placeholderResponse,
      },
    ]);
    setPrompt("");
  }

  const [headingPrefix, headingSuffix] = headingVariants[headingVariantIndex];
  const hasMessages = messages.length > 0;

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
              className="mt-6 min-h-0 flex-1 overflow-y-auto pr-2"
            >
              <ol aria-live="polite" className="space-y-6 py-2">
                {messages.map((message) => {
                  const isUser = message.role === "user";

                  return (
                    <li
                      key={message.id}
                      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                    >
                      <article
                        aria-label={isUser ? "You" : "Cortex"}
                        className={`max-w-[85%] rounded-2xl border px-4 py-3 ${
                          isUser
                            ? "border-accent-bright/20 bg-accent/20"
                            : "border-border/25 bg-surface/70"
                        }`}
                      >
                        <p className="font-mono text-[0.625rem] font-semibold uppercase tracking-[0.12em] text-subtle">
                          {isUser ? "You" : "Cortex"}
                        </p>
                        <p className="mt-1.5 whitespace-pre-wrap text-sm leading-6 text-foreground">
                          {message.content}
                        </p>
                      </article>
                    </li>
                  );
                })}
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
                  aria-disabled={!prompt.trim()}
                  aria-label="Send question"
                  className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-foreground transition-[background,opacity,transform] hover:bg-accent-hover active:scale-[0.96] aria-disabled:cursor-not-allowed aria-disabled:opacity-25"
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

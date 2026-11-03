"use client";

import { useEffect, useRef, useState } from "react";

import { CortexMark } from "@/components/brand/cortex-mark";
import { ApiError } from "@/lib/api";
import {
  askAssistant,
  type AssistantHistoryMessage,
} from "@/lib/assistant-client";

import { AssistantComposer } from "./assistant-composer";
import {
  type AssistantTurn,
  type AssistantTurnHandle,
  useAssistantConversations,
} from "./assistant-conversation-context";
import { AssistantConversationTurn } from "./assistant-conversation-turn";
import { useWorkspace } from "./workspace-context";

const promptSuggestions = [
  "Why was this architecture chosen?",
  "Show open contradictions",
  "Summarize recent decisions",
];

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

function historyFromTurns(turns: AssistantTurn[]): AssistantHistoryMessage[] {
  return turns
    .filter((turn) => turn.status === "complete")
    .flatMap((turn) => [
      { role: "user" as const, content: turn.question },
      { role: "assistant" as const, content: turn.answer },
    ])
    .slice(-20);
}

function requestErrorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "This response was cancelled.";
  }
  if (error instanceof ApiError || error instanceof Error) {
    return error.message;
  }
  return "The assistant could not answer this question. Please try again.";
}

export function WorkspaceDetail({ workspaceId }: { workspaceId: string }) {
  const { user, workspace } = useWorkspace();
  const {
    activeConversation,
    beginTurn,
    completeTurn,
    failTurn,
    retryTurn,
    startNewConversation: beginNewConversation,
  } = useAssistantConversations();
  const promptInput = useRef<HTMLTextAreaElement>(null);
  const conversationHistory = useRef<HTMLDivElement>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const previousWorkspaceId = useRef(workspaceId);
  const previousConversationId = useRef<string | null>(null);
  const [headingVariantIndex, setHeadingVariantIndex] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [copiedTurnId, setCopiedTurnId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const turns = activeConversation?.turns ?? [];

  useEffect(() => {
    const workspaceChanged = previousWorkspaceId.current !== workspaceId;
    previousWorkspaceId.current = workspaceId;
    if (workspaceChanged) {
      setPrompt("");
      setCopiedTurnId(null);
    }

    const timeout = window.setTimeout(() => {
      setHeadingVariantIndex(chooseHeadingVariant(workspaceId));
      if (workspaceChanged) promptInput.current?.focus();
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [workspaceId]);

  useEffect(() => {
    return () => {
      activeRequest.current?.abort();
      activeRequest.current = null;
    };
  }, [workspaceId]);

  useEffect(() => {
    const history = conversationHistory.current;
    if (history) history.scrollTop = history.scrollHeight;
  }, [activeConversation?.turns]);

  useEffect(() => {
    if (previousConversationId.current && !activeConversation) {
      promptInput.current?.focus();
    }
    previousConversationId.current = activeConversation?.id ?? null;
  }, [activeConversation]);

  function selectSuggestion(suggestion: string) {
    setPrompt(suggestion);
    promptInput.current?.focus();
  }

  function startNewConversation() {
    activeRequest.current?.abort();
    beginNewConversation();
    setPrompt("");
    setCopiedTurnId(null);
  }

  async function copyAnswer(turn: AssistantTurn) {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setCopiedTurnId(turn.id);
    } catch {
      setCopiedTurnId(null);
    }
  }

  async function sendQuestion(
    question: string,
    existingHandle?: AssistantTurnHandle,
  ) {
    if (activeRequest.current) return;
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion) return;

    const handle = existingHandle ?? beginTurn(normalizedQuestion);
    if (existingHandle) retryTurn(existingHandle);
    else setPrompt("");

    const controller = new AbortController();
    activeRequest.current = controller;
    setIsSubmitting(true);
    try {
      const response = await askAssistant({
        workspaceId,
        question: normalizedQuestion,
        history: historyFromTurns(turns),
        signal: controller.signal,
      });
      completeTurn(handle, response);
    } catch (error) {
      failTurn(handle, requestErrorMessage(error));
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null;
        setIsSubmitting(false);
        window.setTimeout(() => promptInput.current?.focus(), 0);
      }
    }
  }

  function retryQuestion(turn: AssistantTurn) {
    if (!activeConversation) return;
    void sendQuestion(turn.question, {
      conversationId: activeConversation.id,
      turnId: turn.id,
    });
  }

  const [headingPrefix, headingSuffix] = headingVariants[headingVariantIndex];
  const hasMessages = turns.length > 0;
  const userLabel = user?.display_name?.trim() || user?.email || "You";
  const conversationTitle = activeConversation?.title ?? "Graph-Aware Assistant";

  return (
    <main className="flex h-screen flex-col overflow-hidden">
      {hasMessages ? (
        <header className="flex h-[4.25rem] shrink-0 items-center justify-between gap-6 border-b border-border/20 px-[var(--cortex-page-gutter)]">
          <div className="flex min-w-0 items-center gap-3">
            <CortexMark className="size-7 shrink-0" />
            <span className="shrink-0 text-sm font-medium text-muted">Cortex</span>
            <span aria-hidden="true" className="text-lg text-subtle/70">/</span>
            <h1 id="assistant-session-heading" title={conversationTitle} className="truncate text-base font-medium tracking-[-0.015em] text-foreground">
              {conversationTitle}
            </h1>
          </div>
          <button type="button" onClick={startNewConversation} className="flex min-h-9 shrink-0 items-center gap-2 rounded-lg border border-border/30 bg-surface/35 px-3 text-xs font-medium text-muted transition-[background,border-color,color] hover:border-border/55 hover:bg-surface/65 hover:text-foreground">
            <span aria-hidden="true" className="text-base leading-none">+</span>
            New conversation
          </button>
        </header>
      ) : null}

      <div className="mx-auto flex min-h-0 w-full max-w-[76rem] flex-1 flex-col px-[var(--cortex-page-gutter)] pb-8 pt-6">
        <section aria-labelledby={hasMessages ? "assistant-session-heading" : "ask-cortex-heading"} className={`mx-auto flex min-h-0 w-full max-w-[51rem] flex-1 flex-col ${hasMessages ? "" : "justify-center pb-24"}`}>
          {!hasMessages ? (
            <>
              <h1 id="ask-cortex-heading" className="text-center text-[clamp(1.65rem,3vw,2.25rem)] font-medium leading-tight tracking-[-0.035em] text-foreground">
                {headingPrefix}{" "}
                <span className="decoration-border decoration-dotted underline underline-offset-4">{workspace?.name ?? "this workspace"}</span>
                {headingSuffix}
              </h1>
              <p className="mx-auto mt-3 max-w-[38rem] text-center text-sm leading-6 text-subtle">
                Trace project decisions, surface contradictions, and connect answers to workspace evidence.
              </p>
            </>
          ) : null}

          {hasMessages ? (
            <div ref={conversationHistory} aria-label="Conversation history" className="mt-5 min-h-0 flex-1 overflow-y-auto pr-2">
              <ol aria-live="polite" className="divide-y divide-border/20">
                {turns.map((turn, turnIndex) => (
                  <li key={turn.id} className="py-8 first:pt-3">
                    <AssistantConversationTurn
                      turn={turn}
                      turnIndex={turnIndex}
                      workspaceId={workspaceId}
                      userLabel={userLabel}
                      isCopied={copiedTurnId === turn.id}
                      onCopy={() => void copyAnswer(turn)}
                      onRetry={() => retryQuestion(turn)}
                      onSelectSuggestion={selectSuggestion}
                      onFocusComposer={() => promptInput.current?.focus()}
                    />
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          <AssistantComposer
            inputRef={promptInput}
            workspaceId={workspaceId}
            workspaceName={workspace?.name ?? null}
            prompt={prompt}
            hasMessages={hasMessages}
            isSubmitting={isSubmitting}
            onPromptChange={setPrompt}
            onSubmit={() => void sendQuestion(prompt)}
          />

          {!hasMessages ? (
            <section aria-labelledby="prompt-suggestions" className="mt-6">
              <h2 id="prompt-suggestions" className="sr-only">Try asking</h2>
              <div className="flex items-center justify-center gap-1 text-xs text-subtle">
                {promptSuggestions.map((suggestion) => (
                  <button key={suggestion} type="button" onClick={() => selectSuggestion(suggestion)} className="min-h-8 rounded-lg px-3 transition-colors hover:bg-surface/45 hover:text-muted">
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

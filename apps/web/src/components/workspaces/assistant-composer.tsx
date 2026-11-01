import Link from "next/link";
import type { RefObject } from "react";

import { MAX_ASSISTANT_QUESTION_LENGTH } from "@/lib/assistant-client";
import { routes } from "@/lib/routes";

function ArrowUpIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-5">
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
    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" className="size-4">
      <path
        d="M10 4v12M4 10h12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function AssistantComposer({
  inputRef,
  workspaceId,
  workspaceName,
  prompt,
  hasMessages,
  isSubmitting,
  onPromptChange,
  onSubmit,
}: {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  workspaceId: string;
  workspaceName: string | null;
  prompt: string;
  hasMessages: boolean;
  isSubmitting: boolean;
  onPromptChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className={hasMessages ? "mt-6 shrink-0" : "mt-9"}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
        aria-label="Ask Cortex"
        aria-busy={isSubmitting}
        autoComplete="off"
        className="relative z-10 overflow-hidden rounded-[1.125rem] border border-border/30 bg-composer shadow-[0_20px_60px_rgb(0_0_0/28%)] transition-[border-color,box-shadow] duration-200 focus-within:border-border/65 focus-within:shadow-[0_22px_70px_rgb(0_0_0/34%)]"
      >
        <label htmlFor="cortex-question" className="sr-only">
          Ask Cortex about this workspace
        </label>
        <textarea
          ref={inputRef}
          id="cortex-question"
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          autoComplete="off"
          disabled={isSubmitting}
          maxLength={MAX_ASSISTANT_QUESTION_LENGTH}
          rows={hasMessages ? 2 : 3}
          placeholder={
            isSubmitting
              ? "Cortex is working on your question…"
              : "Ask about a decision, contradiction, or source"
          }
          className={`cortex-composer-input block w-full resize-none bg-transparent px-5 pb-3 pt-5 text-[0.95rem] leading-6 text-foreground placeholder:text-subtle disabled:cursor-wait disabled:opacity-70 ${
            hasMessages ? "min-h-20" : "min-h-28"
          }`}
        />

        <div className="flex min-h-13 items-center justify-between gap-4 px-3.5 pb-3">
          <Link
            href={routes.workspace.ingest(workspaceId)}
            aria-label="Add source"
            title="Add source"
            className="flex min-h-8 items-center gap-2 rounded-lg px-2 text-xs font-medium text-muted transition-colors hover:bg-surface/70 hover:text-foreground"
          >
            <PlusIcon />
            Add source
          </Link>

          <button
            type="submit"
            disabled={!prompt.trim() || isSubmitting}
            aria-disabled={!prompt.trim() || isSubmitting}
            aria-label={isSubmitting ? "Waiting for Cortex" : "Send question"}
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-foreground transition-[background,opacity,transform] enabled:hover:bg-accent-hover enabled:active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-25"
          >
            <ArrowUpIcon />
          </button>
        </div>
      </form>

      <div className="relative mx-5 -mt-px flex min-h-10 items-center justify-between gap-4 rounded-b-xl border border-border/25 bg-surface/45 px-4 pt-px text-[0.6875rem] text-subtle">
        <span className="min-w-0 truncate">
          Workspace · {workspaceName ?? "Loading…"}
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
  );
}

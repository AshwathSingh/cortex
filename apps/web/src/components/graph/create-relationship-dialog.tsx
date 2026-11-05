"use client";

import {
  type FormEvent,
  type SyntheticEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { Field, fieldControlClassName } from "@/components/ui/form-field";
import type { GraphNode } from "@/lib/api-types";

const RATIONALE_MAX_LENGTH = 2000;

const NODE_TYPE_LABELS: Record<GraphNode["type"], string> = {
  Author: "Author",
  PullRequest: "Pull request",
  Issue: "Issue",
  Document: "Document",
  DocumentSection: "Section",
};

const NODE_TYPE_STYLES: Record<GraphNode["type"], { colour: string; shape: string }> = {
  Author: { colour: "var(--cortex-graph-author)", shape: "rounded-full" },
  PullRequest: { colour: "var(--cortex-graph-pull-request)", shape: "rounded-[2px]" },
  Issue: { colour: "var(--cortex-graph-issue)", shape: "rotate-45 rounded-[1px]" },
  // The same swatches the graph legend uses: the canvas draws a hexagon for a
  // document, which reads as a blob at this size, so it is a squat rounded box.
  Document: { colour: "var(--cortex-graph-document)", shape: "rounded-[3px]" },
  DocumentSection: {
    colour: "var(--cortex-graph-document-section)",
    shape: "[clip-path:polygon(50%_0%,100%_100%,0%_100%)]",
  },
};

function Endpoint({
  label,
  node,
}: {
  label: "From" | "To";
  node: GraphNode;
}) {
  const style = NODE_TYPE_STYLES[node.type];
  return (
    <div className="min-w-0 text-center">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-subtle">
        {label}
      </p>
      <span
        className={`mx-auto mt-3 block size-3 border-2 bg-background shadow-[0_0_0_4px_rgb(7_10_15/0.9),0_0_16px_currentColor] ${style.shape}`}
        style={{ borderColor: style.colour, color: style.colour }}
        aria-hidden="true"
      />
      <p className="mt-3 truncate text-sm font-medium text-foreground" title={node.title}>
        {node.title}
      </p>
      <p className="mt-1 text-xs text-muted">{NODE_TYPE_LABELS[node.type]}</p>
    </div>
  );
}

export function CreateRelationshipDialog({
  error,
  isSubmitting,
  onCancel,
  onSubmit,
  source,
  target,
}: {
  error: string | null;
  isSubmitting: boolean;
  onCancel: () => void;
  onSubmit: (rationale: string) => void;
  source: GraphNode;
  target: GraphNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const rationaleRef = useRef<HTMLTextAreaElement>(null);
  const [rationale, setRationale] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    rationaleRef.current?.focus();
  }, []);

  function closeDialog() {
    if (isSubmitting) return;
    dialogRef.current?.close();
    onCancel();
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    closeDialog();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;
    onSubmit(rationale.trim());
  }

  return (
    <dialog
      ref={dialogRef}
      aria-describedby="create-relationship-description"
      aria-labelledby="create-relationship-title"
      aria-modal="true"
      onCancel={handleCancel}
      className="m-auto w-[min(38rem,calc(100%-2rem))] overflow-hidden rounded-2xl border border-[var(--cortex-graph-divider)] bg-[rgb(9_14_23/0.98)] p-0 text-foreground shadow-[0_32px_100px_rgb(0_0_0/0.62),inset_0_1px_0_rgb(120_160_255/0.08)] backdrop:bg-[rgb(2_5_9/0.78)] backdrop:backdrop-blur-[3px]"
    >
      <div className="flex items-start justify-between gap-5 px-6 pb-4 pt-6">
        <div className="flex items-start gap-3.5">
          <span className="mt-0.5 grid size-10 shrink-0 place-items-center rounded-xl border border-accent-bright/20 bg-accent/10 text-accent-bright shadow-[inset_0_1px_0_rgb(255_255_255/0.05)]">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="size-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            >
              <circle cx="6" cy="12" r="2.5" />
              <circle cx="18" cy="7" r="2.5" />
              <circle cx="18" cy="17" r="2.5" />
              <path d="m8.3 10.9 7.4-2.8M8.3 13.1l7.4 2.8" />
            </svg>
          </span>
          <div>
            <h2
              id="create-relationship-title"
              className="text-xl font-semibold tracking-[-0.025em]"
            >
              Create relationship
            </h2>
            <p
              id="create-relationship-description"
              className="mt-1.5 text-sm leading-5 text-muted"
            >
              Add a meaningful connection to this workspace map.
            </p>
          </div>
        </div>
        <button
          type="button"
          aria-label="Close relationship dialog"
          disabled={isSubmitting}
          onClick={closeDialog}
          className="grid size-8 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-surface-raised hover:text-foreground disabled:opacity-50"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            className="size-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          >
            <path d="m5 5 10 10M15 5 5 15" />
          </svg>
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5 px-6 pb-6 pt-2">
        <div className="relative overflow-hidden rounded-xl border border-[var(--cortex-graph-divider)] bg-[rgb(7_11_18/0.72)] px-5 py-4 shadow-[inset_0_1px_12px_rgb(0_0_0/0.24)]">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 opacity-60 [background-image:radial-gradient(circle,rgb(120_160_255/0.12)_1px,transparent_1px)] [background-size:20px_20px]"
          />
          <div className="relative grid grid-cols-[minmax(0,1fr)_5rem_minmax(0,1fr)] items-center gap-3">
            <Endpoint label="From" node={source} />
            <div className="flex min-w-0 flex-col items-center gap-2.5" aria-label="Related to">
              <span className="whitespace-nowrap rounded-full border border-accent-bright/20 bg-accent/10 px-2 py-1 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-accent-bright">
                Related to
              </span>
              <div className="flex w-full items-center text-accent-bright" aria-hidden="true">
                <span className="h-px min-w-0 flex-1 bg-gradient-to-r from-transparent to-accent-bright/60" />
                <svg
                  viewBox="0 0 12 12"
                  className="size-3 shrink-0"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="m4 2 4 4-4 4" />
                </svg>
                <span className="h-px min-w-0 flex-1 bg-gradient-to-l from-transparent to-accent-bright/20" />
              </div>
            </div>
            <Endpoint label="To" node={target} />
          </div>
        </div>

        <Field
          id="relationship-rationale"
          label="Why are these nodes connected?"
          hint={`Optional · ${rationale.length}/${RATIONALE_MAX_LENGTH}`}
        >
          <textarea
            ref={rationaleRef}
            id="relationship-rationale"
            value={rationale}
            rows={4}
            maxLength={RATIONALE_MAX_LENGTH}
            aria-describedby="relationship-rationale-hint"
            disabled={isSubmitting}
            onChange={(event) => setRationale(event.target.value)}
            placeholder="Add context that will help teammates understand this connection."
            className={`${fieldControlClassName} resize-none py-3 leading-6`}
          />
        </Field>

        <FeedbackAlert message={error} />

        <div className="flex justify-end gap-2 pt-1">
          <Button
            type="button"
            variant="ghost"
            disabled={isSubmitting}
            onClick={closeDialog}
          >
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={isSubmitting}>
            {isSubmitting ? "Creating…" : "Create relationship"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}

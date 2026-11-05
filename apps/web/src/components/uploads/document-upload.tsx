"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ApiError, apiRequest } from "@/lib/api";
import type { UploadResult } from "@/lib/api-types";

/**
 * T-9.2: dropping a PRD or spec into the workspace.
 *
 * The drop zone is a `<label>` wrapping a real file input rather than a styled
 * `<div>` with a click handler: that way the keyboard and screen-reader paths
 * are the browser's own, and dragging is an enhancement on top of a control
 * that already works without it.
 *
 * `dragDepth` is a counter, not a boolean. `dragleave` fires every time the
 * pointer crosses into a child element, so a boolean flickers the highlight off
 * while the file is still over the zone.
 *
 * Uploads go one at a time. The request is synchronous server-side — it parses
 * the document and writes the graph before answering — so firing a folder's
 * worth at once would open as many parallel parses, and the per-file results
 * would arrive interleaved with no way to say which failed.
 */

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.text";

type Outcome = {
  filename: string;
  message: string;
  failed: boolean;
};

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-6">
      <path d="M12 16V4m0 0L8 8m4-4 4 4" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  );
}

export function DocumentUpload({
  workspaceId,
  onUploaded,
}: {
  workspaceId: string;
  /** Called after each successful upload so the source list refreshes. */
  onUploaded?: () => void;
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragDepth, setDragDepth] = useState(0);
  const [uploading, setUploading] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);

  async function send(file: File) {
    setUploading(file.name);
    const body = new FormData();
    body.append("file", file);

    try {
      const result = await apiRequest<UploadResult>(
        `/api/workspaces/${workspaceId}/uploads`,
        // No Content-Type header: the browser has to set the multipart
        // boundary itself, and naming the type would omit it.
        { method: "POST", body },
      );
      setOutcomes((current) => [
        {
          filename: result.filename,
          message: `${result.replaced ? "Replaced" : "Added"} ${result.filename} — ${result.sections} ${result.sections === 1 ? "section" : "sections"} indexed.`,
          failed: false,
        },
        ...current,
      ]);
      onUploaded?.();
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      setOutcomes((current) => [
        {
          filename: file.name,
          // The server names the reason — unsupported type, over the limit, or
          // unreadable — and that sentence is what the reader needs.
          message:
            requestError instanceof ApiError
              ? requestError.message
              : `Could not upload ${file.name}. The Cortex server is unreachable.`,
          failed: true,
        },
        ...current,
      ]);
    } finally {
      setUploading(null);
    }
  }

  async function handle(files: FileList | null) {
    if (!files || files.length === 0) return;
    for (const file of Array.from(files)) {
      await send(file);
    }
    // Let the same file be picked again after a failure the reader has fixed.
    if (inputRef.current) inputRef.current.value = "";
  }

  const isDragging = dragDepth > 0;
  const busy = uploading !== null;

  return (
    <section aria-labelledby="upload-heading" className="mt-12">
      <div className="border-b border-border/30 pb-4">
        <h2 id="upload-heading" className="text-base font-semibold text-foreground">
          Documents
        </h2>
        <p className="mt-1 text-sm text-muted">
          Upload a PRD, spec or notes and Cortex indexes its text straight away.
        </p>
      </div>

      <label
        onDragEnter={(event) => {
          event.preventDefault();
          setDragDepth((depth) => depth + 1);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragDepth((depth) => Math.max(0, depth - 1))}
        onDrop={(event) => {
          event.preventDefault();
          setDragDepth(0);
          void handle(event.dataTransfer?.files ?? null);
        }}
        className={`mt-6 flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent ${
          isDragging
            ? "border-accent bg-accent/5 text-foreground"
            : "border-border/40 text-muted hover:border-border/70 hover:bg-surface-raised/40"
        } ${busy ? "cursor-wait opacity-70" : ""}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          disabled={busy}
          onChange={(event) => void handle(event.target.files)}
          className="sr-only"
        />
        <UploadIcon />
        <span className="text-sm font-medium text-foreground">
          {busy ? `Reading ${uploading}…` : "Drop files here, or choose files"}
        </span>
        <span className="text-xs text-muted">
          PDF, Word (.docx) or text — up to 10 MB each
        </span>
      </label>

      <div aria-live="polite">
        {outcomes.length > 0 ? (
          <ul className="mt-5 space-y-2">
            {outcomes.map((outcome, index) => (
              <li
                key={`${outcome.filename}-${index}`}
                className={`text-sm leading-6 ${outcome.failed ? "text-red-300" : "text-foreground"}`}
              >
                {outcome.message}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {outcomes.length > 0 ? (
        <Button
          type="button"
          size="small"
          variant="muted"
          className="mt-4"
          onClick={() => setOutcomes([])}
        >
          Clear
        </Button>
      ) : null}
    </section>
  );
}

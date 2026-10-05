"use client";

import Link from "next/link";

import { GraphView } from "@/components/graph/graph-view";

/**
 * T-14.3: the standalone Graph Explorer page shell.
 *
 * The workspace page (US-41 AC2) renders `GraphView` under its own header; this
 * route keeps a focused, full-width view for deep-linking straight to the canvas
 * without the workspace chrome. Both share `GraphView`, so there is one
 * implementation of the graph.
 */

export function GraphExplorer({ workspaceId }: { workspaceId: string }) {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[var(--cortex-content-width)]">
        <Link
          href={`/workspaces/${workspaceId}`}
          className="text-sm font-medium text-muted transition-colors hover:text-foreground"
        >
          ← Back to workspace
        </Link>

        <h1
          id="graph-title"
          className="mt-8 text-[clamp(2rem,5vw,3.25rem)] font-semibold leading-none tracking-[-0.05em]"
        >
          Graph Explorer
        </h1>

        <div className="mt-8">
          <GraphView workspaceId={workspaceId} height={620} />
        </div>
      </div>
    </main>
  );
}

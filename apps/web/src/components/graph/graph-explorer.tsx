"use client";

import { GraphView } from "@/components/graph/graph-view";

export function GraphExplorer({ workspaceId }: { workspaceId: string }) {
  return (
    <main
      aria-labelledby="graph-title"
      className="flex h-screen min-h-[42rem] flex-col overflow-hidden"
    >
      <header className="flex items-end justify-between gap-8 border-b border-[var(--cortex-graph-divider)] px-7 py-5">
        <div>
          <p className="text-[0.65rem] font-semibold uppercase tracking-[0.2em] text-subtle">
            Workspace map
          </p>
          <h1
            id="graph-title"
            className="mt-1.5 text-2xl font-semibold tracking-[-0.035em] text-foreground"
          >
            Graph
          </h1>
        </div>
        <p className="pb-1 text-sm text-muted">
          Explore the people and work connected in this workspace.
        </p>
      </header>

      <GraphView workspaceId={workspaceId} />
    </main>
  );
}

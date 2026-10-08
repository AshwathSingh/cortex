"use client";

import { useState } from "react";

import { GraphSyncStatus } from "@/components/graph/graph-sync-status";
import { GraphView } from "@/components/graph/graph-view";

export function GraphExplorer({ workspaceId }: { workspaceId: string }) {
  // Bumped when an ingestion lands new data. The canvas is fetched once on
  // mount, so without this a finished re-sync would leave it showing the graph
  // from before the sync it just reported.
  const [graphVersion, setGraphVersion] = useState(0);

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
        <div className="flex flex-col items-end gap-2 pb-1">
          <p className="text-sm text-muted">
            Explore the people and work connected in this workspace.
          </p>
          <GraphSyncStatus
            workspaceId={workspaceId}
            onGraphChanged={() => setGraphVersion((version) => version + 1)}
          />
        </div>
      </header>

      <GraphView workspaceId={workspaceId} reloadToken={graphVersion} />
    </main>
  );
}

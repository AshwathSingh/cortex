"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { GraphCanvas } from "@/components/graph/graph-canvas";
import { GraphInspector, type InspectorState } from "@/components/graph/graph-inspector";
import { buttonClassName } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  GraphEdgeDetails,
  GraphNodeDetails,
  GraphNodeType,
  GraphSelection,
  WorkspaceGraph,
} from "@/lib/api-types";

const NODE_TYPES: {
  type: GraphNodeType;
  label: string;
  colour: string;
  shapeClass: string;
}[] = [
  {
    type: "Author",
    label: "Author",
    colour: "var(--cortex-graph-author)",
    shapeClass: "rounded-full",
  },
  {
    type: "PullRequest",
    label: "Pull request",
    colour: "var(--cortex-graph-pull-request)",
    shapeClass: "rounded-[2px]",
  },
  {
    type: "Issue",
    label: "Issue",
    colour: "var(--cortex-graph-issue)",
    shapeClass: "rotate-45 rounded-[1px]",
  },
];

type State =
  | { kind: "loading" }
  | { kind: "ready"; graph: WorkspaceGraph }
  | { kind: "error"; message: string };

export function GraphView({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [inspectorState, setInspectorState] = useState<InspectorState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const graph = await apiRequest<WorkspaceGraph>(
          `/api/workspaces/${workspaceId}/graph`,
          { signal: controller.signal },
        );
        setState({ kind: "ready", graph });
      } catch (requestError) {
        if (controller.signal.aborted) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        setState({
          kind: "error",
          message:
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to load the graph.",
        });
      }
    }

    void load();
    return () => controller.abort();
  }, [router, workspaceId]);

  useEffect(() => {
    if (!selection) return;
    const selected = selection;
    const controller = new AbortController();

    async function loadDetails() {
      try {
        if (selected.kind === "node") {
          const separator = selected.key.indexOf(":");
          const nodeType = selected.key.slice(0, separator);
          const nodeId = selected.key.slice(separator + 1);
          const details = await apiRequest<GraphNodeDetails>(
            `/api/workspaces/${workspaceId}/graph/nodes/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeId)}`,
            { signal: controller.signal },
          );
          setInspectorState({ kind: "node", details });
        } else {
          const params = new URLSearchParams({
            source_key: selected.edge.source,
            target_key: selected.edge.target,
            edge_type: selected.edge.type,
          });
          const details = await apiRequest<GraphEdgeDetails>(
            `/api/workspaces/${workspaceId}/graph/edges?${params.toString()}`,
            { signal: controller.signal },
          );
          setInspectorState({ kind: "edge", details });
        }
      } catch (requestError) {
        if (controller.signal.aborted) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        setInspectorState({
          kind: "error",
          message: requestError instanceof ApiError
            ? requestError.message
            : "Unable to load graph details.",
        });
      }
    }

    void loadDetails();
    return () => controller.abort();
  }, [router, selection, workspaceId]);

  const graph = state.kind === "ready" ? state.graph : null;
  const isWorkspaceEmpty = graph !== null && graph.nodes.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {graph && !isWorkspaceEmpty ? (
        <div
          className="flex min-h-14 flex-wrap items-center justify-between gap-4 border-b border-[var(--cortex-graph-divider)] px-6 py-2"
        >
          <ul className="flex items-center gap-5" aria-label="Node types">
            {NODE_TYPES.map(({ type, label, colour, shapeClass }) => (
              <li key={type} className="flex items-center gap-2 text-xs text-muted">
                <span
                  aria-hidden="true"
                  className="inline-flex size-3 items-center justify-center"
                >
                  <span
                    className={`block size-2 border-2 ${shapeClass}`}
                    style={{ borderColor: colour }}
                  />
                </span>
                {label}
              </li>
            ))}
          </ul>

          <p className="whitespace-nowrap text-xs text-subtle">
            {graph.nodes.length} nodes · {graph.edges.length} connections
          </p>
        </div>
      ) : null}

      <div className="relative flex min-h-0 flex-1">
        <div className="graph-scene relative min-w-0 flex-1 overflow-hidden" aria-live="polite">
          {state.kind === "loading" ? (
            <div className="grid size-full place-items-center text-sm text-muted">
              Building the graph…
            </div>
          ) : null}

          {state.kind === "error" ? (
            <div className="mx-auto max-w-xl px-6 pt-8">
              <FeedbackAlert message={state.message} />
            </div>
          ) : null}

          {isWorkspaceEmpty ? (
            <section className="grid size-full place-items-center px-6 text-center">
              <div>
                <h2 className="text-xl font-semibold text-foreground">
                  Your graph starts with a source
                </h2>
                <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted">
                  Add a GitHub repository to map its pull requests, issues, and authors.
                </p>
                <Link
                  href={`/workspaces/${workspaceId}/ingest`}
                  className={buttonClassName({
                    className: "mt-7",
                    variant: "primary",
                  })}
                >
                  Add a GitHub repository
                </Link>
              </div>
            </section>
          ) : null}

          {graph && !isWorkspaceEmpty ? (
            <GraphCanvas
              nodes={graph.nodes}
              edges={graph.edges}
              onSelectionChange={(nextSelection) => {
                setSelection(nextSelection);
                if (nextSelection) setInspectorState({ kind: "loading" });
              }}
            />
          ) : null}

          <span id="graph-interaction-help" className="sr-only">
            Drag to pan, use the mouse wheel or graph controls to zoom, and select a
            node or connection to inspect its details. Click empty graph space to close
            the inspector.
          </span>

          {graph?.truncated ? (
            <p
              role="status"
              className="absolute right-5 top-5 rounded-md border border-[var(--cortex-graph-divider)] bg-background/80 px-3 py-2 text-xs text-muted backdrop-blur-sm"
            >
              Display limit reached · showing {graph.nodes.length} nodes
            </p>
          ) : null}
        </div>
        {selection ? (
          <div className="w-[22rem] max-w-[40vw] shrink-0 overflow-y-auto border-l border-[var(--cortex-graph-divider)] p-4">
            <GraphInspector
              selection={selection}
              state={inspectorState}
              onClose={() => setSelection(null)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

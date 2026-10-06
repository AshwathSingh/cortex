"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { GraphCanvas } from "@/components/graph/graph-canvas";
import { GraphInspector, type InspectorState } from "@/components/graph/graph-inspector";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { GraphEdgeDetails, GraphNodeDetails, GraphNodeType, GraphSelection, WorkspaceGraph } from "@/lib/api-types";

/**
 * The graph itself: fetch, legend, canvas and the loading / empty / error states.
 *
 * Deliberately NOT a page — it carries no <main>, no back-link and no <h1>, so it
 * can be embedded under the workspace page's header (US-41 AC2) as well as on the
 * standalone /graph route. Nesting two <main> elements would be invalid HTML.
 *
 * Only Author / PullRequest / Issue are legended, because that is all the graph
 * holds. Requirement, Decision and Evidence come from the Connection Agent, which
 * is not built.
 *
 * Each swatch repeats the canvas's shape as well as its colour, so the legend is
 * still usable without colour vision. Colours come from the --cortex-graph-*
 * tokens in globals.css, the same ones graph-canvas.tsx resolves.
 */

const LEGEND: {
  type: GraphNodeType;
  label: string;
  colour: string;
  /** Mirrors NODE_SHAPES in graph-canvas.tsx. */
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

export function GraphView({
  workspaceId,
  height = 560,
}: {
  workspaceId: string;
  height?: number;
}) {
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
    const selectedNodeKey = selection.kind === "node" ? selection.key : null;
    const selectedEdge = selection.kind === "edge" ? selection.edge : null;
    const controller = new AbortController();

    async function loadDetails() {
      try {
        if (selectedNodeKey !== null) {
          const separator = selectedNodeKey.indexOf(":");
          const nodeType = selectedNodeKey.slice(0, separator);
          const nodeId = selectedNodeKey.slice(separator + 1);
          const details = await apiRequest<GraphNodeDetails>(
            `/api/workspaces/${workspaceId}/graph/nodes/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeId)}`,
            { signal: controller.signal },
          );
          setInspectorState({ kind: "node", details });
        } else {
          const params = new URLSearchParams({
            source_key: selectedEdge!.source,
            target_key: selectedEdge!.target,
            edge_type: selectedEdge!.type,
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
  const isEmpty = graph !== null && graph.nodes.length === 0;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted">
          {graph
            ? `${graph.nodes.length} nodes · ${graph.edges.length} connections`
            : "Loading the knowledge graph…"}
        </p>

        {graph && !isEmpty ? (
          <ul className="flex flex-wrap items-center gap-4" aria-label="Node types">
            {LEGEND.map(({ type, label, colour, shapeClass }) => (
              <li key={type} className="flex items-center gap-2 text-sm text-muted">
                <span
                  aria-hidden="true"
                  className="inline-flex size-3.5 items-center justify-center"
                >
                  <span
                    className={`block size-2.5 border-2 ${shapeClass}`}
                    style={{ borderColor: colour }}
                  />
                </span>
                {label}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <FeedbackAlert message={state.kind === "error" ? state.message : null} />

      {graph?.truncated ? (
        <p role="status" className="mt-5 text-sm text-subtle">
          This workspace is larger than the display limit — showing the first{" "}
          {graph.nodes.length} nodes.
        </p>
      ) : null}

      <div className="mt-6" aria-live="polite">
        {state.kind === "loading" ? (
          <p className="text-sm text-muted">Building the graph…</p>
        ) : null}

        {isEmpty ? (
          <section className="rounded-panel border border-border/50 bg-surface/40 px-6 py-14 text-center">
            <h3 className="text-lg font-semibold text-foreground">
              Nothing in this workspace yet
            </h3>
            <p className="mx-auto mt-3 max-w-prose text-sm text-muted">
              Add a GitHub repository and its pull requests, issues and authors will
              appear here as a connected graph.
            </p>
            <Link
              href={`/workspaces/${workspaceId}/ingest`}
              className="mt-8 inline-flex min-h-11 items-center rounded-control bg-accent px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover"
            >
              Add a GitHub repository
            </Link>
          </section>
        ) : null}

        {graph && !isEmpty ? (
          <div className={selection ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]" : ""}>
            <div className="min-w-0">
              <GraphCanvas
                nodes={graph.nodes}
                edges={graph.edges}
                height={height}
                onSelectionChange={(nextSelection) => {
                  setSelection(nextSelection);
                  if (nextSelection) setInspectorState({ kind: "loading" });
                }}
              />
            </div>
            {selection ? (
              <GraphInspector
                selection={selection}
                state={inspectorState}
                onClose={() => setSelection(null)}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

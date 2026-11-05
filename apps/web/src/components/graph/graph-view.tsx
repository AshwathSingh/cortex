"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { GraphCanvas } from "@/components/graph/graph-canvas";
import { GraphComments } from "@/components/graph/graph-comments";
import { GraphInspector, type InspectorState } from "@/components/graph/graph-inspector";
import { buttonClassName } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { useOptionalWorkspace } from "@/components/workspaces/workspace-context";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  GraphEdgeDetails,
  GraphNodeDetails,
  GraphNodeType,
  GraphSelection,
  WorkspaceGraph,
} from "@/lib/api-types";
import { activityKey, targetFor } from "@/lib/graph-comment-target";
import { useCommentActivity } from "@/lib/use-comment-activity";

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

export function GraphView({
  workspaceId,
  reloadToken = 0,
}: {
  workspaceId: string;
  /** Change it to refetch the graph; the header bumps it after an ingestion. */
  reloadToken?: number;
}) {
  const router = useRouter();
  const workspaceContext = useOptionalWorkspace();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [inspectorState, setInspectorState] = useState<InspectorState>({ kind: "loading" });
  // T-27.4: which nodes and edges carry comments, for the canvas badges.
  const { activity, refresh: refreshActivity } = useCommentActivity(workspaceId);

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
        const message =
          requestError instanceof ApiError
            ? requestError.message
            : "Unable to load the graph.";
        // A refresh that fails must not take the graph down with it: what is on
        // screen is still the last thing the server successfully sent, and
        // replacing it with an error loses work the user can still read. Only
        // the first load, which has nothing to fall back on, shows the error.
        setState((previous) =>
          previous.kind === "ready" ? previous : { kind: "error", message },
        );
      }
    }

    void load();
    return () => controller.abort();
  }, [reloadToken, router, workspaceId]);

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
  const commentTarget = targetFor(selection);

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

          <div className="flex items-center gap-5">
            {/* Only shown once something is actually commented on: a legend
                entry for a mark the reader will never see is just noise. */}
            {activity.length > 0 ? (
              <p className="flex items-center gap-2 whitespace-nowrap text-xs text-muted">
                <span
                  aria-hidden="true"
                  className="block size-2.5 rounded-full"
                  style={{ backgroundColor: "var(--cortex-graph-comment)" }}
                />
                Unseen comments
              </p>
            ) : null}
            <p className="whitespace-nowrap text-xs text-subtle">
              {graph.nodes.length} nodes · {graph.edges.length} connections
            </p>
          </div>
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
              commentActivity={activity}
              onSelectionChange={(nextSelection) => {
                setSelection(nextSelection);
                if (nextSelection) setInspectorState({ kind: "loading" });
              }}
            />
          ) : null}

          <span id="graph-interaction-help" className="sr-only">
            Drag to pan, use the mouse wheel or graph controls to zoom, and select a
            node or connection to inspect its details and its comments. A filled dot
            marks comments you have not read. Click empty graph space to close
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
            >
              {commentTarget ? (
                <GraphComments
                  // Keyed on the target, so selecting a different node starts a
                  // clean thread instead of carrying the last draft across.
                  key={activityKey(commentTarget)}
                  workspaceId={workspaceId}
                  target={commentTarget}
                  currentUserId={workspaceContext?.user?.id ?? null}
                  onActivityChange={refreshActivity}
                />
              ) : null}
            </GraphInspector>
          </div>
        ) : null}
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";

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

const ALL_NODE_TYPES = NODE_TYPES.map(({ type }) => type);
const NO_HIGHLIGHTS: string[] = [];

type State =
  | { kind: "loading" }
  | { kind: "ready"; graph: WorkspaceGraph; requestKey: string; requestError?: string; requestErrorKey?: string }
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
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [inspectorState, setInspectorState] = useState<InspectorState>({ kind: "loading" });
  const [selectedTypes, setSelectedTypes] = useState<GraphNodeType[]>(ALL_NODE_TYPES);
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [relationshipNotice, setRelationshipNotice] = useState("");
  const [linkSource, setLinkSource] = useState<string | null>(null);
  const [linkMode, setLinkMode] = useState(false);
  const requestKey = JSON.stringify([searchTerm, [...selectedTypes].sort()]);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchTerm(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const params = new URLSearchParams();
        if (searchTerm) params.set("q", searchTerm);
        for (const type of selectedTypes) params.append("types", type);
        if (selectedTypes.length === 0) params.set("types", "");
        const serializedParams = params.toString();
        const query = serializedParams ? `?${serializedParams}` : "";
        const graph = await apiRequest<WorkspaceGraph>(
          `/api/workspaces/${workspaceId}/graph${query}`,
          { signal: controller.signal },
        );
        setState({ kind: "ready", graph, requestKey });
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
        setState((previous) => previous.kind === "ready"
          ? { ...previous, requestError: message, requestErrorKey: requestKey }
          : { kind: "error", message });
      }
    }

    void load();
    return () => controller.abort();
  }, [reloadToken, requestKey, router, searchTerm, selectedTypes, workspaceId]);

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
  const graphMatchesRequest = state.kind === "ready" && state.requestKey === requestKey;
  const isWorkspaceEmpty = graph !== null
    && graph.nodes.length === 0
    && !searchTerm
    && selectedTypes.length === ALL_NODE_TYPES.length;
  const isSearchEmpty = graph !== null && graph.nodes.length === 0 && Boolean(searchTerm);
  const visibleNodes = useMemo(
    () => graph ? graph.nodes.filter((node) => selectedTypes.includes(node.type)) : [],
    [graph, selectedTypes],
  );
  const visibleKeys = useMemo(() => new Set(visibleNodes.map((node) => node.key)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => graph
      ? graph.edges.filter((edge) => visibleKeys.has(edge.source) && visibleKeys.has(edge.target))
      : [],
    [graph, visibleKeys],
  );
  const highlightedNodeKeys = useMemo(
    () => graphMatchesRequest && searchTerm ? visibleNodes.map((node) => node.key) : NO_HIGHLIGHTS,
    [graphMatchesRequest, searchTerm, visibleNodes],
  );

  function selectTypes(nextTypes: GraphNodeType[]) {
    setSelectedTypes(nextTypes);
    if (!selection) return;

    const nextVisibleKeys = new Set(
      (graph?.nodes ?? [])
        .filter((node) => nextTypes.includes(node.type))
        .map((node) => node.key),
    );
    const selectionRemainsVisible = selection.kind === "node"
      ? nextVisibleKeys.has(selection.key)
      : (graph?.edges ?? []).some((edge) =>
          nextVisibleKeys.has(edge.source)
          && nextVisibleKeys.has(edge.target)
          && edge.source === selection.edge.source
          && edge.target === selection.edge.target
          && edge.type === selection.edge.type,
        );
    if (!selectionRemainsVisible) setSelection(null);
  }

  function toggleType(type: GraphNodeType) {
    const nextTypes = selectedTypes.includes(type)
      ? selectedTypes.filter((selected) => selected !== type)
      : [...selectedTypes, type];
    selectTypes(nextTypes);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSelection(null);
    setSearchTerm(searchInput.trim());
  }

  function updateSearchInput(value: string) {
    setSearchInput(value);
    setSelection(null);
  }


  async function removeSelectedEdge() {
    if (selection?.kind !== "edge" || state.kind !== "ready") return;
    const edge = selection.edge;
    if (!window.confirm("Remove this relationship from the workspace graph?")) return;
    const previous = state.graph;
    setState({ ...state, graph: { ...previous, edges: previous.edges.filter((item) =>
      !(item.source === edge.source && item.target === edge.target && item.type === edge.type)) } });
    setSelection(null);
    setRelationshipNotice("");
    try {
      await apiRequest(`/api/workspaces/${workspaceId}/graph/edges`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_key: edge.source, target_key: edge.target, edge_type: edge.type }),
      });
      setRelationshipNotice("Relationship removed.");
    } catch {
      setState((current) => current.kind === "ready" ? { ...current, graph: previous } : current);
      setRelationshipNotice("Failed to remove relationship. Please try again.");
    }
  }

  async function handleCanvasSelection(nextSelection: GraphSelection) {
    if (linkSource && nextSelection?.kind === "node") {
      if (linkSource === nextSelection.key) {
        setRelationshipNotice("Choose two different nodes.");
        return;
      }
      const currentGraph = state.kind === "ready" ? state.graph : null;
      if (currentGraph?.edges.some((edge) =>
        (edge.source === linkSource && edge.target === nextSelection.key)
        || (edge.source === nextSelection.key && edge.target === linkSource))) {
        setRelationshipNotice("That relationship already exists.");
        setLinkSource(null);
        return;
      }
      const rationale = window.prompt("Why are these nodes connected? (optional)") ?? "";
      setLinkSource(null);
      try {
        const edge = await apiRequest<{ source: string; target: string; type: string }>(
          `/api/workspaces/${workspaceId}/graph/edges`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source_key: linkSource, target_key: nextSelection.key,
              relationship_type: "RELATED_TO", rationale }),
          });
        setState((current) => current.kind === "ready" ? { ...current,
          graph: { ...current.graph, edges: [...current.graph.edges, edge] } } : current);
        setRelationshipNotice("Relationship added.");
      } catch {
        setRelationshipNotice("Unable to add relationship. Check your permissions and try again.");
      }
      return;
    }
    setSelection(nextSelection);
    if (nextSelection) setInspectorState({ kind: "loading" });
  }

  function clearSearch() {
    setSearchInput("");
    setSearchTerm("");
    setSelection(null);
  }

  const isUpdatingGraph = Boolean(
    graph && (!graphMatchesRequest || searchInput.trim() !== searchTerm),
  );
  const resultSummary = searchTerm
    ? `${visibleNodes.length} ${visibleNodes.length === 1 ? "match" : "matches"}`
    : `${visibleNodes.length} ${visibleNodes.length === 1 ? "node" : "nodes"}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {graph && !isWorkspaceEmpty ? (
        <div
          className="border-b border-[var(--cortex-graph-divider)] bg-background/30 px-6 py-3"
        >
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            <form
              role="search"
              onSubmit={submitSearch}
              className="relative min-w-[18rem] flex-1 basis-[24rem] sm:max-w-[30rem]"
            >
              <label htmlFor="graph-search" className="sr-only">
                Search artifacts
              </label>
              <svg
                aria-hidden="true"
                viewBox="0 0 20 20"
                className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-subtle"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
              >
                <circle cx="8.5" cy="8.5" r="4.75" />
                <path d="m12 12 4 4" />
              </svg>
              <input
                id="graph-search"
                type="text"
                role="searchbox"
                inputMode="search"
                enterKeyHint="search"
                value={searchInput}
                maxLength={200}
                autoComplete="off"
                aria-describedby="graph-search-status"
                onChange={(event) => updateSearchInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && searchInput) {
                    event.preventDefault();
                    clearSearch();
                  }
                }}
                placeholder="Search this graph"
                className="h-10 w-full appearance-none rounded-xl border border-border/45 bg-surface/70 pl-10 pr-10 text-sm text-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.025)] outline-none transition-[border-color,background-color,box-shadow] placeholder:text-subtle hover:border-border/70 focus-visible:border-accent-bright/70 focus-visible:bg-surface focus-visible:ring-2 focus-visible:ring-accent-bright/15"
              />
              {searchInput ? (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={clearSearch}
                  className="absolute right-2 top-1/2 grid size-7 -translate-y-1/2 place-items-center rounded-lg text-subtle transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
                >
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 20 20"
                    className="size-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  >
                    <path d="m6 6 8 8M14 6l-8 8" />
                  </svg>
                </button>
              ) : null}
            </form>

            <span
              aria-hidden="true"
              className="hidden h-6 w-px bg-[var(--cortex-graph-divider)] lg:block"
            />

            <fieldset className="flex flex-wrap items-center gap-1.5">
              <legend className="sr-only">Filter graph by artifact type</legend>
              {NODE_TYPES.map(({ type, label, colour, shapeClass }) => {
                const selected = selectedTypes.includes(type);
                return (
                  <button
                    key={type}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => toggleType(type)}
                    className={`inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-medium transition-[border-color,background-color,color] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      selected
                        ? "border-border/45 bg-surface-raised/80 text-foreground"
                        : "border-transparent bg-transparent text-subtle hover:border-border/25 hover:bg-surface/50 hover:text-muted"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className="inline-flex size-3 items-center justify-center"
                    >
                      <span
                        className={`block size-2 border-2 ${shapeClass} ${
                          selected ? "opacity-100" : "opacity-45"
                        }`}
                        style={{ borderColor: colour }}
                      />
                    </span>
                    {label}
                  </button>
                );
              })}
              {selectedTypes.length !== ALL_NODE_TYPES.length ? (
                <button
                  type="button"
                  onClick={() => selectTypes(ALL_NODE_TYPES)}
                  className="h-9 rounded-lg px-2.5 text-xs font-medium text-accent-bright transition-colors hover:bg-accent/10 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  Reset
                </button>
              ) : null}
            </fieldset>

            <p
              id="graph-search-status"
              role="status"
              aria-live="polite"
              className="ml-auto whitespace-nowrap px-2 text-xs text-subtle"
            >
              {isUpdatingGraph
                ? "Updating…"
                : `${resultSummary} · ${visibleEdges.length} ${
                    visibleEdges.length === 1 ? "connection" : "connections"
                  }`}
            </p>
          </div>
        </div>
      ) : null}
      {state.kind === "ready" && state.requestError && state.requestErrorKey === requestKey ? (
        <div className="px-6 py-2"><FeedbackAlert message={state.requestError} /></div>
      ) : null}
      {relationshipNotice ? <p role="status" className="px-6 py-2 text-sm text-muted">{relationshipNotice}</p> : null}

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

          {isSearchEmpty ? (
            <section className="grid size-full place-items-center px-6 text-center" aria-live="polite">
              <div>
                <h2 className="text-lg font-semibold text-foreground">No artifacts match “{searchTerm}”</h2>
                <p className="mt-2 text-sm text-muted">Try another keyword or clear your search.</p>
              </div>
            </section>
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

          {graph && !isWorkspaceEmpty && visibleNodes.length === 0 ? (
            <section className="grid size-full place-items-center px-6 text-center">
              <div>
                <h2 className="text-lg font-semibold text-foreground">
                  No artifacts match these filters
                </h2>
                <p className="mt-2 text-sm text-muted">
                  Select another artifact type or show all types to restore the graph.
                </p>
                <button
                  type="button"
                  onClick={() => selectTypes(ALL_NODE_TYPES)}
                  className="mt-4 rounded-lg border border-border/60 px-3 py-2 text-sm font-medium text-accent transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  Show all artifact types
                </button>
              </div>
            </section>
          ) : null}

          {graph && !isWorkspaceEmpty && visibleNodes.length > 0 ? (
            <>
              <button
                type="button"
                onClick={() => {
                  if (linkMode) {
                    setLinkMode(false);
                    setLinkSource(null);
                    setRelationshipNotice("");
                    return;
                  }
                  setLinkSource(null);
                  setLinkMode(true);
                  setRelationshipNotice("Select the first node, then the second node to connect them.");
                }}
                className="absolute right-4 top-4 z-10 rounded-lg border border-border bg-background/90 px-3 py-2 text-xs font-medium text-foreground shadow"
              >
                {linkMode ? "Cancel relationship" : "Create relationship"}
              </button>
              <GraphCanvas
                nodes={visibleNodes}
                edges={visibleEdges}
                highlightedNodeKeys={highlightedNodeKeys}
                onSelectionChange={(nextSelection) => {
                  if (linkMode) {
                    if (nextSelection?.kind === "node") {
                      if (!linkSource) setLinkSource(nextSelection.key);
                      else {
                        setLinkMode(false);
                        void handleCanvasSelection(nextSelection);
                      }
                    }
                    return;
                  }
                  void handleCanvasSelection(nextSelection);
                }}
              />
            </>
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
              Display limit reached · showing {visibleNodes.length} nodes
            </p>
          ) : null}
        </div>
        {selection ? (
          <div className="w-[22rem] max-w-[40vw] shrink-0 overflow-y-auto border-l border-[var(--cortex-graph-divider)] p-4">
            <GraphInspector
              selection={selection}
              state={inspectorState}
              onClose={() => setSelection(null)}
              onDelete={() => void removeSelectedEdge()}
              canEdit
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

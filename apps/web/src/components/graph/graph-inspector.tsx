"use client";

import type { GraphEdgeDetails, GraphNodeDetails, GraphSelection } from "@/lib/api-types";

export type InspectorState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "node"; details: GraphNodeDetails }
  | { kind: "edge"; details: GraphEdgeDetails };

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Attributes({ attributes }: { attributes: Record<string, unknown> }) {
  const entries = Object.entries(attributes).filter(([key]) => key !== "body");
  if (entries.length === 0) return null;
  return (
    <section className="mt-6">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Properties</h3>
      <dl className="mt-3 space-y-2">
        {entries.map(([key, value]) => (
          <div key={key} className="grid grid-cols-[minmax(5rem,0.7fr)_minmax(0,1.3fr)] gap-3 text-sm">
            <dt className="break-words text-muted">{key.replaceAll("_", " ")}</dt>
            <dd className="break-words text-foreground">{formatValue(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function OriginLinks({ details }: { details: GraphNodeDetails | GraphEdgeDetails }) {
  const origins = details.origins;
  return (
    <section className="mt-6">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Sources and origins</h3>
      {origins.length ? (
        <ul className="mt-3 space-y-2">
          {origins.map((origin, index) => (
            <li key={`${origin.key}:${origin.relationship ?? "source"}:${index}`}>
              <a
                href={origin.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-medium text-accent underline-offset-4 hover:underline"
              >
                {origin.title}
              </a>
              <p className="mt-0.5 text-xs text-muted">
                {origin.type}
                {origin.relationship ? ` · ${origin.relationship.toLowerCase()} (${origin.direction})` : " · original source"}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-muted">No source links are available for this item.</p>
      )}
    </section>
  );
}

export function GraphInspector({
  selection,
  state,
  onClose,
}: {
  selection: Exclude<GraphSelection, null>;
  state: InspectorState;
  onClose: () => void;
}) {
  const kind = selection.kind === "node" ? "Node" : "Connection";
  const details = state.kind === "node" || state.kind === "edge" ? state.details : null;

  return (
    <aside
      aria-label={`${kind} details`}
      className="rounded-panel border border-border/60 bg-surface/70 p-5"
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{kind} inspector</p>
          <h2 className="mt-1 text-lg font-semibold text-foreground">
            {state.kind === "loading" ? "Loading details…" : details?.title ?? "Details unavailable"}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="inline-flex size-9 shrink-0 items-center justify-center rounded-control border border-border/60 text-muted hover:bg-surface hover:text-foreground"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>

      {state.kind === "loading" ? (
        <p role="status" className="mt-5 text-sm text-muted">Loading graph details…</p>
      ) : null}
      {state.kind === "error" ? (
        <p role="alert" className="mt-5 text-sm text-danger">{state.message}</p>
      ) : null}
      {details ? (
        <>
          <p className="mt-3 text-sm text-muted">{details.type}</p>
          {state.kind === "edge" ? (
            <dl className="mt-4 space-y-2 text-sm">
              <div><dt className="inline text-muted">From </dt><dd className="inline text-foreground">{state.details.source.title}</dd></div>
              <div><dt className="inline text-muted">To </dt><dd className="inline text-foreground">{state.details.target.title}</dd></div>
            </dl>
          ) : null}
          <section className="mt-5">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
              {state.kind === "edge" ? "Evidence" : "Content"}
            </h3>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-foreground">
              {details.content || "No content is available."}
            </p>
          </section>
          <Attributes attributes={details.attributes} />
          <OriginLinks details={details} />
        </>
      ) : null}
    </aside>
  );
}

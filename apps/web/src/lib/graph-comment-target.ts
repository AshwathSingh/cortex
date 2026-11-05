import type { CommentActivity, GraphSelection } from "@/lib/api-types";

/**
 * T-27.3/T-27.4: how a selection on the canvas addresses its comment thread.
 *
 * One function, used by both the inspector and the canvas, so the key a comment
 * is posted against is always the key the badge is drawn from. These strings are
 * the contract with the server (`app.models.graph_comment`): a node is
 * `Label:id`, an edge is `source|TYPE|target` -- the same key
 * `fetch_edge_details` returns.
 */

export type CommentTargetRef = {
  target_kind: "node" | "edge";
  target_key: string;
};

export function edgeTargetKey(edge: {
  source: string;
  target: string;
  type: string;
}): string {
  return `${edge.source}|${edge.type}|${edge.target}`;
}

export function targetFor(selection: GraphSelection): CommentTargetRef | null {
  if (!selection) return null;
  return selection.kind === "node"
    ? { target_kind: "node", target_key: selection.key }
    : { target_kind: "edge", target_key: edgeTargetKey(selection.edge) };
}

/** Index the activity list the way the canvas looks things up: by kind and key. */
export function activityIndex(
  activity: readonly CommentActivity[],
): Map<string, CommentActivity> {
  return new Map(
    activity.map((entry) => [`${entry.target_kind}:${entry.target_key}`, entry]),
  );
}

export function activityKey(ref: CommentTargetRef): string {
  return `${ref.target_kind}:${ref.target_key}`;
}

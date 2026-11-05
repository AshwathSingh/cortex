import { describe, expect, it } from "vitest";

import type { CommentActivity } from "@/lib/api-types";
import {
  activityIndex,
  activityKey,
  edgeTargetKey,
  targetFor,
} from "@/lib/graph-comment-target";

const EDGE = { source: "Author:7", target: "Issue:42", type: "AUTHORED" };

describe("addressing a comment thread", () => {
  it("uses a node's own key", () => {
    expect(targetFor({ kind: "node", key: "Issue:42" })).toEqual({
      target_kind: "node",
      target_key: "Issue:42",
    });
  });

  it("builds an edge key the server will accept", () => {
    /** The same shape `fetch_edge_details` returns, which is what makes the key
     *  a contract rather than two coincidences. */
    expect(edgeTargetKey(EDGE)).toBe("Author:7|AUTHORED|Issue:42");
    expect(targetFor({ kind: "edge", edge: EDGE })).toEqual({
      target_kind: "edge",
      target_key: "Author:7|AUTHORED|Issue:42",
    });
  });

  it("has no target when nothing is selected", () => {
    expect(targetFor(null)).toBeNull();
  });

  it("keeps a node and an edge of the same name apart", () => {
    const node = activityKey({ target_kind: "node", target_key: "Issue:42" });
    const edge = activityKey({ target_kind: "edge", target_key: "Issue:42" });
    expect(node).not.toBe(edge);
  });
});

describe("indexing activity for the canvas", () => {
  function activity(over: Partial<CommentActivity> = {}): CommentActivity {
    return {
      target_kind: "node",
      target_key: "Issue:42",
      total: 2,
      unseen: 1,
      ...over,
    };
  }

  it("finds a target by kind and key", () => {
    const index = activityIndex([activity()]);
    expect(index.get("node:Issue:42")?.unseen).toBe(1);
  });

  it("does not confuse a node with an edge", () => {
    const index = activityIndex([
      activity({ target_kind: "node", total: 1, unseen: 0 }),
      activity({ target_kind: "edge", total: 5, unseen: 5 }),
    ]);

    expect(index.get("node:Issue:42")?.unseen).toBe(0);
    expect(index.get("edge:Issue:42")?.unseen).toBe(5);
  });

  it("is empty for a workspace with no comments", () => {
    expect(activityIndex([]).size).toBe(0);
  });
});

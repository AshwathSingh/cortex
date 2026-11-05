import { describe, expect, it } from "vitest";

import {
  NODE_COLOURS,
  NODE_SHAPES,
  isHubType,
  nodeColour,
  nodeShape,
} from "@/components/graph/graph-canvas";
import type { GraphNodeType } from "@/lib/api-types";

const TYPES: GraphNodeType[] = [
  "Author",
  "PullRequest",
  "Issue",
  "Channel",
  "Message",
];

describe("node types on the canvas", () => {
  it("styles every label the graph can hold", () => {
    for (const type of TYPES) {
      expect(nodeColour(type)).toBe(NODE_COLOURS[type]);
      expect(nodeShape(type)).toBe(NODE_SHAPES[type]);
    }
  });

  it("gives each type a distinct colour and shape", () => {
    // Colour alone never distinguishes a type, so both have to be unique.
    expect(new Set(TYPES.map((type) => NODE_COLOURS[type])).size).toBe(
      TYPES.length,
    );
    expect(new Set(TYPES.map((type) => NODE_SHAPES[type])).size).toBe(
      TYPES.length,
    );
  });

  it("falls back rather than dropping a label the UI does not know", () => {
    expect(nodeColour("Requirement")).toBe("#a4adbd");
    expect(nodeShape("Requirement")).toBe("circle");
  });

  it("treats authors and channels as hubs", () => {
    // Every message in a channel attaches to the one node, so leaf-sized it
    // would disappear under its own edges -- the same reason an author is a hub.
    expect(isHubType("Author")).toBe(true);
    expect(isHubType("Channel")).toBe(true);
    expect(isHubType("Message")).toBe(false);
    expect(isHubType("PullRequest")).toBe(false);
  });
});

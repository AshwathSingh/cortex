import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReviewQueue, type ReviewItem } from "@/components/review/review-queue";

const WORKSPACE_ID = "workspace-1";

describe("ReviewQueue", () => {
  it("shows an honest empty state until review data is connected", () => {
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);
    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.getByText(/no review items yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /review indexed sources/i })).toHaveAttribute("href", `/workspaces/${WORKSPACE_ID}/sources`);
  });

  it("supports the populated state expected from the future review API", () => {
    const items: ReviewItem[] = [{
      id: "signal-1",
      title: "Conflicting authentication decisions",
      summary: "Two sources describe different session expiry rules.",
      kind: "Contradiction",
      priority: "High",
      sourceCount: 2,
    }];
    render(<ReviewQueue workspaceId={WORKSPACE_ID} items={items} />);
    expect(screen.getByText("1 signal needs review")).toBeInTheDocument();
    expect(screen.getByText(items[0].title)).toBeInTheDocument();
    expect(screen.getByText("High priority")).toBeInTheDocument();
    expect(screen.getByText("2 sources")).toBeInTheDocument();
  });
});

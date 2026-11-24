import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceConnectionLayout } from "@/components/sources/source-connection-layout";

describe("SourceConnectionLayout", () => {
  it("accepts source-specific methods, data and optional controls", () => {
    render(
      <SourceConnectionLayout
        backHref="/workspaces/example/sources"
        backLabel="Back to sources"
        sourceName="Slack"
        workspaceName="Cortex"
        description="Connect a source."
        methodTitle="Slack authorization"
        methodDescription="Authorize Cortex in Slack."
        dataTitle="What Cortex will use from Slack"
        dataDescription="Choose which conversations are available."
        dataItems={[
          { label: "Messages", description: "Channel conversation history." },
          { label: "Decisions", description: "Decisions captured in context." },
        ]}
        controls={<button type="button">Choose channels</button>}
      >
        <button type="button">Connect with Slack</button>
      </SourceConnectionLayout>,
    );

    expect(
      screen.getByRole("heading", { name: "Connect Slack" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Cortex")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Connect with Slack" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Messages")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Choose channels" }),
    ).toBeInTheDocument();
  });
});

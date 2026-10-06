import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AppSidebar } from "@/components/navigation/app-sidebar";
import {
  GraphIcon,
  HomeIcon,
  ManageIcon,
  ReviewIcon,
} from "@/components/navigation/sidebar-icons";

const primaryLinks = [
  { label: "Home", href: "/workspaces/demo", icon: HomeIcon, exact: true },
  { label: "Graph", href: "/workspaces/demo/graph", icon: GraphIcon },
  {
    label: "Review",
    href: "/workspaces/demo/review",
    icon: ReviewIcon,
    badge: 3,
  },
];

const baseProps = {
  productLabel: "Cortex",
  workspace: {
    id: "demo",
    label: "Demo project",
    options: [
      { id: "demo", label: "Demo project", detail: "OWNER", href: "/workspaces/demo" },
      { id: "platform", label: "Platform", detail: "EDITOR", href: "/workspaces/platform" },
    ],
    createHref: "/workspaces/new",
  },
  account: {
    label: "Ada Lovelace",
    detail: "ada@example.com",
    href: "/account",
  },
  primaryLinks,
  secondaryLinks: [
    {
      label: "Workspace settings",
      href: "/workspaces/demo/manage",
      icon: ManageIcon,
    },
  ],
};

describe("AppSidebar", () => {
  it("renders configured links and identifies the active route", () => {
    render(
      <AppSidebar {...baseProps} activePath="/workspaces/demo/graph" />,
    );

    expect(screen.getByRole("link", { name: "Graph" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("link", { name: /Review/ })).toHaveTextContent("3");
    expect(
      screen.getByRole("button", {
        name: "Switch workspace. Current workspace: Demo project",
      }),
    ).not.toHaveAttribute("title");
    expect(
      screen.getByRole("heading", { name: "Recent conversations" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/recent questions will appear here/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Workspace settings" }),
    ).toHaveAttribute("href", "/workspaces/demo/manage");
  });

  it("opens an in-sidebar workspace menu", async () => {
    const user = userEvent.setup();
    render(<AppSidebar {...baseProps} activePath="/workspaces/demo" />);
    await user.click(screen.getByRole("button", { name: "Switch workspace. Current workspace: Demo project" }));
    expect(screen.getByRole("navigation", { name: "Workspaces" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Demo project/i })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Platform/i })).toHaveAttribute("href", "/workspaces/platform");
    expect(screen.getByRole("link", { name: /New workspace/i })).toHaveAttribute("href", "/workspaces/new");
  });

  it("closes the workspace menu with Escape", async () => {
    const user = userEvent.setup();
    render(<AppSidebar {...baseProps} activePath="/workspaces/demo" />);
    const trigger = screen.getByRole("button", { name: /switch workspace/i });
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("navigation", { name: "Workspaces" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("does not activate Home for a nested workspace route", () => {
    render(
      <AppSidebar {...baseProps} activePath="/workspaces/demo/review" />,
    );

    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("link", { name: /Review/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

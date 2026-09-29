import { render, screen } from "@testing-library/react";
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
  workspace: { label: "Demo project", href: "/workspaces" },
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
      screen.getByRole("link", {
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

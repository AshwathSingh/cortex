import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ChatConnections } from "@/components/sources/chat-connections";
import type { ChannelOption, ChatConnection } from "@/lib/api-types";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function slack(over: Partial<ChatConnection> = {}): ChatConnection {
  return {
    kind: "slack",
    external_ref: "T0ACME",
    display_name: "Acme",
    installed_by_name: "Ashwath",
    ...over,
  };
}

const CHANNELS: ChannelOption[] = [
  { id: "C1", name: "general" },
  { id: "C2", name: "design" },
];

type Routes = {
  connections?: () => Promise<Response>;
  channels?: () => Promise<Response>;
  ingest?: () => Promise<Response>;
  disconnect?: () => Promise<Response>;
};

/** Routes the four endpoints the component uses, by URL and method. */
function mockApi(routes: Routes = {}) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "DELETE") {
      return (routes.disconnect ?? (() => Promise.resolve(new Response(null, { status: 204 }))))();
    }
    if (url.includes("/api/ingest/")) {
      return (
        routes.ingest ??
        (() => Promise.resolve(json({ source: "Acme", channels: 2, messages: 41 })))
      )();
    }
    if (url.includes("/channels")) {
      return (routes.channels ?? (() => Promise.resolve(json(CHANNELS))))();
    }
    return (routes.connections ?? (() => Promise.resolve(json([]))))();
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderConnections(onIngested = vi.fn()) {
  return render(
    <ChatConnections workspaceId={WORKSPACE_ID} onIngested={onIngested} />,
  );
}

beforeEach(() => {
  replace.mockClear();
  routerMock.refresh.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("offers both providers when nothing is connected", async () => {
  mockApi();
  renderConnections();

  const slackLink = await screen.findByRole("link", { name: "Connect Slack" });
  // A real navigation, not a fetch: the server answers with a 302 to the
  // provider and sets the state cookie on it.
  expect(slackLink).toHaveAttribute(
    "href",
    `/api/sources/slack/install?workspace_id=${WORKSPACE_ID}`,
  );
  expect(
    await screen.findByRole("link", { name: "Connect Discord" }),
  ).toHaveAttribute(
    "href",
    `/api/sources/discord/install?workspace_id=${WORKSPACE_ID}`,
  );
});

it("names the connected team and who connected it", async () => {
  mockApi({ connections: () => Promise.resolve(json([slack()])) });
  renderConnections();

  expect(await screen.findByText("Acme · connected by Ashwath")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Connect Slack" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Connect Discord" })).toBeInTheDocument();
});

it("loads channels only when the picker is opened", async () => {
  const fetchFn = mockApi({ connections: () => Promise.resolve(json([slack()])) });
  renderConnections();
  await screen.findByText("Acme · connected by Ashwath");

  const channelCalls = () =>
    fetchFn.mock.calls.filter(([url]) => String(url).includes("/channels"));
  expect(channelCalls()).toHaveLength(0);

  await userEvent.click(screen.getByRole("button", { name: "Choose channels" }));

  expect(await screen.findByLabelText("#general")).toBeInTheDocument();
  expect(screen.getByLabelText("#design")).toBeInTheDocument();
  expect(channelCalls()).toHaveLength(1);
});

it("ingests exactly the channels that were ticked", async () => {
  const onIngested = vi.fn();
  const fetchFn = mockApi({ connections: () => Promise.resolve(json([slack()])) });
  renderConnections(onIngested);
  await screen.findByText("Acme · connected by Ashwath");
  await userEvent.click(screen.getByRole("button", { name: "Choose channels" }));
  await userEvent.click(await screen.findByLabelText("#design"));

  await userEvent.click(screen.getByRole("button", { name: /Ingest 1 selected/ }));

  await waitFor(() => expect(onIngested).toHaveBeenCalled());
  const [, init] = fetchFn.mock.calls.find(([url]) =>
    String(url).includes("/api/ingest/slack"),
  )!;
  expect(JSON.parse(String(init?.body))).toEqual({
    workspace_id: WORKSPACE_ID,
    channel_ids: ["C2"],
  });
  expect(
    await screen.findByText(/Ingested 41 messages from 2 channels in Acme\./),
  ).toBeInTheDocument();
});

it("cannot ingest without choosing a channel", async () => {
  mockApi({ connections: () => Promise.resolve(json([slack()])) });
  renderConnections();
  await screen.findByText("Acme · connected by Ashwath");
  await userEvent.click(screen.getByRole("button", { name: "Choose channels" }));
  await screen.findByLabelText("#general");

  expect(screen.getByRole("button", { name: /Ingest/ })).toBeDisabled();
});

it("reports the server's reason when an ingestion fails", async () => {
  mockApi({
    connections: () => Promise.resolve(json([slack()])),
    ingest: () =>
      Promise.resolve(
        json({ detail: "Slack rejected Cortex's access to Acme." }, 403),
      ),
  });
  renderConnections();
  await screen.findByText("Acme · connected by Ashwath");
  await userEvent.click(screen.getByRole("button", { name: "Choose channels" }));
  await userEvent.click(await screen.findByLabelText("#general"));
  await userEvent.click(screen.getByRole("button", { name: /Ingest 1 selected/ }));

  expect(
    await screen.findByText("Slack rejected Cortex's access to Acme."),
  ).toBeInTheDocument();
});

it("explains an empty channel list rather than showing nothing", async () => {
  mockApi({
    connections: () => Promise.resolve(json([slack()])),
    channels: () => Promise.resolve(json([])),
  });
  renderConnections();
  await screen.findByText("Acme · connected by Ashwath");

  await userEvent.click(screen.getByRole("button", { name: "Choose channels" }));

  expect(
    await screen.findByText(/Invite Cortex to a channel in Slack/),
  ).toBeInTheDocument();
});

it("surfaces a failure to list channels", async () => {
  mockApi({
    connections: () => Promise.resolve(json([slack()])),
    channels: () =>
      Promise.resolve(json({ detail: "Slack rate limit reached" }, 429)),
  });
  renderConnections();
  await screen.findByText("Acme · connected by Ashwath");

  await userEvent.click(screen.getByRole("button", { name: "Choose channels" }));

  expect(await screen.findByText("Slack rate limit reached")).toBeInTheDocument();
});

it("disconnecting removes the connection and re-reads the list", async () => {
  let connections = [slack()];
  const fetchFn = mockApi({
    connections: () => Promise.resolve(json(connections)),
    disconnect: () => {
      connections = [];
      return Promise.resolve(new Response(null, { status: 204 }));
    },
  });
  renderConnections();
  await screen.findByText("Acme · connected by Ashwath");

  await userEvent.click(screen.getByRole("button", { name: "Disconnect Slack" }));

  expect(await screen.findByRole("link", { name: "Connect Slack" })).toBeInTheDocument();
  expect(
    fetchFn.mock.calls.filter(([, init]) => init?.method === "DELETE"),
  ).toHaveLength(1);
});

it("sends an unauthenticated visitor to log in", async () => {
  mockApi({ connections: () => Promise.resolve(json({ detail: "Not authenticated" }, 401)) });
  renderConnections();

  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});

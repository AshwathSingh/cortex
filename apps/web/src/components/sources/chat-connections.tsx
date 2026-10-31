"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  ChannelOption,
  ChatConnection,
  ChatIngestResult,
  ChatKind,
} from "@/lib/api-types";
import { CHAT_KINDS, CHAT_KIND_LABELS } from "@/lib/source-kinds";

/**
 * T-8.5: connecting Slack and Discord, and choosing which channels to ingest.
 *
 * The authorise step is a full-page navigation rather than a fetch: the server
 * answers `/api/sources/{kind}/install` with a 302 to the provider *and* sets
 * the state cookie that binds the callback to this browser. Following that with
 * fetch would land the redirect inside XHR, where the provider's consent screen
 * cannot be shown and the cookie would be set on a response nobody navigates
 * to.
 *
 * Channels are chosen explicitly (US-08 AC1/AC2) and the picker is only loaded
 * on demand: listing them costs a provider API call against a rate limit that
 * the ingestion itself needs.
 */

type ConnectionsState =
  | { kind: "loading" }
  | { kind: "ready"; connections: ChatConnection[] }
  | { kind: "error"; message: string };

type PickerState =
  | { kind: "closed" }
  | { kind: "loading"; provider: ChatKind }
  | { kind: "ready"; provider: ChatKind; channels: ChannelOption[] }
  | { kind: "error"; provider: ChatKind; message: string };

function SlackIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true" className="size-5">
      <path d="M9 4.5v9M15 10.5v9M4.5 15h9M10.5 9h9" />
    </svg>
  );
}

function DiscordIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-5">
      <path d="M6 18.5 4.5 7A14 14 0 0 1 12 5.5a14 14 0 0 1 7.5 1.5L18 18.5a12 12 0 0 1-6 1.5 12 12 0 0 1-6-1.5Z" />
      <path d="M9.5 12.5h.01M14.5 12.5h.01" />
    </svg>
  );
}

const ICONS: Record<ChatKind, () => React.ReactElement> = {
  slack: SlackIcon,
  discord: DiscordIcon,
};

export function ChatConnections({
  workspaceId,
  onIngested,
}: {
  workspaceId: string;
  /** Called after a successful ingestion so the source list refreshes. */
  onIngested?: () => void;
}) {
  const router = useRouter();
  const [state, setState] = useState<ConnectionsState>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  const [picker, setPicker] = useState<PickerState>({ kind: "closed" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<ChatKind | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const unauthorised = useCallback(
    (requestError: unknown) => {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return true;
      }
      return false;
    },
    [router],
  );

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const connections = await apiRequest<ChatConnection[]>(
          `/api/workspaces/${workspaceId}/connections`,
          { signal: controller.signal },
        );
        setState({ kind: "ready", connections });
      } catch (requestError) {
        if (controller.signal.aborted || unauthorised(requestError)) return;
        setState({
          kind: "error",
          message:
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to load connected chat sources.",
        });
      }
    }

    void load();
    return () => controller.abort();
  }, [unauthorised, version, workspaceId]);

  const connections = state.kind === "ready" ? state.connections : [];
  const connected = new Map(connections.map((entry) => [entry.kind, entry]));

  async function openPicker(provider: ChatKind) {
    setActionError(null);
    setResult(null);
    setSelected(new Set());
    setPicker({ kind: "loading", provider });
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const channels = await apiRequest<ChannelOption[]>(
        `/api/workspaces/${workspaceId}/connections/${provider}/channels`,
        { signal: controller.signal },
      );
      setPicker({ kind: "ready", provider, channels });
    } catch (requestError) {
      if (controller.signal.aborted || unauthorised(requestError)) return;
      setPicker({
        kind: "error",
        provider,
        message:
          requestError instanceof ApiError
            ? requestError.message
            : `Unable to list ${CHAT_KIND_LABELS[provider]} channels.`,
      });
    }
  }

  async function ingest(provider: ChatKind) {
    const channelIds = [...selected];
    if (channelIds.length === 0) return;

    setBusy(provider);
    setActionError(null);
    setResult(null);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const ingested = await apiRequest<ChatIngestResult>(
        `/api/ingest/${provider}`,
        {
          method: "POST",
          body: JSON.stringify({
            workspace_id: workspaceId,
            channel_ids: channelIds,
          }),
          signal: controller.signal,
        },
      );
      setResult(
        `Ingested ${ingested.messages.toLocaleString()} message${ingested.messages === 1 ? "" : "s"} from ${ingested.channels} channel${ingested.channels === 1 ? "" : "s"} in ${ingested.source}.`,
      );
      setPicker({ kind: "closed" });
      setSelected(new Set());
      onIngested?.();
    } catch (requestError) {
      if (controller.signal.aborted || unauthorised(requestError)) return;
      // The server records its own failures against the source, so the Sources
      // row will carry the reason too. This covers what never reached it.
      setActionError(
        requestError instanceof ApiError
          ? requestError.message
          : `Could not read ${CHAT_KIND_LABELS[provider]}. The Cortex server is unreachable.`,
      );
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  async function disconnect(provider: ChatKind) {
    setBusy(provider);
    setActionError(null);
    setResult(null);

    try {
      await apiRequest<void>(
        `/api/workspaces/${workspaceId}/connections/${provider}`,
        { method: "DELETE" },
      );
      setPicker({ kind: "closed" });
      setVersion((current) => current + 1);
    } catch (requestError) {
      if (unauthorised(requestError)) return;
      setActionError(
        requestError instanceof ApiError
          ? requestError.message
          : `Could not disconnect ${CHAT_KIND_LABELS[provider]}.`,
      );
    } finally {
      setBusy(null);
    }
  }

  function toggle(channelId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(channelId)) next.delete(channelId);
      else next.add(channelId);
      return next;
    });
  }

  return (
    <section aria-labelledby="chat-sources-heading" className="mt-12">
      <div className="border-b border-border/30 pb-4">
        <h2
          id="chat-sources-heading"
          className="text-base font-semibold text-foreground"
        >
          Chat sources
        </h2>
        <p className="mt-1 text-sm text-muted">
          Capture decisions made in Slack and Discord channels.
        </p>
      </div>

      {state.kind === "loading" ? (
        <p role="status" className="mt-6 text-sm text-muted">
          Loading connections…
        </p>
      ) : null}

      {state.kind === "error" ? (
        <div className="mt-6 max-w-2xl">
          <FeedbackAlert message={state.message} />
        </div>
      ) : null}

      <FeedbackAlert message={actionError} />
      {result ? (
        <p role="status" className="mt-4 text-sm text-foreground">
          {result}
        </p>
      ) : null}

      {state.kind === "ready" ? (
        <ul className="divide-y divide-border/20">
          {CHAT_KINDS.map((provider) => {
            const label = CHAT_KIND_LABELS[provider];
            const connection = connected.get(provider);
            const Icon = ICONS[provider];
            const isBusy = busy === provider;
            const isPickerOpen = picker.kind !== "closed" && picker.provider === provider;

            return (
              <li key={provider} className="py-5">
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <div className="flex min-w-0 items-center gap-4">
                    <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-border/30 bg-surface-raised text-muted">
                      <Icon />
                    </span>
                    <div className="min-w-0">
                      <p className="font-medium text-foreground">{label}</p>
                      <p className="mt-1 text-xs text-muted">
                        {connection
                          ? connection.installed_by_name
                            ? `${connection.display_name} · connected by ${connection.installed_by_name}`
                            : connection.display_name
                          : `Not connected`}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-3">
                    {connection ? (
                      <>
                        <Button
                          type="button"
                          size="small"
                          onClick={() =>
                            isPickerOpen
                              ? setPicker({ kind: "closed" })
                              : void openPicker(provider)
                          }
                          disabled={isBusy}
                        >
                          {isPickerOpen ? "Cancel" : "Choose channels"}
                        </Button>
                        <Button
                          type="button"
                          size="small"
                          variant="muted"
                          aria-label={`Disconnect ${label}`}
                          onClick={() => void disconnect(provider)}
                          disabled={isBusy}
                        >
                          Disconnect
                        </Button>
                      </>
                    ) : (
                      // A link, not a fetch: the server's 302 to the provider
                      // has to be followed by the browser itself.
                      <a
                        href={`/api/sources/${provider}/install?workspace_id=${encodeURIComponent(workspaceId)}`}
                        className="inline-flex min-h-9 items-center rounded-lg bg-accent px-3 text-sm font-semibold text-background transition-colors hover:bg-accent-bright"
                      >
                        Connect {label}
                      </a>
                    )}
                  </div>
                </div>

                {isPickerOpen ? (
                  <div className="mt-5 rounded-xl border border-border/30 bg-surface-raised/40 p-4">
                    {picker.kind === "loading" ? (
                      <p role="status" className="text-sm text-muted">
                        Loading channels…
                      </p>
                    ) : null}

                    {picker.kind === "error" ? (
                      <FeedbackAlert message={picker.message} />
                    ) : null}

                    {picker.kind === "ready" && picker.channels.length === 0 ? (
                      <p className="text-sm text-muted">
                        No channels are visible to Cortex yet.{" "}
                        {provider === "slack"
                          ? "Invite Cortex to a channel in Slack, then try again."
                          : "Give the Cortex bot access to a channel in Discord, then try again."}
                      </p>
                    ) : null}

                    {picker.kind === "ready" && picker.channels.length > 0 ? (
                      <>
                        <fieldset>
                          <legend className="text-sm font-medium text-foreground">
                            Channels to ingest
                          </legend>
                          <div className="mt-3 grid max-h-64 gap-2 overflow-y-auto sm:grid-cols-2">
                            {picker.channels.map((channel) => (
                              <label
                                key={channel.id}
                                className="flex items-center gap-2.5 text-sm text-muted"
                              >
                                <input
                                  type="checkbox"
                                  checked={selected.has(channel.id)}
                                  onChange={() => toggle(channel.id)}
                                  className="size-4 rounded border-border/40 bg-transparent"
                                />
                                <span className="truncate">#{channel.name}</span>
                              </label>
                            ))}
                          </div>
                        </fieldset>
                        <div className="mt-4 flex items-center gap-3">
                          <Button
                            type="button"
                            size="small"
                            variant="primary"
                            onClick={() => void ingest(provider)}
                            disabled={isBusy || selected.size === 0}
                          >
                            {isBusy
                              ? "Ingesting…"
                              : `Ingest ${selected.size || ""} selected`.trim()}
                          </Button>
                          <p className="text-xs text-muted">
                            Large channels can take a while.
                          </p>
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

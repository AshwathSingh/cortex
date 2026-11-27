"use client";

import Link from "next/link";
import { Button, buttonClassName } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { useWorkspace } from "@/components/workspaces/workspace-context";
import { routes } from "@/lib/routes";
import { useSourceOptions } from "@/lib/use-source-options";
import { canManageSources } from "@/lib/workspace-permissions";

const PROVIDERS = [
  {
    kind: "github",
    title: "GitHub repository",
    description:
      "Index pull requests, issues and their contributors. Public repositories work without signing into GitHub; private repositories need server access.",
    action: "Add repository",
    anchor: null,
  },
  {
    kind: "upload",
    title: "Document upload",
    description:
      "Upload a PRD, specification or notes as PDF, Word or text. No provider account is needed.",
    action: "Upload a document",
    anchor: "documents",
  },
  {
    kind: "slack",
    title: "Slack",
    description:
      "Authorize a Slack connection, then choose the channels to index. Only selected channels are ingested.",
    action: "Set up Slack",
    anchor: "slack",
  },
  {
    kind: "discord",
    title: "Discord",
    description:
      "Connect a Discord server, then choose which text channels Cortex should read.",
    action: "Set up Discord",
    anchor: "discord",
  },
] as const;

/** Shared by the empty inventory and the dedicated Add source destination. */
export function SourceChooser({ workspaceId }: { workspaceId: string }) {
  const { workspace, isLoading } = useWorkspace();
  const { state, refresh } = useSourceOptions(workspaceId);
  const permission = !isLoading && canManageSources(workspace?.permissions);
  const mayAdd =
    permission && state.kind === "ready" && state.data.can_manage_sources;
  return (
    <div className="mt-8 text-left">
      {!isLoading && !permission ? (
        <p className="mb-5 text-sm leading-6 text-muted">
          You have view-only access to sources. Ask a member with source
          management access to add a repository, document or chat channel.
        </p>
      ) : null}
      {state.kind === "loading" || isLoading ? (
        <p role="status" className="mb-5 text-sm text-muted">
          Checking source availability and workspace access…
        </p>
      ) : null}
      {state.kind === "error" ? (
        <div className="mb-5">
          <FeedbackAlert message={state.message} />
          <Button type="button" size="small" className="mt-3" onClick={refresh}>
            Retry source availability
          </Button>
        </div>
      ) : null}
      <ul aria-label="Source types" className="grid gap-4 sm:grid-cols-2">
        {PROVIDERS.map((provider) => {
          const availability =
            state.kind === "ready"
              ? state.data.providers.find((item) => item.kind === provider.kind)
              : null;
          const href = provider.anchor
            ? `${routes.workspace.sources(workspaceId)}#${provider.anchor}`
            : routes.workspace.ingest(workspaceId);
          return (
            <li
              key={provider.kind}
              className="flex min-w-0 flex-col rounded-xl border border-border/30 bg-surface-raised/30 p-5"
            >
              <h3 className="text-base font-semibold text-foreground">
                {provider.title}
              </h3>
              <p className="mt-2 text-sm leading-6 text-muted">
                {provider.description}
              </p>
              <div className="mt-auto pt-5">
                {availability?.available && mayAdd ? (
                  <Link
                    href={href}
                    onClick={() => {
                      if (provider.anchor) {
                        const target = document.getElementById(provider.anchor);
                        if (target)
                          requestAnimationFrame(() =>
                            target.focus({ preventScroll: true }),
                          );
                      }
                    }}
                    className={buttonClassName({ size: "small" })}
                  >
                    {provider.action}
                  </Link>
                ) : (
                  <p className="text-xs leading-5 text-muted">
                    {availability?.available
                      ? "Source management access required"
                      : (availability?.reason ??
                        (state.kind === "loading"
                          ? "Checking availability…"
                          : "Availability could not be confirmed."))}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {permission &&
      state.kind === "ready" &&
      !state.data.can_manage_sources ? (
        <p role="status" className="mt-4 text-sm text-muted">
          Your source management access has changed. Refresh the workspace
          before adding a source.
        </p>
      ) : null}
    </div>
  );
}

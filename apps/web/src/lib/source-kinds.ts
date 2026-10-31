import type { ChatKind, WorkspaceSource } from "@/lib/api-types";

/**
 * T-8.5: how each provider is presented on the Sources page.
 *
 * One table rather than conditionals scattered through the component, because
 * the three differ in more than a label: a repository is addressed by
 * `owner/name` and links to GitHub, while a chat source's `repo` field holds an
 * opaque team or guild id that must never be shown to a reader and cannot be
 * turned into a URL without the provider's own deep-link format.
 *
 * `countColumns` is what makes one row template serve all three: the backend
 * reports both pairs of counts on every row and leaves the irrelevant pair at
 * zero, so each kind names the two that mean something plus the shared total.
 */

export type CountColumn = {
  label: string;
  value: (source: WorkspaceSource) => number;
};

export type SourceKindMeta = {
  /** Singular noun for this kind of source, for headings and empty states. */
  noun: string;
  /** How to name one instance on screen. */
  title: (source: WorkspaceSource) => string;
  /** An external link to the source, when the provider has an addressable one. */
  href: (source: WorkspaceSource) => string | null;
  /** Where that link goes, for the screen-reader suffix. */
  destination: string | null;
  countColumns: CountColumn[];
};

export function githubUrl(repo: string) {
  return `https://github.com/${repo.split("/").map(encodeURIComponent).join("/")}`;
}

const INDEXED: CountColumn = {
  label: "Indexed",
  value: (source) => source.total_items,
};

const GITHUB: SourceKindMeta = {
  noun: "repository",
  title: (source) => source.repo,
  href: (source) => githubUrl(source.repo),
  destination: "GitHub",
  countColumns: [
    { label: "Pull requests", value: (source) => source.pull_requests },
    { label: "Issues", value: (source) => source.issues },
    INDEXED,
  ],
};

const CHAT_COLUMNS: CountColumn[] = [
  { label: "Channels", value: (source) => source.channels },
  { label: "Messages", value: (source) => source.messages },
  INDEXED,
];

const SLACK: SourceKindMeta = {
  noun: "Slack workspace",
  // Falls back to the team id only if the name is somehow missing; a bare
  // "T0ACME" is still better than an empty row.
  title: (source) => source.display_name ?? source.repo,
  // Slack has no stable web URL for a team that does not depend on its own
  // subdomain, which the OAuth exchange never returns.
  href: () => null,
  destination: null,
  countColumns: CHAT_COLUMNS,
};

const DISCORD: SourceKindMeta = {
  noun: "Discord server",
  title: (source) => source.display_name ?? source.repo,
  href: (source) => `https://discord.com/channels/${encodeURIComponent(source.repo)}`,
  destination: "Discord",
  countColumns: CHAT_COLUMNS,
};

const KINDS: Record<string, SourceKindMeta> = {
  github: GITHUB,
  slack: SLACK,
  discord: DISCORD,
};

/** An unknown kind still renders: the server may add one before the UI knows it. */
const UNKNOWN: SourceKindMeta = {
  noun: "source",
  title: (source) => source.display_name ?? source.repo,
  href: () => null,
  destination: null,
  countColumns: [INDEXED],
};

export function sourceKindMeta(kind: string): SourceKindMeta {
  return KINDS[kind] ?? UNKNOWN;
}

export const CHAT_KINDS: readonly ChatKind[] = ["slack", "discord"] as const;

export const CHAT_KIND_LABELS: Record<ChatKind, string> = {
  slack: "Slack",
  discord: "Discord",
};

/** What a member is choosing between when they pick channels, per provider. */
export const CHAT_CHANNEL_NOUN: Record<ChatKind, string> = {
  slack: "channel",
  discord: "channel",
};

export function isChatKind(kind: string): kind is ChatKind {
  return kind === "slack" || kind === "discord";
}

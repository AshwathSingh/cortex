import type { WorkspaceSource } from "@/lib/api-types";

/**
 * T-9.1: how each kind of source is presented on the Sources page.
 *
 * One table rather than conditionals scattered through the component, because
 * the kinds differ in more than a label: a repository is addressed by
 * `owner/name` and links to GitHub, while an uploaded document has a filename
 * and no URL at all — the file lives nowhere a browser can open.
 *
 * `countColumns` is what makes one row template serve both: the backend reports
 * every count on every row and leaves the irrelevant ones at zero, so each kind
 * names the ones that mean something plus the shared total.
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
  /** An external link to the source, when there is one to give. */
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

const UPLOAD: SourceKindMeta = {
  noun: "document",
  // `repo` holds the filename for an upload, so either works; display_name is
  // preferred because it is the field that means "what to call this".
  title: (source) => source.display_name ?? source.repo,
  // Nothing to link to: the file was read and discarded, never stored.
  href: () => null,
  destination: null,
  countColumns: [
    { label: "Sections", value: (source) => source.sections },
    INDEXED,
  ],
};

const KINDS: Record<string, SourceKindMeta> = {
  github: GITHUB,
  upload: UPLOAD,
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

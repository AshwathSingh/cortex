import type { WorkspaceRole } from "@/lib/api-types";

const ROLE_STYLES: Record<WorkspaceRole, string> = {
  OWNER: "border-role-owner/40 bg-role-owner/10 text-role-owner",
  EDITOR: "border-role-editor/40 bg-role-editor/10 text-role-editor",
  VIEWER: "border-role-viewer/40 bg-role-viewer/10 text-role-viewer",
};

export function RoleBadge({ role }: { role: string }) {
  const style =
    role in ROLE_STYLES
      ? ROLE_STYLES[role as WorkspaceRole]
      : "border-border/40 bg-surface-raised text-muted";

  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-[0.65rem] font-semibold tracking-[0.08em] ${style}`}
    >
      {role}
    </span>
  );
}

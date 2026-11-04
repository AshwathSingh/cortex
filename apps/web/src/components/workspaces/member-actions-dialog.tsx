"use client";

import {
  type FormEvent,
  type SyntheticEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { Field, fieldControlClassName } from "@/components/ui/form-field";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { ApiError } from "@/lib/api";
import type {
  WorkspaceMember,
  WorkspacePermission,
  WorkspaceRoleDefinition,
} from "@/lib/api-types";
import { listWorkspaceRoles } from "@/lib/invite-client";
import {
  removeWorkspaceMember,
  updateWorkspaceMemberRole,
} from "@/lib/member-client";
import { assignableWorkspaceRoles } from "@/lib/workspace-role-options";

function roleKey(member: WorkspaceMember) {
  return member.role_id
    ? `custom:${member.role_id}`
    : `builtin:${member.role}`;
}

export function MemberActionsDialog({
  member,
  workspaceId,
  currentUserId,
  currentRole,
  permissions,
  onClose,
  onMemberRemoved,
  onMemberUpdated,
}: {
  member: WorkspaceMember;
  workspaceId: string;
  currentUserId?: string;
  currentRole: string;
  permissions: WorkspacePermission[];
  onClose: () => void;
  onMemberRemoved: (userId: string) => void;
  onMemberUpdated: (member: WorkspaceMember) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [roles, setRoles] = useState<WorkspaceRoleDefinition[]>([]);
  const [rolesError, setRolesError] = useState<string | null>(null);
  const [isLoadingRoles, setIsLoadingRoles] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [selectedRoleKey, setSelectedRoleKey] = useState(roleKey(member));
  const [isSaving, setIsSaving] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  const [isConfirmingRemoval, setIsConfirmingRemoval] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "error">(
    "idle",
  );

  const isCurrentUser = member.user_id === currentUserId;
  const targetIsOwner = member.role.toUpperCase() === "OWNER";
  const actorIsOwner = currentRole.toUpperCase() === "OWNER";
  const canManageMember =
    !isCurrentUser &&
    permissions.includes("members.manage") &&
    (!targetIsOwner || actorIsOwner);
  const memberName = member.name?.trim() || member.email || "Workspace member";

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
  }, []);

  useEffect(() => {
    if (!canManageMember) return;
    const controller = new AbortController();

    async function loadRoles() {
      setIsLoadingRoles(true);
      setRolesError(null);
      try {
        setRoles(await listWorkspaceRoles(workspaceId, controller.signal));
      } catch (error) {
        if (controller.signal.aborted) return;
        setRolesError(
          error instanceof ApiError
            ? error.message
            : "Unable to load workspace roles.",
        );
      } finally {
        if (!controller.signal.aborted) setIsLoadingRoles(false);
      }
    }

    void loadRoles();
    return () => controller.abort();
  }, [canManageMember, loadAttempt, workspaceId]);

  const roleOptions = useMemo(
    () => assignableWorkspaceRoles(roles, currentRole, permissions),
    [currentRole, permissions, roles],
  );
  const selectedRole = roleOptions.find(
    (option) => option.key === selectedRoleKey,
  );

  function closeDialog() {
    if (isSaving || isRemoving) return;
    dialogRef.current?.close();
    onClose();
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    closeDialog();
  }

  async function copyEmail() {
    if (!member.email) return;
    try {
      await navigator.clipboard.writeText(member.email);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("error");
    }
  }

  async function saveRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRole || selectedRole.key === roleKey(member)) return;

    setIsSaving(true);
    setActionError(null);
    try {
      const updatedMember = await updateWorkspaceMemberRole(
        workspaceId,
        member.user_id,
        selectedRole.selection,
      );
      onMemberUpdated(updatedMember);
      dialogRef.current?.close();
      onClose();
    } catch (error) {
      setActionError(
        error instanceof ApiError
          ? error.message
          : "Unable to update this member's role.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function removeMember() {
    setIsRemoving(true);
    setActionError(null);
    try {
      await removeWorkspaceMember(workspaceId, member.user_id);
      onMemberRemoved(member.user_id);
      dialogRef.current?.close();
      onClose();
    } catch (error) {
      setActionError(
        error instanceof ApiError
          ? error.message
          : "Unable to remove this member.",
      );
      setIsConfirmingRemoval(false);
    } finally {
      setIsRemoving(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="member-actions-title"
      aria-describedby="member-actions-description"
      aria-modal="true"
      onCancel={handleCancel}
      className="m-auto w-[min(30rem,calc(100%-2rem))] rounded-2xl border border-border/30 bg-surface p-0 text-foreground shadow-[0_28px_80px_rgb(0_0_0/0.48)] backdrop:bg-background/85 backdrop:backdrop-blur-[2px]"
    >
      <div className="flex items-start justify-between gap-5 border-b border-border/20 px-6 py-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2
              id="member-actions-title"
              className="truncate text-lg font-semibold tracking-[-0.02em]"
            >
              {memberName}
            </h2>
            <RoleBadge role={member.role} />
          </div>
          <p
            id="member-actions-description"
            className="mt-1.5 truncate text-sm text-muted"
          >
            {member.email || "No email address available"}
          </p>
        </div>
        <button
          type="button"
          aria-label="Close member actions"
          onClick={closeDialog}
          disabled={isSaving || isRemoving}
          className="grid size-8 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-surface-raised hover:text-foreground disabled:opacity-50"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            className="size-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          >
            <path d="m5 5 10 10M15 5 5 15" />
          </svg>
        </button>
      </div>

      <div className="space-y-5 px-6 py-6">
        {member.email ? (
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-foreground">Email address</p>
              <p className="mt-1 text-xs text-subtle">
                {copyStatus === "copied" ? "Copied to clipboard" : member.email}
              </p>
            </div>
            <Button type="button" size="small" variant="muted" onClick={copyEmail}>
              {copyStatus === "copied" ? "Copied" : "Copy"}
            </Button>
          </div>
        ) : null}

        {canManageMember ? (
          <form onSubmit={saveRole} className="border-t border-border/20 pt-5">
            <Field id="member-role" label="Workspace role">
              <div className="relative mt-2">
                <select
                  id="member-role"
                  value={selectedRoleKey}
                  disabled={isLoadingRoles || isSaving || roleOptions.length === 0}
                  onChange={(event) => setSelectedRoleKey(event.target.value)}
                  className={`${fieldControlClassName} mt-0 h-11 appearance-none pr-10`}
                >
                  {isLoadingRoles ? <option>Loading roles…</option> : null}
                  {roleOptions.map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.name}
                    </option>
                  ))}
                </select>
                <svg
                  aria-hidden="true"
                  viewBox="0 0 20 20"
                  className="pointer-events-none absolute right-3.5 top-1/2 size-4 -translate-y-1/2 text-subtle"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="m6.5 8 3.5 3.5L13.5 8" />
                </svg>
              </div>
              <p className="mt-2 text-xs leading-5 text-subtle">
                {selectedRole?.description || "Choose this member's access level."}
              </p>
            </Field>
            {rolesError ? (
              <>
                <FeedbackAlert message={rolesError} />
                <Button
                  type="button"
                  size="small"
                  className="mt-3"
                  onClick={() => setLoadAttempt((attempt) => attempt + 1)}
                >
                  Retry loading roles
                </Button>
              </>
            ) : null}
            <div className="mt-4 flex justify-end">
              <Button
                type="submit"
                size="small"
                variant="primary"
                disabled={
                  isSaving ||
                  !selectedRole ||
                  selectedRole.key === roleKey(member)
                }
              >
                {isSaving ? "Saving…" : "Save role"}
              </Button>
            </div>
          </form>
        ) : (
          <p className="border-t border-border/20 pt-5 text-xs leading-5 text-subtle">
            {isCurrentUser
              ? "Your access is shown here. Another workspace owner can change it."
              : "You can view this member, but you do not have permission to manage their access."}
          </p>
        )}

        {canManageMember ? (
          <div className="border-t border-border/20 pt-5">
            {isConfirmingRemoval ? (
              <div className="rounded-xl border border-red-400/25 bg-red-500/5 p-4">
                <p className="text-sm font-medium text-foreground">
                  Remove {memberName}?
                </p>
                <p className="mt-1 text-xs leading-5 text-muted">
                  They will immediately lose access to this workspace.
                </p>
                <div className="mt-4 flex justify-end gap-2">
                  <Button
                    type="button"
                    size="small"
                    variant="ghost"
                    disabled={isRemoving}
                    onClick={() => setIsConfirmingRemoval(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="small"
                    variant="danger"
                    disabled={isRemoving}
                    onClick={removeMember}
                  >
                    {isRemoving ? "Removing…" : "Remove member"}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-foreground">Remove access</p>
                  <p className="mt-1 text-xs text-subtle">
                    Remove this person from the workspace.
                  </p>
                </div>
                <Button
                  type="button"
                  size="small"
                  variant="danger"
                  onClick={() => setIsConfirmingRemoval(true)}
                >
                  Remove
                </Button>
              </div>
            )}
          </div>
        ) : null}

        <FeedbackAlert
          message={
            copyStatus === "error"
              ? "Could not copy this email address."
              : actionError
          }
        />
      </div>
    </dialog>
  );
}

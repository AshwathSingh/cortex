"use client";

import {
  type FormEvent,
  type SyntheticEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { Field, fieldControlClassName } from "@/components/ui/form-field";
import type { WorkspaceInvite, WorkspaceRole } from "@/lib/api-types";

export type InviteRoleSelection =
  | { role: WorkspaceRole; role_id?: never }
  | { role?: never; role_id: string };

export type InviteRoleOption = {
  key: string;
  name: string;
  description: string;
  selection: InviteRoleSelection;
  isDefault?: boolean;
};

export type CreatedInvite = Pick<
  WorkspaceInvite,
  "email" | "role" | "expires_at" | "token"
>;

type InviteMemberModalProps = {
  workspaceName: string;
  roles: InviteRoleOption[];
  rolesError?: string | null;
  isLoadingRoles?: boolean;
  onRetryRoles?: () => void;
  onClose: () => void;
  onInvite: (
    email: string,
    selection: InviteRoleSelection,
  ) => Promise<CreatedInvite>;
};

export function InviteMemberModal({
  workspaceName,
  roles,
  rolesError = null,
  isLoadingRoles = false,
  onRetryRoles,
  onClose,
  onInvite,
}: InviteMemberModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [createdInvite, setCreatedInvite] = useState<CreatedInvite | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "error">(
    "idle",
  );

  const defaultRoleKey =
    roles.find((option) => option.isDefault)?.key ?? roles[0]?.key ?? "";
  const selectedRoleKey = roles.some((option) => option.key === roleKey)
    ? roleKey
    : defaultRoleKey;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (!dialog.open) dialog.showModal();
    emailRef.current?.focus();
  }, []);

  function closeDialog() {
    if (isSubmitting) return;
    dialogRef.current?.close();
    onClose();
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    closeDialog();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedRole = roles.find(
      (option) => option.key === selectedRoleKey,
    );
    if (!selectedRole) {
      setSubmitError("Choose a role before creating the invite.");
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const result = await onInvite(email.trim(), selectedRole.selection);
      setCreatedInvite(result);
    } catch (error) {
      setSubmitError(
        error instanceof Error ? error.message : "Unable to create the invite.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  async function copyInviteToken() {
    if (!createdInvite) return;
    try {
      await navigator.clipboard.writeText(createdInvite.token);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("error");
    }
  }

  function inviteAnotherPerson() {
    setEmail("");
    setRoleKey("");
    setSubmitError(null);
    setCreatedInvite(null);
    setCopyStatus("idle");
    window.requestAnimationFrame(() => emailRef.current?.focus());
  }

  return (
    <dialog
      ref={dialogRef}
      aria-describedby="invite-member-description"
      aria-labelledby="invite-member-title"
      aria-modal="true"
      onCancel={handleCancel}
      className="m-auto w-[min(34rem,calc(100%-2rem))] rounded-panel border border-border/35 bg-surface-raised p-0 text-foreground shadow-2xl backdrop:bg-background/80 backdrop:backdrop-blur-sm"
    >
      <div className="border-b border-border/20 px-6 py-5">
        <div className="flex items-start justify-between gap-5">
          <div>
            <h2
              id="invite-member-title"
              className="text-lg font-semibold tracking-[-0.02em]"
            >
              {createdInvite ? "Invite created" : "Invite a member"}
            </h2>
            <p
              id="invite-member-description"
              className="mt-1.5 text-sm leading-6 text-muted"
            >
              {createdInvite
                ? `Share this invite securely with ${createdInvite.email}.`
                : `Give someone access to ${workspaceName}.`}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close invite dialog"
            disabled={isSubmitting}
            onClick={closeDialog}
            className="grid size-9 shrink-0 place-items-center rounded-lg text-xl leading-none text-muted transition hover:bg-surface hover:text-foreground disabled:opacity-50"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>

      {createdInvite ? (
        <div className="px-6 py-5">
          <div className="rounded-control border border-accent-bright/25 bg-accent/10 px-4 py-3 text-sm leading-6 text-foreground">
            Cortex does not email invitations yet. Copy this one-time invite code
            and send it to the intended person.
          </div>

          <div className="mt-5">
            <Field id="created-invite-token" label="Invite code">
              <div className="mt-2 flex gap-2">
                <input
                  id="created-invite-token"
                  readOnly
                  value={createdInvite.token}
                  className={`${fieldControlClassName} mt-0 h-11 min-w-0 font-mono text-xs`}
                />
                <Button
                  type="button"
                  variant="primary"
                  onClick={copyInviteToken}
                >
                  {copyStatus === "copied" ? "Copied" : "Copy code"}
                </Button>
              </div>
            </Field>
            <p className="mt-3 text-xs leading-5 text-subtle">
              Role: {createdInvite.role} · Expires{" "}
              {new Intl.DateTimeFormat(undefined, {
                dateStyle: "medium",
              }).format(new Date(createdInvite.expires_at))}
            </p>
            {copyStatus === "error" ? (
              <FeedbackAlert message="Could not copy the code. Select it and copy it manually." />
            ) : null}
          </div>

          <div className="mt-6 flex justify-end gap-3 border-t border-border/20 pt-5">
            <Button type="button" onClick={inviteAnotherPerson}>
              Invite another
            </Button>
            <Button type="button" variant="primary" onClick={closeDialog}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="px-6 py-5">
          <div className="space-y-5">
            <Field
              id="invite-member-email"
              label="Email address"
              hint="Required"
            >
              <input
                ref={emailRef}
                id="invite-member-email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                disabled={isSubmitting}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="teammate@example.com"
                className={`${fieldControlClassName} h-12`}
              />
            </Field>

            <Field id="invite-member-role" label="Workspace role">
              <select
                id="invite-member-role"
                value={selectedRoleKey}
                disabled={isLoadingRoles || isSubmitting || roles.length === 0}
                onChange={(event) => setRoleKey(event.target.value)}
                className={`${fieldControlClassName} h-12`}
              >
                {isLoadingRoles ? (
                  <option value="">Loading roles…</option>
                ) : null}
                {!isLoadingRoles && roles.length === 0 ? (
                  <option value="">No roles available</option>
                ) : null}
                {roles.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.name} — {option.description}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <FeedbackAlert message={rolesError ?? submitError} />
          {rolesError && onRetryRoles ? (
            <Button
              type="button"
              size="small"
              className="mt-3"
              onClick={onRetryRoles}
            >
              Retry loading roles
            </Button>
          ) : null}

          <div className="mt-6 flex justify-end gap-3 border-t border-border/20 pt-5">
            <Button
              type="button"
              disabled={isSubmitting}
              onClick={closeDialog}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={
                isLoadingRoles || isSubmitting || roles.length === 0 || !email
              }
            >
              {isSubmitting ? "Creating invite…" : "Create invite"}
            </Button>
          </div>
        </form>
      )}
    </dialog>
  );
}

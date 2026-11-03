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
import { createInviteLink } from "@/lib/invite-link";

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
  const selectedRole = roles.find(
    (option) => option.key === selectedRoleKey,
  );
  const inviteLink = createdInvite
    ? createInviteLink(window.location.origin, createdInvite.token)
    : "";

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

  async function copyInviteLink() {
    if (!createdInvite) return;
    try {
      await navigator.clipboard.writeText(inviteLink);
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
      className="m-auto w-[min(30rem,calc(100%-2rem))] rounded-2xl border border-border/30 bg-surface p-0 text-foreground shadow-[0_28px_80px_rgb(0_0_0/0.48)] backdrop:bg-background/85 backdrop:backdrop-blur-[2px]"
    >
      <div className="px-6 pt-6">
        <div className="flex items-start justify-between gap-5">
          <div>
            <h2
              id="invite-member-title"
              className="text-xl font-semibold tracking-[-0.025em]"
            >
              {createdInvite ? "Invite created" : "Invite a member"}
            </h2>
            <p
              id="invite-member-description"
              className="mt-1.5 text-sm leading-5 text-muted"
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
      </div>

      {createdInvite ? (
        <div className="px-6 pb-6 pt-5">
          <div className="rounded-xl border border-border/25 bg-background/35 px-4 py-3 text-sm leading-5 text-muted">
            Cortex does not email invitations yet. Copy this private invite link
            and send it to the intended person.
          </div>

          <div className="mt-5">
            <Field id="created-invite-link" label="Invite link">
              <div className="mt-2 flex gap-2">
                <input
                  id="created-invite-link"
                  readOnly
                  value={inviteLink}
                  className={`${fieldControlClassName} mt-0 h-11 min-w-0 font-mono text-xs`}
                />
                <Button
                  type="button"
                  variant="primary"
                  onClick={copyInviteLink}
                >
                  {copyStatus === "copied" ? "Copied" : "Copy link"}
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
              <FeedbackAlert message="Could not copy the link. Select it and copy it manually." />
            ) : null}
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={inviteAnotherPerson}
            >
              Invite another
            </Button>
            <Button type="button" variant="primary" onClick={closeDialog}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="px-6 pb-6 pt-6">
          <div className="space-y-4">
            <Field id="invite-member-email" label="Email address">
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
                className={`${fieldControlClassName} h-11`}
              />
            </Field>

            <Field id="invite-member-role" label="Workspace role">
              <div className="relative mt-2">
                <select
                  id="invite-member-role"
                  value={selectedRoleKey}
                  aria-describedby="invite-member-role-description"
                  disabled={isLoadingRoles || isSubmitting || roles.length === 0}
                  onChange={(event) => setRoleKey(event.target.value)}
                  className={`${fieldControlClassName} mt-0 h-11 appearance-none pr-10`}
                >
                  {isLoadingRoles ? (
                    <option value="">Loading roles…</option>
                  ) : null}
                  {!isLoadingRoles && roles.length === 0 ? (
                    <option value="">No roles available</option>
                  ) : null}
                  {roles.map((option) => (
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
              <p
                id="invite-member-role-description"
                className="mt-2 text-xs leading-5 text-subtle"
              >
                {selectedRole?.description ?? "Choose the access this person receives."}
              </p>
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

          <div className="mt-6 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={isSubmitting}
              onClick={closeDialog}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              className="disabled:bg-border/15 disabled:text-subtle disabled:opacity-100"
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

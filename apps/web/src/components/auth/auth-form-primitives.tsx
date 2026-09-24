import Link from "next/link";
import type { InputHTMLAttributes, ReactNode } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";

const fieldClassName =
  "mt-2 h-12 w-full rounded-control border border-border/60 bg-surface/70 px-4 text-[0.95rem] text-foreground outline-none transition placeholder:text-subtle hover:border-border focus:border-accent-bright focus:ring-2 focus:ring-accent-bright/20";

type AuthFormLayoutProps = {
  children: ReactNode;
  description: string;
  headingId: string;
  switchHref: string;
  switchLabel: string;
  switchPrompt: string;
  title: string;
};

export function AuthFormLayout({
  children,
  description,
  headingId,
  switchHref,
  switchLabel,
  switchPrompt,
  title,
}: AuthFormLayoutProps) {
  return (
    <section aria-labelledby={headingId} className="w-full max-w-[28rem]">
      <h1
        id={headingId}
        className="text-[clamp(2.25rem,4vw,2.75rem)] font-semibold leading-[1.05] tracking-[-0.05em] text-foreground"
      >
        {title}
      </h1>
      <p className="mt-3 text-base leading-7 text-muted">{description}</p>

      <p className="mt-5 flex items-center gap-2.5 text-sm text-muted">
        <svg
          aria-hidden="true"
          viewBox="0 0 20 20"
          className="size-4 shrink-0 text-accent-bright"
          fill="none"
        >
          <path
            d="M10 2.5 16 5v4.5c0 3.7-2.4 6.4-6 8-3.6-1.6-6-4.3-6-8V5z"
            stroke="currentColor"
            strokeWidth="1.4"
          />
          <path
            d="m7.4 10 1.7 1.7 3.7-4"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.4"
          />
        </svg>
        Your context stays yours.
      </p>

      <GitHubAuthButton />
      <AuthDivider />
      {children}

      <p className="mt-7 text-center text-sm text-muted">
        {switchPrompt}{" "}
        <Link
          href={switchHref}
          className="font-semibold text-accent-bright transition-colors hover:text-foreground"
        >
          {switchLabel}
        </Link>
      </p>
    </section>
  );
}

function GitHubAuthButton() {
  return (
    <button
      type="button"
      disabled
      title="GitHub authentication is not configured yet"
      className="mt-9 flex min-h-12 w-full cursor-not-allowed items-center justify-center gap-3 rounded-control border border-border/40 bg-surface/50 px-5 text-sm font-semibold text-muted opacity-70"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 fill-current">
        <path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.14.68-3.8-1.33-3.8-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.03-.7.08-.69.08-.69 1.13.08 1.73 1.16 1.73 1.16 1.01 1.73 2.65 1.23 3.3.94.1-.73.39-1.23.72-1.51-2.5-.29-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.15a10.7 10.7 0 0 1 5.64 0c2.15-1.46 3.1-1.15 3.1-1.15.61 1.55.23 2.7.11 2.98.72.79 1.16 1.79 1.16 3.02 0 4.32-2.64 5.26-5.15 5.55.4.35.76 1.04.76 2.1v3.12c0 .3.2.65.78.54A11.25 11.25 0 0 0 12 .75Z" />
      </svg>
      Continue with GitHub (soon)
    </button>
  );
}

function AuthDivider() {
  return (
    <div className="my-7 flex items-center gap-4" aria-hidden="true">
      <span className="h-px flex-1 bg-border/40" />
      <span className="text-[0.7rem] font-medium uppercase tracking-[0.12em] text-subtle">
        or use email
      </span>
      <span className="h-px flex-1 bg-border/40" />
    </div>
  );
}

type FormFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  hint?: string;
  id: string;
  label: string;
};

export function FormField({ hint, id, label, ...inputProps }: FormFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;

  return (
    <div>
      <div className={hint ? "flex items-baseline justify-between gap-4" : undefined}>
        <label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
        </label>
        {hint ? (
          <span id={hintId} className="text-xs text-subtle">
            {hint}
          </span>
        ) : null}
      </div>
      <input
        {...inputProps}
        id={id}
        aria-describedby={inputProps["aria-describedby"] ?? hintId}
        className={fieldClassName}
      />
    </div>
  );
}

export function AuthFormError({ message }: { message: string | null }) {
  return <FeedbackAlert message={message} />;
}

export function AuthSubmitButton({
  children,
  disabled = false,
}: {
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="mt-8 flex min-h-12 w-full items-center justify-center rounded-control bg-accent px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover disabled:cursor-wait disabled:opacity-60"
    >
      {children}
    </button>
  );
}

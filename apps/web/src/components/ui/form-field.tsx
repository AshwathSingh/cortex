import type { InputHTMLAttributes, ReactNode } from "react";

export const fieldControlClassName =
  "mt-2 w-full rounded-control border border-border/60 bg-surface/70 px-4 text-[0.95rem] text-foreground outline-none transition placeholder:text-subtle hover:border-border focus:border-accent-bright focus:ring-2 focus:ring-accent-bright/20 disabled:opacity-60";

export function Field({
  children,
  hint,
  id,
  label,
}: {
  children: ReactNode;
  hint?: ReactNode;
  id: string;
  label: string;
}) {
  return (
    <div>
      <div className={hint ? "flex items-baseline justify-between gap-4" : undefined}>
        <label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
        </label>
        {hint ? (
          <span id={`${id}-hint`} className="text-xs text-subtle">
            {hint}
          </span>
        ) : null}
      </div>
      {children}
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
    <Field hint={hint} id={id} label={label}>
      <input
        {...inputProps}
        id={id}
        aria-describedby={inputProps["aria-describedby"] ?? hintId}
        className={`${fieldControlClassName} h-12`}
      />
    </Field>
  );
}

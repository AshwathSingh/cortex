import type { ReactNode } from "react";

export function SettingsSection({
  id,
  title,
  description,
  children,
  danger = false,
}: {
  id: string;
  title: string;
  description: string;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className={`overflow-hidden rounded-2xl border bg-surface/55 ${
        danger ? "border-red-400/20" : "border-border/30"
      }`}
    >
      <div className="border-b border-border/20 px-6 py-5">
        <h2
          id={`${id}-title`}
          className="text-base font-semibold tracking-[-0.015em] text-foreground"
        >
          {title}
        </h2>
        <p className="mt-1 text-sm leading-6 text-muted">{description}</p>
      </div>
      {children}
    </section>
  );
}

export function SettingsValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-subtle">
        {label}
      </p>
      <p className="mt-1.5 truncate text-sm text-foreground">{value}</p>
    </div>
  );
}

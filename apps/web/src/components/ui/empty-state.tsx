import type { ReactNode } from "react";

export function EmptyState({
  action,
  description,
  icon,
  title,
}: {
  action?: ReactNode;
  description: ReactNode;
  icon: ReactNode;
  title: ReactNode;
}) {
  return (
    <section className="mt-12 border-y border-border/25 py-16 text-center">
      <span className="mx-auto grid size-11 place-items-center rounded-xl border border-border/35 bg-surface-raised text-muted">
        {icon}
      </span>
      <h2 className="mt-5 text-lg font-semibold text-foreground">{title}</h2>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted">
        {description}
      </p>
      {action}
    </section>
  );
}

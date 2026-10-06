import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

export function SettingsRow({
  action,
  description,
  title,
}: {
  action?: ReactNode;
  description: ReactNode;
  title: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-5 px-6 py-5">
      <div>
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <p className="mt-1 text-sm leading-6 text-muted">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function UnavailableAction({
  children,
  danger = false,
}: {
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <Button
      type="button"
      disabled
      size="small"
      variant={danger ? "danger" : "muted"}
      className="disabled:cursor-not-allowed"
    >
      {children}
    </Button>
  );
}

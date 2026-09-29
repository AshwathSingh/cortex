import type { ReactNode } from "react";

function IconFrame({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  );
}

export function HomeIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <path d="m3 10 9-7 9 7" />
      <path d="M5 9v11h14V9M9 20v-6h6v6" />
    </IconFrame>
  );
}

export function GraphIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="7" r="2.5" />
      <circle cx="11" cy="18" r="2.5" />
      <path d="m8.3 6.4 7.2.4M7.2 8.2l2.7 7.4M16.7 9.1l-4.1 6.8" />
    </IconFrame>
  );
}

export function ReviewIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <path d="M12 3 2.8 19h18.4L12 3Z" />
      <path d="M12 9v4M12 16.5h.01" />
    </IconFrame>
  );
}

export function SourcesIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7" />
    </IconFrame>
  );
}

export function ManageIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="8" cy="12" r="2" />
      <circle cx="13" cy="18" r="2" />
    </IconFrame>
  );
}

export function AppearanceIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <path d="M21 12a9 9 0 1 1-9-9 7 7 0 0 0 9 9Z" />
    </IconFrame>
  );
}

export function AccountIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
    </IconFrame>
  );
}

export function WorkspaceIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M3 9h18M9 9v12" />
    </IconFrame>
  );
}

export function ChevronLeftIcon({ className }: { className?: string }) {
  return (
    <IconFrame className={className}>
      <path d="m15 18-6-6 6-6" />
    </IconFrame>
  );
}

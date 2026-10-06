type CortexMarkProps = {
  className?: string;
};

export function CortexMark({ className }: CortexMarkProps) {
  return (
    <svg
      viewBox="0 0 40 40"
      role="img"
      aria-label="Cortex"
      className={className}
    >
      <rect
        x="1"
        y="1"
        width="38"
        height="38"
        rx="11"
        fill="var(--cortex-sidebar-logo-background, #101827)"
        stroke="var(--cortex-sidebar-border)"
      />
      <path
        d="M19.7 10.2a5.2 5.2 0 0 0-9.4 3.1 4.9 4.9 0 0 0-1 8.6 5.2 5.2 0 0 0 6.1 7.8 5 5 0 0 0 4.3-2.5v-17Z"
        fill="none"
        stroke="var(--cortex-sidebar-accent)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M20.3 10.2a5.2 5.2 0 0 1 9.4 3.1 4.9 4.9 0 0 1 1 8.6 5.2 5.2 0 0 1-6.1 7.8 5 5 0 0 1-4.3-2.5v-17Z"
        fill="none"
        stroke="var(--cortex-sidebar-accent)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="m13.2 17.2 3.2 2.4-2.3 3.6M26.8 17.2l-3.2 2.4 2.3 3.6M20 14.1v11.8"
        fill="none"
        stroke="var(--cortex-sidebar-icon)"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="13.2" cy="17.2" r="1.45" fill="var(--cortex-sidebar-accent)" />
      <circle cx="14.1" cy="23.2" r="1.45" fill="var(--cortex-sidebar-accent)" />
      <circle cx="26.8" cy="17.2" r="1.45" fill="var(--cortex-sidebar-accent)" />
      <circle cx="25.9" cy="23.2" r="1.45" fill="var(--cortex-sidebar-accent)" />
      <circle cx="20" cy="14.1" r="1.45" fill="var(--cortex-sidebar-accent)" />
      <circle cx="20" cy="25.9" r="1.45" fill="var(--cortex-sidebar-accent)" />
    </svg>
  );
}

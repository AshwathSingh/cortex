import type { ButtonHTMLAttributes } from "react";

const variants = {
  primary: "bg-accent text-foreground enabled:hover:bg-accent-hover",
  outline:
    "border border-border/40 text-foreground enabled:hover:border-border enabled:hover:bg-surface-raised",
  muted:
    "border border-border/40 text-muted enabled:hover:border-border enabled:hover:bg-surface-raised enabled:hover:text-foreground",
  danger: "border border-red-400/25 text-red-300",
} as const;

const sizes = {
  small: "min-h-9 rounded-lg px-3 text-xs",
  medium: "min-h-10 rounded-lg px-4 text-sm",
  large: "min-h-12 rounded-control px-5 text-sm",
} as const;

type ButtonStyleOptions = {
  className?: string;
  size?: keyof typeof sizes;
  variant?: keyof typeof variants;
};

export function buttonClassName({
  className = "",
  size = "medium",
  variant = "outline",
}: ButtonStyleOptions = {}) {
  return `inline-flex shrink-0 items-center justify-center font-semibold transition-colors disabled:opacity-60 ${sizes[size]} ${variants[variant]} ${className}`.trim();
}

export function Button({
  className,
  size,
  variant,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & ButtonStyleOptions) {
  return (
    <button
      {...props}
      className={buttonClassName({ className, size, variant })}
    />
  );
}

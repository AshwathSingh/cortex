/** A soft, low-contrast network that quietly suggests connected project memory. */
export function AuthProductPreview() {
  return (
    <section
      aria-labelledby="product-preview-heading"
      className="relative hidden min-h-screen overflow-hidden border-l border-border/25 bg-[linear-gradient(155deg,rgb(15_26_44/94%),rgb(8_14_24/98%))] lg:block"
    >
      <h2 id="product-preview-heading" className="sr-only">
        Cortex keeps project context connected
      </h2>

      <div className="absolute inset-0 bg-[radial-gradient(circle_at_54%_48%,rgb(59_103_220/14%),transparent_30%),radial-gradient(circle_at_84%_12%,rgb(59_103_220/7%),transparent_28%)]" />

      <svg
        aria-hidden="true"
        viewBox="0 0 720 900"
        preserveAspectRatio="xMidYMid slice"
        className="auth-network-breathe absolute inset-0 size-full"
        fill="none"
      >
        <defs>
          <linearGradient id="calm-link" x1="210" y1="230" x2="540" y2="670" gradientUnits="userSpaceOnUse">
            <stop stopColor="#78a0ff" stopOpacity="0.04" />
            <stop offset="0.5" stopColor="#78a0ff" stopOpacity="0.18" />
            <stop offset="1" stopColor="#78a0ff" stopOpacity="0.03" />
          </linearGradient>
          <radialGradient id="calm-core">
            <stop stopColor="#a9beff" stopOpacity="0.82" />
            <stop offset="0.2" stopColor="#6488ec" stopOpacity="0.42" />
            <stop offset="1" stopColor="#3b67dc" stopOpacity="0" />
          </radialGradient>
          <filter id="calm-blur" x="-200%" y="-200%" width="500%" height="500%">
            <feGaussianBlur stdDeviation="18" />
          </filter>
        </defs>

        <path
          d="M206 260C290 308 322 362 388 442M388 442c74-58 112-102 168-138M388 442c-20 92-52 150-88 216"
          stroke="url(#calm-link)"
          strokeLinecap="round"
          strokeWidth="1.2"
        />

        <circle cx="388" cy="442" r="104" fill="#3b67dc" opacity="0.1" filter="url(#calm-blur)" />
        <circle cx="388" cy="442" r="54" fill="url(#calm-core)" opacity="0.72" />

        <g fill="#8dabff">
          <circle cx="206" cy="260" r="4.5" fillOpacity="0.32" />
          <circle cx="556" cy="304" r="5" fillOpacity="0.3" />
          <circle cx="300" cy="658" r="4" fillOpacity="0.26" />
        </g>
        <circle cx="388" cy="442" r="5" fill="#dce5ff" fillOpacity="0.75" />
      </svg>
    </section>
  );
}

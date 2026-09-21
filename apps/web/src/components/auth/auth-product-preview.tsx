/**
 * Signup product-trailer template: a Cortex prompt floating above a project
 * knowledge graph, previewing how questions connect to underlying context.
 */
export function AuthProductPreview() {
  return (
    <section
      aria-labelledby="product-preview-heading"
      className="relative hidden min-h-[42rem] overflow-hidden rounded-[1.5rem] bg-[radial-gradient(circle_at_52%_100%,rgb(64_105_224/72%),transparent_42%),radial-gradient(circle_at_84%_18%,rgb(42_76_145/32%),transparent_42%),linear-gradient(155deg,#111c30_0%,#0b1220_58%,#101a2d_100%)] lg:block"
    >
      <h2 id="product-preview-heading" className="sr-only">
        Ask Cortex about your connected project
      </h2>

      <svg
        aria-hidden="true"
        viewBox="0 0 800 760"
        preserveAspectRatio="xMidYMax slice"
        className="absolute inset-x-0 bottom-0 h-[72%] w-full"
        fill="none"
      >
        <defs>
          <linearGradient id="graph-fade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#78a0ff" stopOpacity="0" />
            <stop offset="32%" stopColor="#78a0ff" stopOpacity="0.16" />
            <stop offset="100%" stopColor="#78a0ff" stopOpacity="0.72" />
          </linearGradient>
          <linearGradient id="node-fade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#8eb0ff" stopOpacity="0" />
            <stop offset="35%" stopColor="#8eb0ff" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#8eb0ff" stopOpacity="0.9" />
          </linearGradient>
        </defs>
        <path
          d="M400 52 252 214 102 356M400 52l158 174 142 118M252 214l30 214-138 184M252 214l210 158M558 226l-96 146 64 238M282 428l180-56 170 116M282 428l-46 226M462 372l12 282M632 488l-38 166M102 356l42 256"
          stroke="url(#graph-fade)"
          strokeWidth="2"
        />
        <g fill="url(#node-fade)">
          <circle cx="400" cy="52" r="5" />
          <circle cx="252" cy="214" r="7" />
          <circle cx="558" cy="226" r="6" />
          <circle cx="102" cy="356" r="6" />
          <circle cx="282" cy="428" r="8" />
          <circle cx="462" cy="372" r="7" />
          <circle cx="700" cy="344" r="6" />
          <circle cx="632" cy="488" r="8" />
          <circle cx="144" cy="612" r="8" />
          <circle cx="236" cy="654" r="7" />
          <circle cx="474" cy="654" r="8" />
          <circle cx="526" cy="610" r="7" />
          <circle cx="594" cy="654" r="8" />
        </g>
      </svg>

      <div className="absolute inset-x-0 top-[34%] z-10 mx-auto w-[min(82%,38rem)]">
        <p className="mb-4 text-center text-xs font-semibold uppercase tracking-[0.16em] text-accent-bright">
          Ask your project
        </p>
        <div className="flex min-h-[5.25rem] items-center justify-between gap-5 rounded-[1.25rem] border border-white/25 bg-white/[0.94] px-6 shadow-[0_24px_70px_rgb(0_0_0/32%)] backdrop-blur-xl">
          <p className="text-lg font-medium tracking-[-0.015em] text-[#111827]">
            Why did we choose Neo4j?
          </p>
          <span
            aria-hidden="true"
            className="flex size-11 shrink-0 items-center justify-center rounded-full bg-[#0b1220] text-xl text-white"
          >
            ↑
          </span>
        </div>
        <p className="mt-4 text-center text-sm text-white/55">
          Answers grounded in the people, documents, and code behind the work.
        </p>
      </div>
    </section>
  );
}

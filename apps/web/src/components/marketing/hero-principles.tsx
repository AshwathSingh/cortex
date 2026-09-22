const principles = [
  {
    title: "Evidence-linked",
    description: "Every answer stays traceable to its source.",
  },
  {
    title: "Agent-ready",
    description: "Project context persists between sessions.",
  },
  {
    title: "Built for judgment",
    description: "Contradictions come back to people.",
  },
] as const;

/**
 * Homepage principle strip: three short product promises beneath the hero copy
 * that explain how Cortex memory stays trustworthy and useful to agents.
 */
export function HeroPrinciples() {
  return (
    <dl className="mt-12 grid max-w-[42rem] gap-7 border-t border-border/40 pt-7 sm:grid-cols-3 sm:gap-6 lg:mt-auto">
      {principles.map((principle) => (
        <div key={principle.title}>
          <dt className="text-sm font-semibold text-foreground">
            {principle.title}
          </dt>
          <dd className="mt-2 text-sm leading-6 text-subtle">
            {principle.description}
          </dd>
        </div>
      ))}
    </dl>
  );
}

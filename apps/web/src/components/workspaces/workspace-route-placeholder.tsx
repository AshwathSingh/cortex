type WorkspaceRoutePlaceholderProps = {
  eyebrow: string;
  title: string;
  description: string;
};

export function WorkspaceRoutePlaceholder({
  eyebrow,
  title,
  description,
}: WorkspaceRoutePlaceholderProps) {
  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <section aria-labelledby="route-title">
          <p className="text-sm font-medium text-accent-bright">{eyebrow}</p>
          <h1
            id="route-title"
            className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]"
          >
            {title}
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
            {description}
          </p>
        </section>
      </div>
    </main>
  );
}

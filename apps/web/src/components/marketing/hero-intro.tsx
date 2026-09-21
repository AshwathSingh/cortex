/**
 * Homepage hero-copy template: the left-hand message that introduces Cortex,
 * states the primary value proposition, and explains the product in one line.
 */
export function HeroIntro() {
    return (
        <div className="ml-[0.2em] max-w-[42rem]">
            <p className="ml-[0.2rem] text-sm font-semibold uppercase tracking-[0.16em] text-accent-bright">
                Engineering memory, made useful
            </p>

            <h1
                id="hero-title"
                className="mt-4 text-[clamp(3.1rem,5.2vw,4.5rem)] font-semibold leading-[1.02] tracking-[-0.055em] text-foreground sm:mt-5"
            >
                <span className="block">your project already</span>
                <span className="block text-accent-bright">
                    knows the answer.
                </span>
            </h1>

            <p className="ml-[0.2rem] mt-1 max-w-[36rem] text-lg leading-[1.6] tracking-[-0.01em] text-muted sm:mt-8 sm:text-xl">
                Cortex connects decisions, discussions, and source evidence into
                durable memory, so engineering agents can reason with the full
                project context.
            </p>
        </div>
    );
}

import Link from "next/link";

/**
 * Homepage decision-chat template: the right-hand example showing how someone
 * asks Cortex about a decision, receives a sourced answer, and follows it up.
 */
export function DecisionPreview() {
    return (
        <aside
            aria-labelledby="decision-preview-title"
            className="w-full max-w-[34rem] justify-self-end lg:-mt-8"
        >
            <article className="rounded-[1.75rem] border border-border/60 bg-[linear-gradient(145deg,rgb(18_29_46/96%),rgb(10_17_29/94%))] p-7 shadow-[0_28px_80px_rgb(0_0_0/24%)] backdrop-blur-xl sm:p-9">
                <header className="flex items-center justify-between gap-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-accent-bright">
                        Ask Cortex
                    </p>
                    <p className="text-xs font-medium text-subtle">
                        Architecture
                    </p>
                </header>

                <div className="mt-6">
                    <p className="text-xs font-semibold text-subtle">You</p>
                    <h2
                        id="decision-preview-title"
                        className="mt-2 text-[clamp(1.65rem,2.4vw,2rem)] font-semibold leading-tight tracking-[-0.04em] text-foreground"
                    >
                        Why did we choose Neo4j?
                    </h2>
                </div>

                <div className="mt-6">
                    <p className="text-xs font-semibold text-accent-bright">
                        Cortex
                    </p>
                    <p className="mt-2 max-w-[31rem] text-base leading-[1.65] text-muted sm:text-lg">
                        Neo4j was chosen after Maya Chen&apos;s architecture review
                        connected the PRD&apos;s traceability requirement to the
                        relationship model validated in GitHub PR #42.
                    </p>
                </div>

                <ul
                    aria-label="Sources referenced in this answer"
                    className="mt-6 flex flex-wrap gap-x-5 gap-y-3 text-sm text-muted"
                >
                    <li>
                        <Link
                            href="/graph?source=maya-chen"
                            className="flex min-h-9 items-center gap-2 rounded-md transition-colors hover:text-foreground"
                        >
                            <span
                                aria-hidden="true"
                                className="flex size-6 items-center justify-center rounded-full bg-accent/20 text-[0.625rem] font-semibold text-accent-bright"
                            >
                                MC
                            </span>
                            Maya Chen
                        </Link>
                    </li>
                    <li>
                        <Link
                            href="/graph?source=architecture-prd"
                            className="flex min-h-9 items-center gap-2 rounded-md transition-colors hover:text-foreground"
                        >
                            <svg
                                aria-hidden="true"
                                viewBox="0 0 20 20"
                                className="size-5 text-accent-bright"
                                fill="none"
                            >
                                <path
                                    d="M5 2.75h6l4 4v10.5H5zM11 2.75v4h4M7.75 10h4.5M7.75 13h4.5"
                                    stroke="currentColor"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth="1.4"
                                />
                            </svg>
                            Architecture PRD
                        </Link>
                    </li>
                    <li>
                        <Link
                            href="/graph?source=pr-42"
                            className="flex min-h-9 items-center gap-2 rounded-md transition-colors hover:text-foreground"
                        >
                            <svg
                                aria-hidden="true"
                                viewBox="0 0 20 20"
                                className="size-5 text-accent-bright"
                                fill="none"
                            >
                                <circle cx="5" cy="4" r="1.75" stroke="currentColor" strokeWidth="1.4" />
                                <circle cx="5" cy="16" r="1.75" stroke="currentColor" strokeWidth="1.4" />
                                <circle cx="15" cy="16" r="1.75" stroke="currentColor" strokeWidth="1.4" />
                                <path
                                    d="M5 5.75v8.5M9 5h2a4 4 0 0 1 4 4v5.25M9 5l2-2M9 5l2 2"
                                    stroke="currentColor"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth="1.4"
                                />
                            </svg>
                            GitHub PR #42
                        </Link>
                    </li>
                </ul>

                <footer className="mt-7 flex justify-end border-t border-border/40 pt-4">
                    <Link
                        href="/graph"
                        className="flex min-h-11 items-center gap-2 rounded-md text-sm font-semibold text-foreground transition-colors hover:text-accent-bright"
                    >
                        View in graph
                        <svg
                            aria-hidden="true"
                            viewBox="0 0 16 16"
                            className="size-4"
                            fill="none"
                        >
                            <path
                                d="M3 8h9m-3.5-3.5L12 8l-3.5 3.5"
                                stroke="currentColor"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth="1.5"
                            />
                        </svg>
                    </Link>
                </footer>

                <Link
                    href="/chat"
                    aria-label="Open Cortex chat to ask a follow-up question"
                    className="mt-5 flex min-h-12 items-center justify-between gap-4 rounded-control border border-border/60 bg-background/55 py-2 pl-4 pr-2 text-sm font-medium text-subtle transition-colors hover:border-border hover:bg-background/75 hover:text-foreground"
                >
                    <span>Ask a follow-up…</span>
                    <span
                        aria-hidden="true"
                        className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-foreground"
                    >
                        ↑
                    </span>
                </Link>
            </article>

            <div className="mt-6 flex flex-wrap items-center gap-x-7 gap-y-4 px-2 sm:px-3">
                <Link
                    href="/signup"
                    className="flex min-h-12 min-w-44 items-center justify-center rounded-control bg-accent px-6 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover"
                >
                    Try Cortex
                </Link>
                <Link
                    href="#how-it-works"
                    className="flex min-h-11 items-center gap-2 rounded-md px-1 text-sm font-semibold text-muted transition-colors hover:text-foreground"
                >
                    See how it works
                    <span aria-hidden="true">→</span>
                </Link>
            </div>
        </aside>
    );
}

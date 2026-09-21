import { DecisionPreview } from "@/components/marketing/decision-preview";
import { HeroIntro } from "@/components/marketing/hero-intro";
import { SiteHeader } from "@/components/marketing/site-header";

export default function Home() {
  return (
    <main className="min-h-screen">
      <SiteHeader />
      <section
        id="product"
        aria-labelledby="hero-title"
        className="mx-auto grid max-w-[var(--cortex-content-width)] gap-16 px-[var(--cortex-page-gutter)] pb-24 pt-16 sm:pt-20 lg:grid-cols-[minmax(0,1.08fr)_minmax(26rem,0.92fr)] lg:pt-24"
      >
        <HeroIntro />
        <DecisionPreview />
      </section>
    </main>
  );
}

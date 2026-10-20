import Link from "next/link";
import type { CSSProperties } from "react";
import { HomeMotion } from "@/app/_components/home-motion";
import { LogoStacked } from "@/components/logo";
import { SpotlightCard } from "@/components/spotlight-card";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STEPS = [
  { title: "Génère une école", text: "Petite, moyenne ou grande : promos, groupes de TD, sous-groupes de TP, profs à temps partiel, salles." },
  { title: "Résous avec CP-SAT", text: "Aucune double réservation, salles adaptées, disponibilités respectées ; trous, créneaux tardifs et TP séparés minimisés." },
  { title: "Explique et replanifie", text: "Sans solution, l'ensemble minimal de contraintes contradictoires. Un prof absent : le moins de cours déplacés possible." },
];

const PROOFS = ["Contraintes dures toujours respectées", "Conflits expliqués", "Export PDF et .ics"];

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-12 sm:py-16">
      <HomeMotion>
        <div className="flex flex-col gap-14">
          <section className="grid grid-cols-1 items-center gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
            <div className="flex flex-col gap-6">
              <LogoStacked className="self-start" />
              <h1 className="home-title max-w-[15ch] font-heading text-5xl leading-[1.02] sm:text-6xl">
                Des emplois du temps <em>sans conflit</em>, calculés par optimisation.
              </h1>
              <span aria-hidden="true" className="home-rule h-px w-32 origin-left bg-foreground" />
              <p className="home-lede max-w-[50ch] text-lg text-muted-foreground">
                Fedi&apos;s Planner place chaque séance d&apos;une semaine de cours avec un solveur de contraintes, explique pourquoi quand c&apos;est
                impossible, et replanifie en touchant le moins de cours possible.
              </p>
              <div className="home-actions flex flex-wrap gap-3">
                <Link href="/planner" className={cn(buttonVariants({ size: "lg" }), "btn-shine")}>
                  Ouvrir le planificateur
                </Link>
              </div>
              <ul className="home-lede flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground">
                {PROOFS.map((proof) => (
                  <li key={proof}>
                    <span className="font-bold text-[#1f7a4d] dark:text-[#5fcf95]">✓</span> {proof}
                  </li>
                ))}
              </ul>
            </div>
            <WeekIllustration />
          </section>

          <ol className="home-steps grid grid-cols-1 gap-4 sm:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="home-step">
                <SpotlightCard className="flex h-full flex-col gap-2 rounded-xl border p-5">
                  <span className="font-heading text-4xl text-muted-foreground">{index + 1}</span>
                  <h2 className="text-base font-semibold">{step.title}</h2>
                  <p className="text-sm text-muted-foreground">{step.text}</p>
                </SpotlightCard>
              </li>
            ))}
          </ol>
        </div>
      </HomeMotion>
    </main>
  );
}

/** Semaine d'exemple (illustration) : quelques séances colorées par matière. */
function WeekIllustration() {
  const days = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
  const placed: Record<string, { hue: number; label: string }> = {
    "0-0": { hue: 250, label: "Algo" }, "0-1": { hue: 250, label: "Algo" }, "0-3": { hue: 30, label: "Maths" },
    "1-0": { hue: 150, label: "Réseaux" }, "1-1": { hue: 330, label: "Anglais" }, "1-3": { hue: 200, label: "BDD" },
    "1-4": { hue: 200, label: "BDD" }, "2-1": { hue: 30, label: "Maths" }, "2-2": { hue: 90, label: "Web" },
    "3-0": { hue: 280, label: "Système" }, "3-1": { hue: 280, label: "Système" }, "3-3": { hue: 150, label: "Réseaux" },
    "4-0": { hue: 90, label: "Web" }, "4-2": { hue: 330, label: "Anglais" }, "5-0": { hue: 30, label: "Maths" },
  };
  return (
    <div aria-hidden="true" className="mx-auto hidden w-full max-w-md rounded-xl border bg-card p-4 shadow-[0_18px_40px_rgb(16_22_42/0.12)] sm:block">
      <div className="grid grid-cols-6 gap-1.5 text-center text-[11px] font-semibold text-muted-foreground">
        {days.map((d) => (
          <span key={d}>{d}</span>
        ))}
        {[0, 1, 2, 3, 4].flatMap((slot) =>
          days.map((_, day) => {
            const s = placed[`${day}-${slot}`];
            const exists = day < 5 || slot < 3;
            return (
              <span key={`${day}-${slot}`} className={cn("h-11 rounded-md", exists ? "bg-muted/60" : "opacity-0")}>
                {s && (
                  <span
                    className="hero-session session flex h-full items-center justify-center rounded-md px-1 text-[10px] font-semibold"
                    style={{ "--hue": s.hue } as CSSProperties}
                  >
                    {s.label}
                  </span>
                )}
              </span>
            );
          }),
        )}
      </div>
    </div>
  );
}

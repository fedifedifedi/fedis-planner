import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Apparition discrète (pages de travail) : fondu et légère montée des enfants directs, en CSS (classe .reveal dans
 * globals.css). Pas de GSAP ici : un `gsap.from` masque le contenu dès le départ et le laisse invisible si les
 * images ne défilent pas (onglet en arrière-plan, navigateur headless). Les séquences orchestrées (étapes de
 * l'agent, lettre) restent en GSAP.
 */
export function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("reveal", className)}>{children}</div>;
}

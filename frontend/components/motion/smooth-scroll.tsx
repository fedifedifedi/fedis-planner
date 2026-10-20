"use client";

import Lenis from "lenis";
import { useEffect } from "react";
import { useReducedMotion } from "@/components/motion/use-reduced-motion";

/**
 * Défilement doux (Lenis) sur toute l'application, coupé si le système demande moins d'animations.
 * Les zones qui défilent elles-mêmes (textarea, aperçu de la lettre, listes) portent data-lenis-prevent.
 */
export function SmoothScroll() {
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const lenis = new Lenis({ autoRaf: true, lerp: 0.12 });
    return () => lenis.destroy();
  }, [reduced]);

  return null;
}

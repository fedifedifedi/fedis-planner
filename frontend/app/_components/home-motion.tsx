"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { useRef, type ReactNode } from "react";
import { useReducedMotion } from "@/components/motion/use-reduced-motion";

gsap.registerPlugin(useGSAP, SplitText, ScrollTrigger);

/** Trace un trait SVG (arc, anneau) du début à la fin. */
function draw(element: SVGGeometryElement, vars: gsap.TweenVars) {
  const length = element.getTotalLength();
  return gsap.fromTo(element, { strokeDasharray: length, strokeDashoffset: length }, { strokeDashoffset: 0, ...vars });
}

/**
 * Copié de LMAgent (app/_components/home-motion.tsx), avec la cascade de l'illustration en plus.
 * Animations marquées de l'accueil (seulement ici) : logo tracé, titre révélé mot à mot derrière un masque, filet,
 * étapes au défilement. La page est complète au repos : une minuterie termine l'animation si les images ne défilent
 * pas, et rien ne bouge quand le système demande moins d'animations.
 */
export function HomeMotion({ children }: { children: ReactNode }) {
  const scope = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useGSAP(
    () => {
      const root = scope.current;
      if (reduced || !root) return;
      const timeline = gsap.timeline({ defaults: { ease: "power3.out" } });
      const arc = root.querySelector<SVGGeometryElement>(".logo-arc");
      const ring = root.querySelector<SVGGeometryElement>(".logo-ring");
      if (arc) timeline.add(draw(arc, { duration: 0.9, ease: "power2.inOut" }), 0);
      if (ring) timeline.add(draw(ring, { duration: 1.1, ease: "power2.inOut" }), 0.1);
      timeline.from(root.querySelectorAll(".logo-glow"), { opacity: 0, duration: 0.8 }, 0.4);

      const title = root.querySelector<HTMLElement>(".home-title");
      let split: SplitText | undefined;
      if (title) {
        split = new SplitText(title, { type: "lines,words", mask: "lines" });
        timeline.from(split.words, { yPercent: 110, duration: 0.8, stagger: 0.045 }, 0.35);
      }
      timeline.fromTo(root.querySelectorAll(".home-rule"), { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: "power2.inOut" }, "-=0.45");
      timeline.from(root.querySelectorAll(".home-lede, .home-actions"), { opacity: 0, y: 10, duration: 0.5, stagger: 0.1 }, "-=0.35");
      // Fedi's Planner : les séances de l'illustration se placent en cascade, comme après une résolution.
      // fromTo with an explicit end state: a plain .from() read its end opacity as 0 (measured in headless Edge).
      timeline.fromTo(
        root.querySelectorAll(".hero-session"),
        { opacity: 0, scale: 0.6 },
        { opacity: 1, scale: 1, duration: 0.45, ease: "back.out(1.8)", stagger: { each: 0.04, from: "random" } },
        0.5,
      );

      const steps = root.querySelectorAll<HTMLElement>(".home-step");
      const stepTween = gsap.from(steps, {
        opacity: 0,
        y: 18,
        duration: 0.6,
        stagger: 0.12,
        scrollTrigger: { trigger: root.querySelector(".home-steps"), start: "top 88%", once: true },
      });

      // Filet de sécurité : si l'animation ne progresse pas (onglet en arrière-plan), on affiche l'état final.
      const safety = window.setTimeout(() => {
        timeline.progress(1);
        stepTween.progress(1);
      }, (timeline.duration() + 2) * 1000);

      return () => {
        window.clearTimeout(safety);
        split?.revert();
      };
    },
    { scope, dependencies: [reduced] },
  );

  return <div ref={scope}>{children}</div>;
}

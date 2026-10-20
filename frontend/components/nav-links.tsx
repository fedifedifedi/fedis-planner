"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

// Copié de LMAgent (components/nav-links.tsx), liens adaptés.
const LINKS = [
  { href: "/", label: "Accueil", match: (p: string) => p === "/" },
  { href: "/planner", label: "Planificateur", match: (p: string) => p.startsWith("/planner") },
];

/** Navigation de l'en-tête avec la section active mise en évidence. */
export function NavLinks() {
  const pathname = usePathname();
  return (
    <>
      {LINKS.map((link) => {
        const active = link.match(pathname);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cn("rounded-md px-2.5 py-1.5 font-medium hover:bg-accent", active && "bg-accent")}
          >
            {link.label}
          </Link>
        );
      })}
    </>
  );
}

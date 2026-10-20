import type { Metadata } from "next";
import { Instrument_Serif, Public_Sans } from "next/font/google";
import Link from "next/link";
import type { ReactNode } from "react";
import { Suspense } from "react";
import { Logo } from "@/components/logo";
import { SmoothScroll } from "@/components/motion/smooth-scroll";
import { NavLinks } from "@/components/nav-links";
import { ThemeToggle } from "@/components/theme";
import { themeScript } from "@/lib/theme-script";
import "./globals.css";

// Mise en page copiée de LMAgent (app/layout.tsx) : mêmes polices, script de thème sans flash, en-tête collant flouté.
const publicSans = Public_Sans({ variable: "--font-public-sans", subsets: ["latin"] });
const instrumentSerif = Instrument_Serif({ variable: "--font-instrument-serif", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });

export const metadata: Metadata = {
  title: "Fedi's Planner",
  applicationName: "Fedi's Planner",
  description: "Générateur d'emplois du temps par optimisation sous contraintes (OR-Tools CP-SAT).",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="fr"
      // La classe .dark est posée par themeScript avant l'hydratation.
      suppressHydrationWarning
      className={`${publicSans.variable} ${instrumentSerif.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <SmoothScroll />
        <header className="no-print sticky top-0 z-20 border-b bg-background/85 backdrop-blur print:hidden">
          <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5">
            <Link href="/" aria-label="Fedi's Planner, accueil">
              <Logo className="text-lg" markClassName="size-9" />
            </Link>
            <nav className="flex flex-wrap items-center gap-1 text-sm">
              <Suspense>
                <NavLinks />
              </Suspense>
              <span className="ml-2">
                <ThemeToggle />
              </span>
            </nav>
          </div>
        </header>
        <div className="flex flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}

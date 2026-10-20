import { cn } from "@/lib/utils";

/**
 * Logo Fedi's Planner : une page de calendrier (anneau tracé à l'accueil) dont une case est cochée par le sceau.
 * Même construction que le logo de LMAgent (marque + mot-symbole, classes .logo-ring / .logo-glow pour l'animation).
 */
export function LogoMark({ className, compact = false }: { className?: string; compact?: boolean }) {
  const cells = [0, 1, 2, 3].flatMap((row) => [0, 1, 2, 3].map((col) => ({ row, col })));
  return (
    <svg viewBox="0 0 120 120" className={cn("shrink-0", className)} aria-hidden="true">
      {!compact && <circle className="logo-glow" cx="60" cy="62" r="46" fill="var(--ring)" opacity="0.14" />}
      <rect
        className="logo-ring"
        x="18"
        y="22"
        width="84"
        height="80"
        rx="12"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
      />
      <path d="M18 44H102" stroke="currentColor" strokeWidth="5" />
      <path d="M40 14V30M80 14V30" stroke="currentColor" strokeWidth="5" strokeLinecap="round" />
      {cells.map(({ row, col }) => (
        <rect
          key={`${row}-${col}`}
          x={28 + col * 17}
          y={52 + row * 12}
          width="13"
          height="8"
          rx="2"
          fill={row === 2 && col === 1 ? "var(--seal)" : "currentColor"}
          opacity={row === 2 && col === 1 ? 1 : 0.28}
        />
      ))}
    </svg>
  );
}

export const APP_NAME = "Fedi's Planner";

function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-sans font-extrabold tracking-tight", className)} translate="no">
      {APP_NAME}
    </span>
  );
}

/** Marque au-dessus, nom en dessous (accueil). */
export function LogoStacked({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex flex-col items-start gap-3", className)}>
      <LogoMark className="size-28" />
      <Wordmark className="text-3xl" />
    </span>
  );
}

/** Logo en ligne : marque + nom (en-tête). */
export function Logo({ className, markClassName }: { className?: string; markClassName?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark className={cn("size-9", markClassName)} compact />
      <Wordmark />
    </span>
  );
}

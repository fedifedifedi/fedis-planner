"use client";

import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

/** Carte dont le halo suit le curseur (classe .spotlight dans globals.css). */
export function SpotlightCard({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      {...props}
      className={cn("spotlight", className)}
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        event.currentTarget.style.setProperty("--spot-x", `${event.clientX - rect.left}px`);
        event.currentTarget.style.setProperty("--spot-y", `${event.clientY - rect.top}px`);
      }}
    />
  );
}

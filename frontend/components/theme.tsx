"use client";

import { useEffect, useSyncExternalStore } from "react";
import { THEME_STORAGE_KEY as STORAGE_KEY } from "@/lib/theme-script";

export type ThemeChoice = "system" | "light" | "dark";

const listeners = new Set<() => void>();

function readChoice(): ThemeChoice {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function apply(choice: ThemeChoice) {
  const dark = choice === "dark" || (choice === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function select(next: ThemeChoice) {
  try {
    if (next === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Stockage indisponible (navigation privée) : le choix vaut pour cette page seulement.
  }
  apply(next);
  listeners.forEach((listener) => listener());
}

const LABELS: Record<ThemeChoice, string> = { system: "Système", light: "Clair", dark: "Sombre" };

export function ThemeToggle() {
  // Côté serveur : « Système » (le script de <head> a déjà posé la bonne classe).
  const choice = useSyncExternalStore(subscribe, readChoice, () => "system" as ThemeChoice);

  // En mode système, suivre les changements du réglage du système sans recharger.
  useEffect(() => {
    if (choice !== "system") return;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  return (
    <div role="group" aria-label="Thème" className="inline-flex overflow-hidden rounded-md border bg-card text-sm">
      {(Object.keys(LABELS) as ThemeChoice[]).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={choice === value}
          onClick={() => select(value)}
          className="px-2.5 py-1 font-medium text-foreground aria-pressed:bg-primary aria-pressed:text-primary-foreground"
        >
          {LABELS[value]}
        </button>
      ))}
    </div>
  );
}

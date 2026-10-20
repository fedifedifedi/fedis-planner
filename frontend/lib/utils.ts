/** Joins class names, skipping falsy values (replaces the `cn` package used in LMAgent: one dependency less). */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ")
}

export const THEME_STORAGE_KEY = "fedis-planner:theme";

/**
 * Script bloquant placé dans <head> : pose .dark avant le premier rendu (pas de flash).
 * Le choix est en localStorage plutôt qu'en cookie : lire un cookie dans le layout rendrait toutes les pages
 * dynamiques avec Cache Components. Module neutre (pas "use client") pour que le layout serveur reçoive la chaîne.
 */
export const themeScript = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");var d=t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}})()`;

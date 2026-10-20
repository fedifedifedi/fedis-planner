# Vidéo de démo (régénération)

Démo scriptée de Fedi's Planner, entièrement automatisée sous Windows : voix off Windows, enregistrement du navigateur
(Edge sans fenêtre piloté par le protocole DevTools, sans Playwright ni puppeteer), sous-titres incrustés, montage ffmpeg.
Rien de ce qui est généré n'est versionné (voix, images, vidéos : voir `.gitignore`).

| Fichier | Rôle |
|---|---|
| `script.json` | texte de la voix off, une entrée par séquence (s1 … s7) |
| `tts.ps1` | un WAV par séquence avec une voix Windows OneCore (Julie par défaut ; Hortense et Paul disponibles) |
| `record.mjs` | scénario filmé : intro → accueil → grande école → résolution → glouton vs CP-SAT → prof absent → conflit → export → outro ; la durée de chaque scène suit sa voix off |
| `build.py` | piste audio calée sur les scènes, sous-titres ASS, MP4 H.264 + AAC |

## Prérequis

- **ffmpeg** (avec libass) : par exemple la build « essentials » de gyan.dev, téléchargeable en reprise
  (`curl.exe -L -C - -o ffmpeg.7z <url>`), extraite avec `tar -xf ffmpeg.7z`. Aucune installation système n'est nécessaire.
- Edge ou Chrome, Node 24, le venv Python du backend.
- L'application lancée : `.\dev.ps1` (API sur le port 8000, interface sur le port 3000).

## Régénérer

```powershell
cd scripts\demo
$ffmpeg = "C:\Users\SBS\tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"   # à adapter

# 1. Voix off (audio\s1.wav … s7.wav)
powershell -ExecutionPolicy Bypass -File .\tts.ps1 -Voice Julie

# 2. 16:9 (1920 × 1080)
node record.mjs --size 1920x1080 --out out-1920x1080
..\..\backend\.venv\Scripts\python.exe build.py --ffmpeg $ffmpeg --out-dir out-1920x1080

# 3. 4:5 pour LinkedIn (1080 × 1350) : la page est refilmée dans ce format (mise en page adaptée), pas recadrée
node record.mjs --size 1080x1350 --out out-1080x1350
..\..\backend\.venv\Scripts\python.exe build.py --ffmpeg $ffmpeg --out-dir out-1080x1350
```

Résultat : `out-<largeur>x<hauteur>/fedis-planner-demo-<largeur>x<hauteur>.mp4`. En cas d'échec, `record.mjs` enregistre une
capture `error.png` dans le dossier de sortie.

## Notes

- La carte « Glouton vs CP-SAT » affiche les résultats **mesurés** du benchmark (`backend/bench/results_compare.md`,
  60 s par résolution, 3 graines) : une comparaison en direct sur la grande école ne peut pas aboutir en quelques secondes.
- Pour changer de voix ou de débit : `tts.ps1 -Voice Paul -Rate 1.0`, puis refaire les étapes 2 et 3 (les durées de voix
  pilotent le rythme des scènes).
- Thème clair forcé, faux curseur animé (le mode sans fenêtre n'a pas de pointeur), badge de développement de Next masqué
  si l'interface tourne avec `npm run dev`.

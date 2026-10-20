# Fedi's Planner

Générateur d'emplois du temps par optimisation sous contraintes (Google OR-Tools CP-SAT).
Projet à livrer en 1–2 jours, 100 % gratuit.

## Stack

- **Backend** : Python 3.13 (venv dans `backend/.venv`), OR-Tools CP-SAT, FastAPI + uvicorn, Pydantic v2, pytest (+ httpx pour `TestClient`).
- **Frontend** : Next.js + TypeScript (Node 24) — grille hebdo filtrable groupe / prof / salle, export PDF (impression navigateur, `window.print()` + CSS print, **aucune dépendance**) et `.ics` (généré côté API, écrit à la main, sans librairie).
- **OS** : Windows 11 + PowerShell. Connexion internet **instable**.

## Périmètre

- **Exécution locale uniquement** : pas de déploiement, ni Docker, ni configuration d'hébergement, ni limite de requêtes.
- **Pas de base de données** : instances et solutions en fichiers JSON.
- Seule limite à garder : le **temps de résolution** du solveur, configurable.

## Règles de travail (obligatoires)

1. **Plan avant chaque étape** : présenter le plan détaillé de l'étape et attendre la validation avant de coder.
2. **Un commit par étape**, message en **anglais**, style Conventional Commits (`feat:`, `test:`, `chore:`, `docs:`…).
3. **Paquets publiés depuis au moins 14 jours** (direct *et* transitif) :
   - pip : toujours `--uploaded-prior-to <aujourd'hui - 14 j, ISO 8601 UTC>` ;
   - après chaque installation : `backend\.venv\Scripts\python.exe scripts\check_package_age.py` doit sortir en code 0 ;
   - npm : vérifier la date (`npm view <pkg> time --json`) et figer la version exacte.
   - Puis régénérer le lock : `backend\.venv\Scripts\python.exe -m pip freeze > backend\requirements.lock` (encodage ASCII/UTF-8 sans BOM).
4. **Éviter les gros paquets** : pas de librairie si quelques dizaines de lignes suffisent.
5. **Installations réseau** : `pip install --retries 10 --timeout 60 --only-binary=:all: ...` ; en cas d'erreur SSL en cours de téléchargement, relancer (le cache pip conserve l'acquis).
6. Chaque contrainte / fonctionnalité du solveur a ses tests pytest.

## Priorités

Backend complet (étapes 0 → 8) **avant** l'interface (9 → 11).

| # | Étape |
|---|-------|
| 0 | Setup : git, venv, deps, CLAUDE.md |
| 1 | Modèle de données (Pydantic) + grille configurable |
| 2 | Générateur d'instances (petite / moyenne / grande école, seed) |
| 3 | Solveur CP-SAT : contraintes dures + **mesure de taille/temps** sur les 3 tailles (décomposition créneaux→salles si la grande est trop lente) |
| 4 | Préférences pondérées (trous, créneau tardif, TP consécutifs, journées équilibrées) |
| 5 | Explication des conflits (ensemble minimal : assumptions CP-SAT + minimisation par suppression) |
| 6 | Replanification (prof absent) en minimisant les séances déplacées |
| 7 | Glouton + benchmark (qualité, temps) |
| 8 | API FastAPI |
| 9 | Interface Next.js |
| 10 | Exports PDF / .ics |
| 11 | README, finitions |

### Idées pour plus tard (hors périmètre actuel)

- **Pistes de résolution des conflits** : pour chaque conflit expliqué, proposer une action
  (ex. « libérer le mardi 08:30 pour tel prof », « ajouter un labo de ≥ 16 places »).
- Départ glouton (hint) et limites de temps par taille : à décider après le benchmark (étape 7).
- **Replanification impossible → report à la semaine suivante** : rendre le volume horaire souple
  (séances non placées autorisées, avec une forte pénalité par séance reportée) et lister les reports.

## Domaine

- **Grille configurable** (jours + horaires des créneaux dans la config). Défaut : lundi → samedi matin, séances de 1h30 :
  `08:30-10:00`, `10:10-11:40`, `11:50-13:20`, `14:00-15:30`, `15:40-17:10` (samedi : créneaux du matin seulement).
- **Tardif** = dernier créneau de la journée.
- **Contraintes dures** : pas de double réservation (prof, groupe, salle), capacité et type de salle, volume horaire par cours, disponibilités des profs.
- **Préférences** (poids réglables) : minimiser les trous, éviter les créneaux tardifs, TP consécutifs, journées équilibrées.
- Une **unique fonction de score** (`planner/scoring.py`) pour comparer CP-SAT et glouton.

## Interface (étape 9) : décisions

- **Réutiliser le design de LMAgent** (`C:\Users\SBS\lmagent`) en **copiant** dans `frontend/` (pas de recréation) :
  couleurs + mode sombre, polices, Lenis, `useReducedMotion`, composants d'apparition, style de l'en-tête.
- **Animations** : GSAP (dont le plugin **Flip**), Lenis, composants **React Bits** en version GSAP ou CSS.
  **21st.dev** : inspiration seulement, ou composants **sans motion** dont la licence permet la réutilisation (la vérifier et la citer).
- **Effets prévus** :
  - replanification : séances déplacées qui glissent de l'ancien au nouveau créneau (GSAP Flip) + surlignage ;
  - résolution : apparition des séances en cascade ;
  - conflits : survoler une contrainte du panneau surligne les cours et créneaux concernés dans la grille ;
  - accueil : animations plus marquées.
- **Règles (comme LMAgent)** : pas de WebGL, `prefers-reduced-motion` respecté, **contenu visible même si l'animation ne se lance pas**.

## Rythme de travail (à partir de l'étape 6)

Étapes 6, 7 et 8 enchaînées sans validation intermédiaire : un commit + un court rapport à la fin de chacune ;
s'arrêter seulement en cas de vrai choix ou de problème. Un seul benchmark complet (étape 7).

## Salles : décomposition par seuils de capacité (`rooms="threshold"`, défaut)

Le modèle principal ne décide que des créneaux. Pour chaque créneau, type de salle et seuil k :
`#séances avec ≥ k étudiants ≤ #salles de capacité ≥ k`. Les salles sont attribuées ensuite
(`planner/rooms.py::assign_rooms`, petit CP-SAT qui maximise les blocs de TP consécutifs gardés dans la même salle).

**Exact uniquement sous deux hypothèses** (ensembles de salles compatibles emboîtés → condition de Hall réduite aux seuils) :
- **H1** : un cours n'utilise que des salles de **son type exact** ;
- **H2** : **aucune salle n'a d'indisponibilité propre**.

`rooms.threshold_violations()` les vérifie ; si l'une est violée, le solveur **bascule sur `rooms="full"` avec un `RuntimeWarning`**
(le mode effectif est dans `stats["rooms_mode"]`). Toute évolution du modèle touchant aux salles (salles multi-types,
indisponibilités de salles…) doit mettre à jour cette vérification.
`rooms="full"` (variables `y[c,t,r]`) n'est conservé que pour les tests d'accord et le benchmark.

## Arborescence

```
backend/
  planner/   model, generator, solver, explain, replan, greedy, scoring, export_ics
  api/       FastAPI (main.py)
  bench/     benchmark CP-SAT vs glouton
  tests/
scripts/check_package_age.py   audit de la règle des 14 jours
frontend/                      Next.js (étape 9)
```

## Commandes

```powershell
# Tests
cd backend; .venv\Scripts\python.exe -m pytest

# Audit des dates de paquets
backend\.venv\Scripts\python.exe scripts\check_package_age.py

# Installation reproductible
backend\.venv\Scripts\python.exe -m pip install --retries 10 --timeout 60 --only-binary=:all: -r backend\requirements.lock
```

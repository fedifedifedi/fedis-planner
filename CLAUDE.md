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

## Domaine

- **Grille configurable** (jours + horaires des créneaux dans la config). Défaut : lundi → samedi matin, séances de 1h30 :
  `08:30-10:00`, `10:10-11:40`, `11:50-13:20`, `14:00-15:30`, `15:40-17:10` (samedi : créneaux du matin seulement).
- **Tardif** = dernier créneau de la journée.
- **Contraintes dures** : pas de double réservation (prof, groupe, salle), capacité et type de salle, volume horaire par cours, disponibilités des profs.
- **Préférences** (poids réglables) : minimiser les trous, éviter les créneaux tardifs, TP consécutifs, journées équilibrées.
- Une **unique fonction de score** (`planner/scoring.py`) pour comparer CP-SAT et glouton.

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

# Fedi's Planner

Générateur d'emplois du temps par **optimisation sous contraintes** (Google OR-Tools CP-SAT), avec explication des
conflits, replanification en cas d'imprévu et comparaison avec un algorithme glouton. 100 % gratuit, exécution locale.

- **Backend** : Python 3.13, OR-Tools 9.15 (CP-SAT), FastAPI, pytest (168 tests).
- **Interface** : Next.js 16 + TypeScript, Tailwind 4, GSAP (Flip), Lenis — design repris de LMAgent.

## Fonctionnalités

| | |
|---|---|
| **Contraintes obligatoires** | pas de double réservation (prof, groupe, salle), sous-groupes de TP (un cours du parent et d'un sous-groupe ne se chevauchent jamais), type et capacité de salle, volume horaire, maximum de séances par jour, disponibilités des profs |
| **Préférences pondérées** | trous (étudiants, profs), créneaux tardifs, TP en blocs consécutifs (la pause de midi casse un bloc), journées équilibrées, journée à une seule séance ; poids réglables |
| **Grille configurable** | jours et horaires dans la config ; défaut : lundi → samedi matin, séances d'1h30 (08:30, 10:10, 11:50, 14:00, 15:40), « tardif » = 15:40-17:10 |
| **Générateur d'instances** | petite / moyenne / grande école (promos → groupes → sous-groupes), noms réalistes, profs à temps partiel, graine reproductible, variantes impossibles |
| **Explication des conflits** | vérifications rapides par comptage + **ensemble minimal** de contraintes contradictoires (noyau CP-SAT réduit par suppression, minimalité vérifiée) en français |
| **Replanification** | prof absent : on déplace **le moins de séances possible** (prouvé optimal), puis on optimise la qualité ; les séances déjà passées (`announced_at`) sont figées ; salles conservées |
| **Benchmark** | glouton vs CP-SAT (même fonction de score), départ glouton |
| **Exports** | PDF (impression du navigateur, A4 paysage) et `.ics` (RFC 5545, filtrable, récurrence hebdomadaire) |

## Démarrage (Windows + PowerShell)

```powershell
# Backend (Python 3.13). Connexion instable : retries ; paquets publiés depuis >= 14 jours (voir requirements.lock).
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --retries 10 --timeout 60 --only-binary=:all: -r requirements.lock

# Interface (Node 24)
cd ..\frontend
npm ci

# Lancer les deux (deux fenêtres) puis ouvrir http://localhost:3000
cd ..
.\dev.ps1
```

API documentée sur http://127.0.0.1:8000/docs. Seule limite : le temps de résolution, plafonné par `FEDIS_MAX_TIME_LIMIT`
(120 s par défaut). Pas de base de données : tout passe en JSON (instances d'exemple dans `backend/instances/`).

```powershell
cd backend
.venv\Scripts\python.exe -m pytest                                   # 168 tests
.venv\Scripts\python.exe -m planner.generator --size medium --seed 7 -o instances\m7.json
.venv\Scripts\python.exe -m bench.compare                            # glouton vs CP-SAT (~25 min)
.venv\Scripts\python.exe -m bench.model_size                         # taille du modèle, seuils vs complet
.venv\Scripts\python.exe -m bench.explain_replan                     # temps d'explication et de replanification
```

## Modélisation

- **Variables** : `x[c,t] = 1` si le cours *c* a une séance au créneau *t* (séances interchangeables, aucune variable
  sur un créneau où le prof est indisponible).
- **Salles par seuils de capacité** : au lieu de variables `y[c,t,salle]` (93 % du modèle de la grande école), pour
  chaque créneau, type de salle et seuil *k* : `#séances de ≥ k étudiants ≤ #salles de ≥ k places`. Les ensembles de
  salles compatibles sont **emboîtés**, la **condition de Hall** se réduit donc à ces seuils : la décomposition est
  **exacte** sous deux hypothèses vérifiées à l'exécution (H1 : un cours n'utilise que des salles de son type ; H2 :
  aucune salle n'a d'indisponibilité propre), sinon repli automatique sur le modèle complet avec un avertissement.
  Les salles sont ensuite attribuées par un petit CP-SAT qui garde les blocs de TP dans la même salle (100 % mesuré).
- **Chaînes d'étudiants** : pour chaque sous-groupe, lui + ses ancêtres ; au plus une séance par chaîne et par créneau.
- **Score unique** (`planner/scoring.py`) partagé par CP-SAT, le glouton et la replanification ; testé égal à
  l'objectif de CP-SAT quand l'optimum est prouvé.

## Résultats

Grande école (95 groupes, 102 profs, ~600 séances) — contraintes dures seules :

| Modèle des salles | Variables | Résolution |
|---|---|---|
| complet (`y[c,t,r]`) | 124k – 149k | 8,6 – 13,4 s |
| **seuils de capacité** | **9,9k – 10,5k** | **1,5 – 1,7 s** (+ < 1 s d'attribution des salles) |

Glouton vs CP-SAT (60 s, 8 threads, poids par défaut, 3 graines par taille) :

| Taille | Glouton | CP-SAT | CP-SAT bat le glouton après |
|---|---|---|---|
| petite | 75 – 99 (≤ 0,02 s) | **12 – 25** | 0,6 – 1,9 s |
| moyenne | 284 – 356 (≤ 0,07 s) | **92 – 128** | 8 – 11 s |
| grande | 753 – 858 (≤ 0,17 s) | **439 – 577** | 28 – 41 s |

Sur des instances serrées (salles occupées à 100 %), le glouton laisse 2 à 9 séances non placées alors que CP-SAT
trouve un emploi du temps complet, ou **prouve** qu'aucun n'existe. Le départ glouton (activé par défaut dans l'API)
donne une première solution plus tôt et évite de faire pire que le glouton avec une limite de temps courte.
Détails : [backend/bench/NOTES.md](backend/bench/NOTES.md) et [results_compare.md](backend/bench/results_compare.md).

**Explication des conflits** : 0,1 – 1,3 s (pénurie de labos, 1 contrainte) et 0,3 – 11 s (deux vacataires
disponibles sur le même unique créneau : exactement 3 contraintes, invisibles à tout comptage).
**Replanification** (prof le plus chargé absent un jour) : minimum de déplacements prouvé en 0,4 – 8 s.

### Écart d'optimalité : une borne faible, pas de mauvaises solutions

L'optimum n'est pas prouvé, même sur la petite école en 10 minutes (meilleure solution 10, borne 0). Le score est dominé
par l'équilibre des journées (max − min de la charge quotidienne), dont le minimum tient à des arguments entiers
(17 séances sur 5 jours ⇒ au moins un jour à 4 et un à 3) que la relaxation linéaire ne voit pas. Une coupe
`max − min ≥ ⌈L/5⌉ − ⌊L/5⌋` a été essayée puis retirée : la charge du lundi au vendredi *L* varie avec les séances du
samedi, si bien qu'une répartition rend presque toujours *L* divisible par 5. L'écart (40 à 100 %) mesure donc surtout la
faiblesse de la borne : les solutions n'ont aucune violation, presque aucun trou, et tous les blocs de TP gardent leur salle.

## Interface

Grille de la semaine filtrable par groupe (avec ses ancêtres et sous-groupes), prof ou salle ; une couleur par matière.

- **Résolution** : apparition des séances en cascade (CSS).
- **Replanification** : les séances déplacées glissent de l'ancien au nouveau créneau (GSAP Flip) et restent surlignées.
- **Conflits** : survoler une contrainte surligne les cours et créneaux concernés (créneaux interdits hachurés).
- **Accueil** : animations marquées (logo tracé, titre révélé mot à mot, cascade de l'illustration).

Règles (comme LMAgent) : pas de WebGL, `prefers-reduced-motion` respecté, contenu visible même si une animation ne se
lance pas (minuteries de sécurité, cascade en CSS plutôt qu'en `gsap.from`). Thème clair / sombre / système.

## Structure

```
backend/
  planner/   model, generator, solver, rooms, scoring, explain, replan, greedy, validate, export_ics
  api/       FastAPI (main.py)
  bench/     model_size, objective, compare, explain_replan + NOTES.md
  tests/
frontend/    Next.js (app/, components/ copiés de LMAgent, lib/)
scripts/     audits de la règle des 14 jours (pip et npm)
```

## Pistes

- Proposer une piste de résolution pour chaque conflit (« libérer tel créneau pour tel prof »).
- Replanification impossible : reporter des séances à la semaine suivante (volume horaire souple, forte pénalité).

# Notes de benchmark (à reprendre dans le README)

## Écart d'optimalité : la borne de CP-SAT est faible

Mesures (poids par défaut, `random_seed=0`) :

| Instance | Limite | Threads | Meilleure solution | Borne | Statut |
|---|---|---|---|---|---|
| small-s1 | 60 s | 8 | 14 – 20 (selon l'exécution) | 2 | FEASIBLE |
| small-s1 | 600 s | 4 | **10** (late 1, imbalance 4, single_session_day 2) | **0** | FEASIBLE |

- **L'optimum n'est pas prouvé**, même sur la petite école et en 10 minutes.
- Le temps supplémentaire améliore nettement la solution (14–20 → 10), mais pas la borne.
- Avec 4 threads la borne retombe à 0 : la portfolio de CP-SAT compte moins de workers
  dédiés à la borne inférieure (LP, core-based) qu'avec 8.

**Pourquoi la borne est faible.** Le score est dominé par le déséquilibre des journées
(max − min de la charge quotidienne du lundi au vendredi, par chaîne d'étudiants). Le minimum
réel dépend d'arguments entiers (ex. 17 séances sur 5 jours ⇒ au moins une journée à 4 et une à 3),
que la relaxation linéaire ne voit pas. Une coupe explicite `max − min ≥ ceil(L/5) − floor(L/5)` a été
essayée puis retirée : la charge du lundi au vendredi L varie avec le nombre de séances placées
le samedi (0 à 3), si bien qu'une répartition rend presque toujours L divisible par 5 et la coupe
ne borne rien. Le compromis tardif / déséquilibre / samedi reste donc non borné.

**Lecture de l'écart.** Un écart de 40 à 100 % mesure surtout la faiblesse de la borne, pas la
qualité des solutions : celles-ci n'ont aucune violation, presque aucun trou, et 100 % des blocs
de TP gardent leur salle.

## Glouton vs CP-SAT (benchmark unique de l'étape 7)

Commande : `python -m bench.compare` — 8 threads, `random_seed=0`, 60 s par résolution, poids par défaut.
Tableau complet : [results_compare.md](results_compare.md).

| Taille (3 graines, occupation 75 %) | Glouton : score / temps | CP-SAT : score | CP-SAT bat le glouton après | CP-SAT + départ glouton : score |
|---|---|---|---|---|
| petite | 75 – 99 / ≤ 0,02 s | **12 – 25** | 0,6 – 1,9 s | 15 – 24 |
| moyenne | 284 – 356 / ≤ 0,07 s | 92 – 128 | 8 – 11 s | **85 – 116** |
| grande | 753 – 858 / ≤ 0,17 s | 439 – 577 | 28 – 41 s | **439 – 482** |

Instances serrées (occupation des salles 100 %, graine 1) :

| Instance | Glouton | CP-SAT |
|---|---|---|
| petite | 2 séances non placées | **INFEASIBLE prouvé** : aucun emploi du temps n'existe (le glouton ne peut pas le savoir) |
| moyenne | 2 séances non placées | emploi du temps complet (score 191) |
| grande | 9 séances non placées | emploi du temps complet (score 784) |

Lecture :
- Le glouton est 100 à 1000 fois plus rapide mais 3 à 6 fois moins bon, et il échoue (séances non placées)
  dès que les salles sont pleines, même quand une solution existe.
- **Départ glouton** : première solution plus tôt partout (moyenne 2–4 s au lieu de 4,5–5 s ; grande 5–15 s
  au lieu de 12–16 s). Score final sur les 8 instances moyennes/grandes : meilleur sur 5, égal sur 1, un peu
  moins bon sur les 2 serrées (200 vs 191, 792 vs 784) ; sur la petite école, mitigé (15–24 vs 12–25).
  Écarts de quelques % du même ordre que le bruit d'une exécution multi-thread. L'intérêt principal : CP-SAT
  part d'une solution complète, donc en pratique jamais pire que le glouton même avec une limite de temps
  courte (à froid, la grande école ne bat le glouton qu'après 28–41 s).
- Décision : départ glouton activé par défaut dans l'API (`warm_start=true`, coût < 0,2 s).
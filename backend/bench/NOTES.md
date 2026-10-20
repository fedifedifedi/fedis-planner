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

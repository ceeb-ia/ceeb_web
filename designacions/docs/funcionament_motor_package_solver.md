# Funcionament Del Nou Motor De Designacions `package_solver`

Data de referencia: 2026-04-27

Aquest document descriu el funcionament actual del motor nou de designacions activat amb:

```python
assignment_engine = "package_solver"
```

El motor legacy continua sent el comportament per defecte si no s'activa aquest flag.

L'objectiu del nou motor es deixar de pensar nomes en "subgrups" i passar a treballar amb "paquets" i "rutes candidates": unitats assignables que poden ser un subgrup original, un fragment d'un subgrup o una ruta que uneix diversos fragments compatibles.

## 0. Explicacio Narrativa Del Proces

El nou motor intenta respondre una pregunta una mica diferent de la que responia el legacy.

El legacy partia d'uns subgrups, mirava quin tutor encaixava millor amb cada subgrup i despres intentava arreglar el que quedava pendent. Aixo funciona be quan els subgrups ja son bones unitats d'assignacio. Pero quan hi ha pocs tutors, pocs vehicles, clusters dispersos o partits de nivells molt diferents dins el mateix run, el subgrup inicial pot ser massa rigid. En aquests casos, el problema real no es nomes "quin tutor assigno a aquest subgrup", sino "quina unitat assignable hauria d'existir perque un tutor la pugui cobrir be".

Per aixo el `package_solver` fa un pas intermedi. Primer deixa que el motor actual generi els subgrups base, perque aquesta logica ja sap agrupar partits propers i temporalment raonables. Pero no es casa amb aquests subgrups. Els tracta com una primera proposta. A partir d'aqui, el motor pregunta: aquest subgrup s'hauria d'assignar sencer? Es millor partir-lo? Es pot unir amb un altre fragment per crear una ruta que aprofiti millor un tutor amb vehicle? Hi ha algun partit important dins el subgrup que obliga a reservar un tutor millor?

La idea central es que cada possible unitat assignable es converteix en un `PackageCandidate`. Un paquet pot ser un subgrup original, un sol partit, un tall contigu del subgrup o una ruta que fusiona dos paquets. El motor no assigna encara. Primer construeix el paisatge de possibilitats.

Un cop te aquest paisatge, cada paquet es mira des de tres angles.

Primer, l'angle esportiu. Quin nivell demana aquest paquet? Si dins el paquet hi ha un `SENIOR`, tota la ruta es considera com a minim `SENIOR`. Aixo evita que un partit dificil quedi amagat dins una ruta aparentment facil. Amb aquesta demanda de nivell, el motor classifica cada tutor com a `ideal`, `acceptable`, `exceptional`, `forbidden` o `unscorable`. Aquesta capa es la que ha de manar. Una ruta pot ser molt bona geograficament, pero si nomes la podria pitar un tutor C i conte un `SENIOR`, no es una bona ruta: es una ruta esportivament invalida.

Segon, l'angle logistic. El paquet encaixa en la disponibilitat del tutor? Requereix vehicle? Canvia de cluster? Passa per outliers o seus sense cluster fiable? Aquestes condicions decideixen si un tutor pot cobrir materialment aquella ruta. Si la ruta creua clusters, no n'hi ha prou amb tenir bon nivell: cal vehicle. Si la disponibilitat no cobreix tot el tram, el candidat cau.

Tercer, l'angle de qualitat fina. Si dos tutors poden cobrir el mateix paquet, quin es millor? Aqui entren la classificacio dels equips, la pressio horaria, els warnings, l'estalvi o despesa de vehicle i el cost global. Un partit `1 vs 2` no bloqueja automaticament tutors, pero fa que el motor tendeixi a posar-hi un tutor mes fort si pot. Una ruta en hora de molta pressio pot rebre un petit premi si ajuda a cobrir partits que probablement quedarien penjats. Un tutor amb vehicle en un paquet facil pot rebre penalitzacio si el sistema detecta que cal reservar vehicles per rutes realment dificils.

Despres de construir i puntuar totes les combinacions `tutor + paquet`, entra el solver. El solver no pensa partit a partit, sino en combinacions compatibles. Ha de seleccionar un conjunt d'assignacions on cap partit surti dues vegades i cap tutor rebi mes d'un paquet el mateix dia. El seu objectiu no es nomes baixar cost. Primer intenta cobrir el maxim valor de partit possible, despres cobrir el maxim nombre de partits, despres evitar assignacions `exceptional`, i finalment minimitzar costos.

Aixo vol dir que el motor pot acceptar un cas `exceptional`, per exemple un `SENIOR` amb un B, si realment no hi ha alternativa millor i permet mantenir cobertura. Pero no hauria d'acceptar un cas `forbidden`, com un `SENIOR` amb C o D. Si a la pantalla apareix una assignacio aixi, cal sospitar que el paquet no estava portant correctament la demanda `SENIOR`, o que el run s'ha executat amb codi antic.

El resultat final es una assignacio mes explicable. No nomes diu "aquest tutor pita aquest partit", sino que el resum del run pot indicar quants candidats han estat descartats per nivell, quantes assignacions han estat `ideal`, quantes `exceptional`, quantes rutes candidates s'han generat i quants partits han quedat pendents. Aquesta informacio es clau per replantejar el model: si queden molts pendents per nivell, potser falten tutors de nivell alt; si queden pendents per vehicle, potser cal revisar clusters o permetre rutes diferents; si hi ha massa `exceptional`, potser el sistema esta forçant cobertura per sobre de qualitat esportiva.

## 1. Visio General Del Flux

El flux general es:

```text
1. Llegir excels i aplicar filtres de run
2. Geocodificar i clusteritzar seus
3. Consultar classificacions i escriure posicions dels equips
4. Crear subgrups base amb la logica existent
5. Convertir subgrups base a BaseSubgroup
6. Construir TutorCandidate
7. Calcular pressions del run
8. Generar PackageCandidate
9. Puntuar combinacions tutor + paquet
10. Resoldre globalment amb solver
11. Persistir assignacions, pendents i diagnostics
```

El punt de bifurcacio respecte el legacy es dins `designacions/main_fixed.py`.

Quan `assignment_engine == "package_solver"`, el motor fa:

```python
base_subgroups = build_base_subgroups_from_rows(final_subgrups)
optimization_tutors = _build_optimization_tutors(df_dispos_modalitat)
pressure_result = build_pressure_summary(base_subgroups, optimization_tutors, config)
packages = generate_package_candidates(base_subgroups, optimization_tutors, pressure_result, config)
assignment_candidates = build_assignment_candidates(packages, optimization_tutors, pressure_result, config)
solver_result = solve_assignment_candidates(assignment_candidates, packages, optimization_tutors, config)
```

I despres transforma els paquets seleccionats en assignacions finals.

## 2. Entrada I Preparacio De Dades

### Fitxers D'Entrada

El motor parteix de dos excels:

- Excel de disponibilitats de tutors.
- Excel de partits.

Abans d'arribar al motor:

- Es detecta quin fitxer es de partits i quin es de disponibilitats.
- Es filtren modalitats si l'usuari les ha seleccionat.
- Es filtren dates si `date_from` o `date_to` estan definits.
- Es guarda el run a `DesignationRun`.
- Es poden crear previews de cluster abans d'executar el run.

### Identificadors Interns

El motor crea IDs interns:

- `df_dispos["ID"]` per tutors.
- `df_partits["ID"]` per partits.

Per tutors, si no hi ha ID estable, el motor pot caure al codi de tutor:

```python
tutor_id = row.get("ID")
if pd.isna(tutor_id) or str(tutor_id).strip() == "":
    tutor_id = row.get("Codi Tutor de Joc", "")
```

Aixo es important per reconnectar el candidat seleccionat pel solver amb la fila original de disponibilitat.

## 3. Classificacions

El motor consulta classificacions CEEB abans de formar subgrups assignables.

Per cada grup:

1. Detecta categoria i subcategoria.
2. Busca `Id Categoria` al mapa de modalitats.
3. Crida `fetch_ceeb_classification_async(...)`.
4. Parseja XML amb `parse_ceeb_xml(...)`.
5. Converteix a dataframe amb `xml_to_dataframe(...)`.
6. Busca la posicio de l'equip local i visitant.
7. Escriu:

```text
Posicio Equip Local
Posicio Equip Visitant
```

Aquestes posicions s'usen per dues coses:

- Informar la pestanya de designats/export.
- Calcular `classification_importance` al motor nou.

### Importancia De Classificacio

El modul `designacions/optimization/classification.py` calcula:

```python
match_classification_importance(pos_local, pos_visitant)
```

La idea:

- Un `1 vs 2` es molt important.
- Un partit amb algun equip top 3 rep bonus.
- Un partit amb equips propers a classificacio rep bonus.
- Sense classificacio, la importancia es `0.0`.

Formula actual aproximada:

```text
table_score = 1 - ((pos_local + pos_visitant - 3) / 17)
top_bonus = 0.25 si algun equip es top 3
closeness_bonus = 0.2 si distancia <= 1, 0.1 si distancia <= 2
importance = clamp(table_score + top_bonus + closeness_bonus, 0, 1)
```

Exemples:

```text
1 vs 2  -> importancia molt alta, propera a 1.0
5 vs 3  -> importancia alta/moderada
10 vs 12 -> importancia baixa
posicions desconegudes -> 0.0
```

## 4. Creacio De Subgrups Base

Els subgrups base encara venen de la logica existent del motor.

Es creen amb `_build_daily_subgroups_with_stats(...)` a `main_fixed.py`.

Criteris generals:

- Agrupar partits per dia/modalitat.
- Respectar proximitat temporal.
- Respectar pista/cluster.
- Aplicar gaps:
  - `gap_same_pitch_min`
  - `gap_diff_pitch_min`
  - `gap_diff_cluster_min`
- Respectar `max_partits_subgrup`.

El resultat son llistes de partits:

```text
final_subgrups = [
  [partit_1, partit_2],
  [partit_3],
  ...
]
```

El legacy assignava directament aquests subgrups via Hungarian i despres feia repesca.

El nou motor els converteix a `BaseSubgroup`.

## 5. `BaseSubgroup`

El modul `designacions/optimization/base_subgroups.py` converteix cada subgrup base en una estructura pura:

```python
BaseSubgroup(
    id,
    match_ids,
    date,
    modality,
    start_dt,
    end_dt,
    venues,
    cluster_ids,
    cluster_statuses,
    match_count,
    level_demand,
    classification_importance,
    weighted_coverage_value,
    rows,
)
```

### `level_demand`

`level_demand` representa la categoria mes exigent del subgrup.

Ara es calcula amb ordre esportiu real, no amb `min()` de strings:

```python
hardest_match_level(...)
```

Ordre de categories:

```text
SENIOR
JUNIOR
JUVENIL
CADET
INFANTIL
PREINFANTIL
ALEVI
BENJAMI
PREBENJAMI
MENUT
...
```

Si un subgrup conte:

```text
SENIOR + BENJAMI
```

el `level_demand` del subgrup es:

```text
SENIOR
```

Aixo replica conceptualment el legacy, on `Categoria` es convertia a `CategoricalDtype` ordenat i `min()` retornava la categoria mes exigent.

### `classification_importance`

Per un subgrup amb diversos partits:

```python
classification_importance = max(importancia_de_cada_partit)
```

Es fa servir `max` perque un paquet amb un partit molt important no quedi diluit per altres partits normals.

### `weighted_coverage_value`

Cada paquet te un valor de cobertura ponderada:

```python
weighted_coverage_value = match_count + classification_importance * 0.4
```

Per tant:

```text
partit normal -> aproximadament 1.0
partit molt important -> fins aproximadament 1.4
subgrup de 2 partits amb un 1vs2 -> fins aproximadament 2.4
```

Aixo permet al solver diferenciar entre cobrir un partit normal i cobrir un partit esportivament mes sensible.

## 6. Tutors: `TutorCandidate`

Cada disponibilitat es converteix en:

```python
TutorCandidate(
    id,
    code,
    modality,
    level,
    transport,
    has_vehicle,
    availability_by_date,
)
```

Exemple:

```python
TutorCandidate(
    id="8352 VLY",
    code="8352 VLY",
    modality="VOLEIBOL",
    level="NIVELLD1",
    transport="Bus",
    has_vehicle=False,
    availability_by_date={
        "2026-04-24": [{"start": "17:00", "end": "22:00"}]
    },
)
```

La disponibilitat del nou motor es comprova per paquet complet:

```text
hora_inici_tutor <= start_dt_paquet
end_dt_paquet <= hora_fi_tutor
```

Nota: cal vigilar si es vol aplicar el mateix buffer final que el legacy (`availability_end_buffer_min`). Actualment el model nou comprova finestra, pero aquesta part es una zona a revisar si es vol equivalencia estricta.

## 7. Pressions

El modul `designacions/optimization/pressure.py` calcula pressions per orientar generacio i scoring.

Sortides principals:

```text
pressure_by_hour
vehicle_pressure_by_hour
level_pressure_by_hour
pressure_by_cluster
pressure_summary
```

Aquestes pressions no assignen directament. Serveixen per:

- prioritzar rutes candidates;
- ajustar `pressure_relief_score`;
- penalitzar o reservar vehicles;
- diagnosticar punts tensionats.

Exemple:

```text
2026-04-24|voleibol|18:00
max_general_pressure = 1.2453
max_vehicle_pressure = 0.8
```

Aixo indica que aquella franja te mes demanda relativa que altres.

## 8. Generacio De Paquets

El modul clau es:

```python
designacions/optimization/package_generation.py
```

Genera diferents tipus de `PackageCandidate`.

### 8.1 Paquet `base`

Cada `BaseSubgroup` genera un paquet:

```text
kind = base
match_ids = tots els partits del subgrup
```

Exemple:

```text
Subgrup base:
  M1 18:00 SENIOR pista A
  M2 19:00 BENJAMI pista A

PackageCandidate:
  kind = base
  match_ids = [M1, M2]
  level_demand = SENIOR
```

### 8.2 Paquets `single_match`

Si un subgrup te mes d'un partit, el motor genera variants d'un sol partit:

```text
M1 sol
M2 sol
```

Aixo permet que un subgrup massa dificil es pugui partir.

Important: el `level_demand` del `single_match` es recalcula segons el partit concret.

Exemple:

```text
Subgrup base:
  M1 SENIOR
  M2 BENJAMI

single M1:
  level_demand = SENIOR

single M2:
  level_demand = BENJAMI
```

Aquest punt es important per evitar que un partit `SENIOR` acabi amb una demanda de nivell incorrecta heretada del subgrup.

### 8.3 Paquets `contiguous_split`

Tam be genera talls contigus:

```text
[M1, M2]
[M2, M3]
...
```

No genera totes les particions possibles; limita combinatoria amb:

```text
max_split_subgroup_size
max_split_variants_per_subgroup
```

Per defecte, nomes divideix subgrups de mida controlada.

El `level_demand` del tall tambe es recalcula:

```text
si el tall conte SENIOR -> level_demand = SENIOR
si no, agafa la categoria mes exigent del tall
```

## 9. Generacio De Rutes Candidates

Despres de generar `base`, `single_match` i `contiguous_split`, el motor intenta fusionar paquets en rutes.

Una ruta es un paquet que uneix dos paquets compatibles:

```text
route:pkgA+pkgB
```

Pot ser:

```text
merged_route
split_merged_route
```

### 9.1 Criteris Temporals I Modalitat

Per fusionar dos paquets cal:

```text
mateix dia
mateixa modalitat
ordre temporal valid
cap partit duplicat
gap suficient entre final del primer i inici del segon
```

La funcio principal es:

```python
_can_route(left, right, config)
```

El gap requerit es:

```text
mateixa pista -> gap_same_pitch_min
diferent pista o mateix cluster -> gap_diff_pitch_min
canvi de cluster -> gap_diff_cluster_min
```

### 9.2 Vehicle

Si la ruta conté mes d'un cluster real:

```python
requires_vehicle = True
```

Si algun cluster es poc fiable:

```python
vehicle_preferred = True
```

Casos de cluster poc fiable:

```text
outlier
missing_geocode
pending
not_found
cluster buit
```

Warnings possibles:

```text
outlier_mobility_warning
missing_cluster_mobility_warning
cross_cluster_with_vehicle_warning
```

### 9.3 Nivell De La Ruta

El `level_demand` de la ruta es la categoria mes exigent dels dos components:

```python
level_demand = hardest_match_level([left.level_demand, right.level_demand])
```

Exemple:

```text
Ruta:
  component A: SENIOR
  component B: BENJAMI

level_demand = SENIOR
```

### 9.4 Classificacio De La Ruta

La importancia de classificacio de la ruta es:

```python
classification_importance = max(left.classification_importance, right.classification_importance)
```

Exemple:

```text
component A: partit 1vs2 -> importance 1.0
component B: partit 10vs12 -> importance baixa

ruta importance = 1.0
```

### 9.5 Filtratge Level-Aware De Rutes

Aquest es un dels canvis mes importants del motor actual.

Per cada ruta candidata, es calcula:

```python
level_fit_summary
```

Amb comptadors:

```text
ideal
acceptable
exceptional
forbidden
unscorable
```

Nomes es compten tutors que també compleixen disponibilitat, modalitat i vehicle si cal.

Per defecte, una ruta fusionada es conserva nomes si te com a minim un tutor:

```text
ideal o acceptable
```

Si nomes hi ha tutors `exceptional`, la ruta es descarta, excepte si:

```python
allow_exceptional_routes = True
```

Aixo evita crear rutes boniques horariament pero esportivament dolentes.

### 9.6 Pressupost De Rutes

No es conserven totes les rutes possibles.

Per cada `(date, modality)` es calcula un pressupost segons tutors amb vehicle:

```python
vehicle_capable = tutors amb vehicle i modalitat/data compatibles
budget = max(
    vehicle_capable * route_candidate_factor,
    vehicle_capable + route_candidate_buffer,
    1,
)
```

Valors habituals:

```text
route_candidate_factor = 2
route_candidate_buffer = 3
```

### 9.7 Retencio De Rutes

Les rutes candidates s'ordenen per:

```text
1. nombre de tutors ideal/acceptable
2. weighted_coverage_value
3. classification_importance
4. route_score
```

Aixo vol dir:

- Primer es prioritzen rutes que poden ser pitades be.
- Despres les que cobreixen mes valor esportiu.
- Despres les que inclouen partits classificatoriament importants.
- Finalment les que tenen millor score operatiu.

## 10. Model De Nivell

El model de nivell viu a:

```python
designacions/optimization/levels.py
```

### Escala De Tutors

```text
NIVELLA1
NIVELLB1
NIVELLC1
NIVELLD1
D
```

### Escala De Partits

```text
SENIOR
JUNIOR
JUVENIL
CADET
INFANTIL
PREINFANTIL
ALEVI
BENJAMI
PREBENJAMI
MENUT
...
```

### `level_fit`

Per cada combinacio tutor + paquet:

```python
level_fit(tutor_level, package.level_demand)
```

Retorna:

```text
ideal
acceptable
exceptional
forbidden
unscorable
```

Regles actuals:

```text
SENIOR + A -> ideal
SENIOR + B -> exceptional
SENIOR + C -> forbidden
SENIOR + D -> forbidden
SENIOR + D generic -> forbidden
```

Per altres categories:

```text
gap <= 0 -> ideal
gap == 1 -> acceptable, o exceptional si categoria alta/classificacio alta
gap >= 2 -> forbidden
```

### Diferencia Amb El Legacy

El legacy tractava el nivell com una distancia continua dins el cost.

El nou motor ho tracta com:

```text
1. elegibilitat esportiva
2. cost dins candidats viables
```

Aixo es deliberat per evitar que vehicle, cobertura o pressio compensin una designacio esportivament inacceptable.

## 11. Cost Tutor + Paquet

El modul:

```python
designacions/optimization/package_scoring.py
```

genera totes les parelles:

```text
tutor x paquet
```

Cada parella es un `AssignmentCandidate`.

Cost:

```text
cost =
  level_cost
+ classification_fit_cost
+ mobility_cost
+ vehicle_cost
+ warning_cost
+ base_difficulty_cost
- pressure_relief_reward
```

### 11.1 `level_cost`

Mesura distancia entre nivell del tutor i categoria del paquet.

Pero abans de cost, hi ha `level_fit`:

- `forbidden` -> candidat inviable.
- `exceptional` -> candidat viable pero amb penalitzacio forta.
- `ideal/acceptable` -> candidat normal.

Cost actual:

```python
level_distance_cost(...) * level_distance_weight
```

Valor per defecte:

```text
level_distance_weight = 1000
exceptional_level_penalty = 3000
forbidden_level_penalty = 1000000
```

Exemple `SENIOR`:

```text
A -> ideal, cost baix/0
B -> exceptional, cost + penalitzacio
C/D -> forbidden, inviable
```

### 11.2 `classification_fit_cost`

Penalitza que un partit classificatoriament important caigui a un tutor feble.

Formula:

```python
classification_fit_cost =
    classification_importance
    * normalized_tutor_position
    * classification_fit_weight
```

On:

```text
A -> 0.0
B -> 0.25
C -> 0.5
D -> 0.75
D generic -> 1.0
```

Valor per defecte:

```text
classification_fit_weight = 500
```

Exemple:

```text
partit 1vs2, importance 1.0
A -> 0
B -> 125
C -> 250
D -> 375
```

Aquest cost no ha de permetre C/D en SENIOR, perque aixo ja queda bloquejat per `level_fit`.

### 11.3 `mobility_cost`

Penalitza mobilitat complexa:

```text
requires_vehicle -> +40
cross_cluster warning -> +25
outlier/missing cluster -> +35
altres warnings -> +5
```

Aquest cost refina, no ha de dominar el nivell.

### 11.4 `vehicle_cost`

Penalitza gastar vehicle en paquets facilment assumibles sense vehicle quan hi ha pressio de vehicle.

Casos:

```text
paquet requereix vehicle -> 0
vehicle preferred -> +20
tutor amb vehicle en segment facil i hi ha pressio -> +250
```

Objectiu:

- reservar tutors amb vehicle per rutes que realment el necessiten.

### 11.5 `warning_cost`

Cada warning unic suma:

```text
warning_cost = 15
```

Serveix per ordenar, no per bloquejar.

### 11.6 `base_difficulty_cost`

Ve de la dificultat generica del paquet/ruta:

```text
requires_vehicle -> +2
vehicle_preferred -> +1
warnings * 0.25
```

Actualment pesa poc.

### 11.7 `pressure_relief_reward`

Resta cost quan el paquet alleuja pressio.

```python
pressure_relief_score * pressure_relief_weight
```

Valor habitual:

```text
pressure_relief_weight = 50
```

Serveix per afavorir rutes en punts tensionats, pero no pot superar l'elegibilitat de nivell.

## 12. Viabilitat Del Candidat

Un `AssignmentCandidate` queda inviable si:

```text
modalitat no coincideix
disponibilitat no cobreix el paquet
requereix vehicle i tutor no en te
level_fit == forbidden
unscorable bloquejat per config
```

Reasons habituals:

```text
modality_mismatch
outside_availability_window
vehicle_required
level_forbidden
```

Els candidats inviables reben penalitzacio alta i no entren al solver com a viables.

## 13. Solver

El solver viu a:

```python
designacions/optimization/solver.py
```

Entrada:

```python
solve_assignment_candidates(assignment_candidates, packages, tutors, config)
```

Restriccions fortes:

```text
un partit nomes pot ser assignat una vegada
un tutor nomes pot rebre un paquet per dia
```

### Estrategia

Si hi ha pocs candidats viables:

```text
bounded_exact
```

Llimit:

```text
exact_solver_candidate_limit = 22
```

Si n'hi ha mes:

```text
greedy multi-pass
```

### Objectiu Lexicografic

El solver compara solucions per:

```text
1. weighted_covered_value
2. nombre de partits coberts
3. menys assignacions exceptional
4. menor cost total
5. menys assignacions totals
```

Aixo significa:

- Cobertura ponderada mana.
- Cobertura real tambe mana.
- Pero, a igual cobertura, evita `exceptional`.
- Despres mira cost.

### Greedy Multi-Pass

El greedy prova diverses ordenacions:

```text
1. mes valor de paquet, mes partits, no exceptional, cost baix
2. no exceptional, cost baix, valor alt
3. pressio, valor alt, no exceptional, cost baix
```

Despres es queda la millor solucio segons l'objectiu lexicografic.

## 14. Persistencia I Diagnostics

El motor transforma `selected_assignments` en files d'assignacio.

Per cada paquet seleccionat:

```text
tutor seleccionat
partits del paquet
```

es creen registres equivalents a:

```text
Codi Partit
Tutor Codi
Tutor Nom
Tutor Nivell
Classificacio Equips
...
```

Despres `persist_assignacions_to_db(...)` actualitza:

- `Match`
- `Assignment`
- `Referee`

### Diagnostics Del Nou Motor

`result_summary` inclou:

```text
engine_name
package_solver_summary
candidate_package_count
selected_package_count
```

Dins `package_solver_summary`:

```text
base_subgroup_count
candidate_package_count
assignment_candidate_count
selected_assignment_count
selected_match_count
unassigned_match_count
pressure_summary
solver_objective
rejected_candidates_summary
level_forbidden_candidate_count
level_blocking_counts
selected_by_level_fit
level_exceptional_selected_count
```

Exemple de lectura:

```text
selected_by_level_fit = {
  "ideal": 57,
  "exceptional": 2
}
```

Vol dir:

- 57 paquets assignats amb encaix ideal.
- 2 paquets assignats amb encaix excepcional.
- 0 paquets assignats com forbidden.

Si a la BD apareix un `SENIOR + C/D` pero `selected_by_level_fit` no mostra forbidden, cal sospitar que el `level_demand` del paquet no era `SENIOR`.

Aquest problema ja es va detectar al run 134 i es va corregir recalculant `level_demand` amb `hardest_match_level(...)`.

## 15. Exemples Concrets

### Exemple 1: Partit SENIOR Amb Tutor C

Partit:

```text
Codi: 51097
Categoria: SENIOR
Classificacio: 8 vs 2
```

Tutor:

```text
Nivell: NIVELLC1
```

Amb el model actual:

```python
level_fit("NIVELLC1", "SENIOR") == "forbidden"
```

Resultat esperat:

```text
candidat inviable
blocking_reason = level_forbidden
```

Per tant, aquest tutor no pot rebre aquest paquet si el paquet conserva correctament:

```text
level_demand = SENIOR
```

### Exemple 2: Partit SENIOR Amb Tutor B

Partit:

```text
Categoria: SENIOR
```

Tutor:

```text
Nivell: NIVELLB1
```

Resultat:

```text
level_fit = exceptional
```

No queda bloquejat, pero rep:

```text
level_distance_cost
+ exceptional_level_penalty
```

I el solver intentara evitar-lo si hi ha una solucio amb A que mantingui cobertura.

### Exemple 3: Ruta Amb SENIOR I BENJAMI

Components:

```text
Paquet A:
  M1 SENIOR 20:30

Paquet B:
  M2 BENJAMI 21:30
```

Ruta possible si:

```text
mateix dia
mateixa modalitat
gap suficient
no comparteixen partits
```

Demanda:

```text
level_demand = SENIOR
```

Per tant:

```text
A -> ideal
B -> exceptional
C/D -> forbidden
```

Aixo evita que una ruta mixta amagui un partit SENIOR dins un paquet facil.

### Exemple 4: Ruta Cross-Cluster

Paquet A:

```text
cluster 3
18:00
```

Paquet B:

```text
cluster 8
20:00
```

Si el gap supera `gap_diff_cluster_min`:

```text
requires_vehicle = True
```

La ruta nomes es viable per tutors amb vehicle.

Si a mes conte un `SENIOR`:

```text
requereix vehicle
requereix nivell esportiu suficient
```

Per tant, el candidat ideal seria:

```text
tutor A amb vehicle i disponibilitat completa
```

Si nomes hi ha tutor C amb vehicle:

```text
level_forbidden
```

La ruta no s'hauria d'assignar.

### Exemple 5: Partit 1 vs 2

Partit:

```text
Categoria: CADET
Classificacio: 1 vs 2
```

La categoria pot permetre mes nivells que SENIOR, pero la classificacio puja la importancia:

```text
classification_importance alta
weighted_coverage_value > 1
classification_fit_cost mes alt per tutors fluixos
```

Efecte:

- Si hi ha dos tutors acceptables, el millor nivell queda afavorit.
- Pero si un tutor es `forbidden` per nivell, continua bloquejat.

## 16. Punts Encara Replantejables

### Disponibilitat Amb Buffer

El legacy aplica un buffer al final de disponibilitat:

```text
availability_end_buffer_min
```

El nou motor comprova finestra directa. Si es vol equivalencia estricta, cal incorporar aquest buffer a `package_scoring.py` i `package_generation.py`.

### Repesca Post-Solver

Ara els pendents del solver queden com pendents.

No hi ha encara:

```text
single_match_rescue
relaxed_warning_rescue
augmenting_path_rescue
```

Una repesca futura hauria de respectar:

- no duplicar partits;
- no trencar assignacions locked;
- no permetre `forbidden`;
- relaxar nomes casos `exceptional` de forma auditada.

### Vehicle I Nivell

El model actual posa nivell per davant de vehicle.

Aixo es correcte esportivament, pero pot baixar cobertura si:

```text
els pocs tutors amb vehicle son de nivell baix
els partits dificils son cross-cluster
```

En aquests casos caldria estudiar:

- dividir rutes;
- deixar alguns partits pendents;
- permetre `exceptional` controlat;
- revisar clusters/manual overrides.

### Costos Relatius

Pesos actuals rellevants:

```text
level_distance_weight = 1000
exceptional_level_penalty = 3000
classification_fit_weight = 500
vehicle_easy_segment_penalty = 250
pressure_relief_weight = 50
warning_cost = 15
```

El nivell ja bloqueja casos extrems, pero els pesos encara poden ajustar-se per:

- reduir B en SENIOR si es vol mes estricte;
- afavorir mes partits top classificacio;
- reservar millor vehicles;
- evitar penalitzar massa cobertura global.

## 17. Checklist Per Estudiar Un Run

Per revisar un run `package_solver`, mirar:

```text
result_summary.engine_name
result_summary.package_solver_summary[0].solver_objective
result_summary.package_solver_summary[0].selected_by_level_fit
result_summary.package_solver_summary[0].level_exceptional_selected_count
result_summary.package_solver_summary[0].level_forbidden_candidate_count
result_summary.package_solver_summary[0].rejected_candidates_summary
```

Preguntes:

```text
Hi ha selected_by_level_fit forbidden? No n'hi hauria d'haver.
Hi ha massa exceptional?
Quants partits queden pendents?
Els pendents son per vehicle, nivell o disponibilitat?
Les rutes seleccionades tenen sentit geografic?
Els SENIOR han anat a A o com a molt B exceptional?
Els partits 1vs2 han anat a tutors forts?
```

Si apareix una assignacio aparentment incoherent:

1. Mirar categoria real del partit a `Match.category`.
2. Mirar nivell raw del tutor a `Availability.raw["Nivell"]`.
3. Mirar `selected_by_level_fit`.
4. Si el solver diu `ideal` pero visualment sembla malament, revisar `package.level_demand`.
5. Si `package.level_demand` no es la categoria mes exigent, revisar `hardest_match_level(...)` i la propagacio en splits/rutes.

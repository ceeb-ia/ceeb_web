# Pla d'implementacio del nou motor de recursos

## 0. Objectiu

Aquest document converteix `docs/especificacio_nou_motor_recursos.md` en un pla
executable per implementar el motor `resource_solver` per fases.

Esta escrit perque subagents paralels puguin treballar amb poc context previ,
amb write-sets separats i criteris d'acceptacio verificables.

El motor nou no substitueix el legacy en aquesta primera fase. Ha de conviure
com una variant nova dins:

```text
calendaritzacions/engine/variants/resource_solver/
```

La V1 legacy continua sent la referencia de compatibilitat i comparacio.

## 1. Principis tancats

Aquestes decisions ja no son preguntes obertes per a l'MVP:

```text
1. CP-SAT directe es el model principal.
2. No es preenumeren combinacions locals per decidir numeros.
3. `Num. sorteig`, `CASA` i `FORA` son lliures en l'MVP.
4. La fase es global del run: primera o segona.
5. Tots els grups comparteixen la fase comuna.
6. El grup es contenidor d'equips i numeros `1..8`, no calendari propi.
7. Un partit contra numero buit es descans i no consumeix recurs.
8. Els numeros buits han d'estar equilibrats entre grups comparables.
9. Separar equips de la mateixa entitat es dur excepte quan es infactible.
10. Les relaxacions son locals, no globals.
11. La pressio previa es auditoria/prioritzacio, no cost de l'objectiu.
12. Les combinacions locals son auditoria opcional post-solver.
```

## 2. No objectius de l'MVP

No s'ha d'implementar en aquesta primera versio:

```text
cost per acostar-se a `Num. sorteig`
semantica dura o soft de `CASA/FORA`
optimitzacio per classificacio de segona fase
fairness inter-categories equivalent al legacy
substitucio de l'Excel legacy
motor multi-run complet
UI o API nova
golden runs llargs obligatoris
```

Aixo es pot afegir despres si el motor base queda net i auditable.

## 3. Arquitectura objectiu

Estructura nova:

```text
calendaritzacions/
  engine/
    variants/
      resource_solver/
        __init__.py
        types.py
        config.py
        service.py
        input_adapter.py
        resources.py
        capacities.py
        groups.py
        candidates.py
        constraints/
          __init__.py
          base.py
          assignment.py
          group_size.py
          empty_numbers.py
          entity_separation.py
          resource_capacity.py
        objective.py
        model.py
        solution.py
        audit.py
        local_explanations.py
```

Tests nous:

```text
tests/
  test_resource_solver_resources.py
  test_resource_solver_groups.py
  test_resource_solver_candidates.py
  test_resource_solver_constraints.py
  test_resource_solver_model.py
  test_resource_solver_solution.py
  test_resource_solver_audit.py
  test_resource_solver_service.py
```

## 4. Contractes de dades

### 4.1. `ResourceSolverConfig`

Fitxer: `config.py`

Responsabilitats:

```text
time_limit_seconds
capacity_mode: hard | soft
resource_excess_weight
entity_excess_weight
empty_number_balance_mode: hard | soft
empty_number_imbalance_weight
capacity_estimation_method
local_explanation_threshold
phase_name
```

Valors MVP recomanats:

```text
capacity_mode = soft
resource_excess_weight = 100000
entity_excess_weight = 10000
empty_number_balance_mode = hard
time_limit_seconds = 30
local_explanation_threshold = 50000
```

### 4.2. `TeamRecord`

Fitxer: `types.py`

Camp minim:

```text
team_id
name
entity
league_name
modality
category
subcategory
level
venue
day
time
seed_request_original
```

Notes:

```text
seed_request_original es nomes auditable en l'MVP.
venue/day/time poden tenir valors normalitzats de "sense dada".
team_id ha de ser estable i venir de la ingesta legacy si ja existeix.
```

### 4.3. `BaseResource`

Fitxer: `types.py`

```text
resource_id
venue
day
hour_slot
```

Representa `Pista joc + Dia partit + franja_hora`, sense jornada.

### 4.4. `TimedResource`

Fitxer: `types.py`

```text
resource_id
base_resource_id
venue
day
hour_slot
round_index
date
```

`date` pot ser `None` si el motor nomes treballa amb jornada abstracta.

### 4.5. `GroupSpec`

Fitxer: `types.py`

```text
group_id
min_size
max_size
target_size
phase_name
numbers = 1..8
```

Els grups no tenen calendari propi. `phase_name` es igual per tots els grups del
run.

### 4.6. `Candidate`

Fitxer: `types.py`

```text
candidate_id
team_id
group_id
number
seed_request_original
potential_home_rounds
opponent_number_by_round
potential_resources
```

`potential_resources` no implica consum real si el rival acaba sent un numero
buit.

### 4.7. `SolverContext`

Fitxer: `types.py`

```text
teams
phase
base_resources
capacities
pressure
groups
candidate_catalog
config
```

Ha de ser immutable o tractat com a read-only un cop creat.

### 4.8. `ResourceSolverResult`

Fitxer: `types.py`

```text
status
objective_value
best_bound
wall_time
assignments
real_matches
resource_usage
group_summary
entity_excess
audit_payloads
logs
```

`status` ha de distingir com a minim:

```text
OPTIMAL
FEASIBLE
INFEASIBLE
UNKNOWN
```

## 5. Restriccions del model

Les restriccions han de viure en moduls petits dins `constraints/`.

Cada modul ha d'exposar una funcio o classe amb un contracte semblant:

```python
class ConstraintBuilder(Protocol):
    name: str

    def add(self, model, variables, context, objective_terms, audit_terms) -> None:
        ...
```

### 5.1. Assignacio unica

Fitxer: `constraints/assignment.py`

Per cada equip:

```text
sum(x[equip, grup, numero]) = 1
```

Criteri:

```text
sempre dura
mai relaxable
```

### 5.2. Numero unic dins grup

Fitxer: `constraints/group_size.py` o `constraints/assignment.py`

Per cada `grup, numero`:

```text
sum(x[equip, grup, numero]) <= 1
```

Un numero sense equip assignat es valid i representa possible descans.

### 5.3. Mida de grup

Fitxer: `constraints/group_size.py`

Per cada grup:

```text
min_size[grup] <= equips_assignats[grup] <= max_size[grup]
```

L'MVP pot usar mides precomputades per `groups.py` i fer la restriccio exacta:

```text
equips_assignats[grup] = target_size[grup]
```

### 5.4. Numeros buits equilibrats

Fitxer: `constraints/empty_numbers.py`

Per cada grup:

```text
buits[grup] = 8 - equips_assignats[grup]
```

Per grups comparables de la mateixa categoria:

```text
max(buits) - min(buits) <= 1
```

Si les mides de grup ja venen equilibrades, aquesta restriccio queda satisfeta
per construccio. Igualment s'ha d'auditar.

### 5.5. Entitat separada

Fitxer: `constraints/entity_separation.py`

Per cada entitat i grup:

```text
count_entitat_grup = sum(x[equip, grup, numero] per equips de l'entitat)
```

Si `num_equips_entitat <= num_grups`:

```text
count_entitat_grup <= 1
```

Si `num_equips_entitat > num_grups`:

```text
exces_entitat[entitat, grup] >= count_entitat_grup - 1
exces_entitat[entitat, grup] >= 0
```

I l'objectiu minimitza:

```text
sum(exces_entitat * entity_excess_weight)
```

La relaxacio nomes afecta aquella entitat dins aquella categoria.

### 5.6. Capacitat de recurs

Fitxer: `constraints/resource_capacity.py`

Per cada `TimedResource`:

```text
locals[recurs] = sum(partits reals locals que consumeixen recurs)
```

La part delicada es "partit real":

```text
partit real = numero local ocupat i numero rival ocupat dins el mateix grup
```

Si el numero rival es buit:

```text
descans, no consumeix recurs
```

Implementacio recomanada:

```text
crear variables y[team, group, number, round] que indiquen consum real local
y nomes pot ser 1 si x[team, group, number] = 1
y nomes pot ser 1 si existeix algun equip assignat al numero rival del mateix grup
locals[recurs] = sum(y que apunten al recurs)
```

En CP-SAT, evitar productes de binaries directes. Usar variables auxiliars i
restriccions lineals:

```text
y <= x_local
y <= occupied[group, opponent_number]
y >= x_local + occupied[group, opponent_number] - 1
```

Si `capacity_mode = hard`:

```text
locals[recurs] <= capacitat[recurs]
```

Si `capacity_mode = soft`:

```text
exces_recurs >= locals[recurs] - capacitat[recurs]
exces_recurs >= 0
minimitzar exces_recurs * resource_excess_weight
```

## 6. Objectiu de l'MVP

L'objectiu inicial ha de ser curt i auditable:

```text
minimitzar:
  cost_exces_recursos
+ cost_exces_entitat
+ cost_descansos_si_soft
```

No incloure:

```text
cost Num. sorteig
cost CASA/FORA
cost pressio
cost combinacions locals
```

Els pesos han de quedar al `solver_model_summary.json`.

## 7. Auditoria i explicabilitat

L'auditoria no ha de ser un afegit final improvisat. Cada capa ha de retornar
dades auditables.

### 7.1. `resource_pressure.json`

Generat per `resources.py` i `capacities.py`.

Contingut:

```text
venue
day
hour_slot
teams
demand_count
estimated_capacity
pressure
capacity_method
is_critical
```

### 7.2. `candidate_catalog.json`

Generat per `candidates.py`.

Contingut:

```text
team_id
group_id
number
seed_request_original
potential_home_rounds
opponent_number_by_round
potential_resources
```

### 7.3. `solver_model_summary.json`

Generat per `model.py`.

Contingut:

```text
num_teams
num_groups
num_candidates
num_variables
num_constraints
num_resource_constraints
num_entity_constraints
objective_terms
weights
time_limit_seconds
status
objective_value
best_bound
wall_time
```

### 7.4. `resource_solution.json`

Generat per `solution.py`.

Contingut:

```text
assignments_by_team
groups
empty_numbers
rests_by_team
real_matches
resource_usage_by_round
resource_excess
entity_excess
```

### 7.5. `solver_explanations.json`

Generat per `audit.py`.

Ha d'explicar:

```text
recursos saturats
excessos de capacitat
excessos d'entitat inevitables
descansos per equip
numeros finals diferents del `Num. sorteig` original, nomes informatiu
status del solver i si la solucio es optima o nomes feasible
```

### 7.6. `local_combinations.json`

Generat per `local_explanations.py`.

Opcional. Nomes per blocs petits, critics o amb incidencia.

Contingut:

```text
venue
day
hour_slot
capacity
input_pressure
solver_solution_local
round_usage
nearby_alternatives
why_alternatives_fail_or_cost_more
```

No es una entrada del solver.

## 8. Pla per fases

### Fase RS-00: scaffold i contractes

Objectiu:

```text
crear paquet `resource_solver`
definir dataclasses i config
no implementar solver encara
```

Write-set:

```text
calendaritzacions/engine/variants/__init__.py
calendaritzacions/engine/variants/resource_solver/__init__.py
calendaritzacions/engine/variants/resource_solver/types.py
calendaritzacions/engine/variants/resource_solver/config.py
tests/test_resource_solver_contracts.py
```

Criteris d'acceptacio:

```text
imports funcionen
dataclasses es poden instanciar
config te valors per defecte de l'MVP
cap import de FastAPI, Excel writer ni Redis
```

Verificacio:

```powershell
py -3 -m pytest -q tests/test_resource_solver_contracts.py
py -3 -m compileall calendaritzacions/engine/variants/resource_solver
```

### Fase RS-01: recursos, normalitzacio i pressio

Objectiu:

```text
normalitzar `Pista joc`, `Dia partit`, `Horari partit`
agrupar equips per venue/day/hour_slot
calcular demanda i pressio
estimar capacitat N
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/input_adapter.py
calendaritzacions/engine/variants/resource_solver/resources.py
calendaritzacions/engine/variants/resource_solver/capacities.py
tests/test_resource_solver_resources.py
```

Contractes:

```text
build_team_records(df) -> list[TeamRecord]
build_base_resources(teams) -> dict[resource_id, BaseResource]
estimate_capacities(resources, teams, config) -> dict[resource_id, capacity]
build_resource_pressure(resources, teams, capacities) -> list[PressureRow]
```

Regles:

```text
18:00, 18:15, 18:30, 18:45 -> 18:00
19:00, 19:30 -> 19:00
pista buida -> etiqueta controlada
dia buit -> etiqueta controlada
hora buida -> etiqueta controlada
```

Criteris d'acceptacio:

```text
demanda compta equips unics, no files duplicades
capacitat mai baixa de 1
metode de capacitat queda auditat
pressio no decideix assignacions
```

### Fase RS-02: grups, mides i numeros buits

Objectiu:

```text
calcular grups possibles per categoria
repartir mides equilibrades
derivar numeros buits esperats per grup
validar fase comuna
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/groups.py
tests/test_resource_solver_groups.py
```

Contractes:

```text
build_group_specs(teams, phase, config) -> list[GroupSpec]
group_size_targets(num_teams) -> list[int]
empty_numbers_by_group(group_specs) -> dict[group_id, int]
```

Regles:

```text
grups de maxim 8 equips
mides tan equilibrades com sigui possible
diferencia de buits entre grups <= 1
tots els grups comparteixen phase_name
```

Criteris d'acceptacio:

```text
14 equips -> 2 grups de 7, 1 buit cadascun
17 equips -> grups equilibrats, diferencia de buits <= 1
8 equips -> 1 grup, 0 buits
5 equips -> 1 grup, 3 buits
```

### Fase RS-03: candidats i projeccio de calendari

Objectiu:

```text
generar candidats equip + grup + numero
conservar `Num. sorteig` nomes com auditoria
projectar jornades locals potencials
identificar numero rival per jornada
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/candidates.py
tests/test_resource_solver_candidates.py
```

Contractes:

```text
generate_candidates(teams, group_specs, phase, resources) -> CandidateCatalog
home_rounds_for_number(number, phase) -> list[int]
opponent_by_round(number, phase) -> dict[round_index, opponent_number]
```

Regles:

```text
CASA -> candidats 1..8
FORA -> candidats 1..8
numero explicit -> candidats 1..8
buit -> candidats 1..8
```

Criteris d'acceptacio:

```text
cap cost de peticio
cap filtratge per CASA/FORA
candidate_id estable
potencial local no implica partit real si rival queda buit
```

### Fase RS-04: arquitectura de restriccions

Objectiu:

```text
crear sistema extensible de constraints
implementar constraints sense executar encara servei complet
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/constraints/__init__.py
calendaritzacions/engine/variants/resource_solver/constraints/base.py
calendaritzacions/engine/variants/resource_solver/constraints/assignment.py
calendaritzacions/engine/variants/resource_solver/constraints/group_size.py
calendaritzacions/engine/variants/resource_solver/constraints/empty_numbers.py
calendaritzacions/engine/variants/resource_solver/constraints/entity_separation.py
calendaritzacions/engine/variants/resource_solver/constraints/resource_capacity.py
tests/test_resource_solver_constraints.py
```

Contractes:

```text
add_assignment_constraints(...)
add_group_size_constraints(...)
add_empty_number_constraints(...)
add_entity_separation_constraints(...)
add_resource_capacity_constraints(...)
```

Criteris d'acceptacio:

```text
cada constraint es testable en model petit
relaxacio d'entitat nomes apareix quan equips_entitat > num_grups
capacitat ignora partits contra descans
no hi ha dependencias circulars entre constraints
```

Nota:

```text
si OR-Tools no esta instal.lat a l'entorn local, els tests poden saltar-se amb
skip explicit, pero el codi ha d'estar preparat per usar `ortools.sat.python.cp_model`.
```

### Fase RS-05: model CP-SAT i objectiu

Objectiu:

```text
construir model complet per una categoria
executar CP-SAT amb time limit
retornar status i variables actives
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/model.py
calendaritzacions/engine/variants/resource_solver/objective.py
tests/test_resource_solver_model.py
```

Contractes:

```text
build_solver_model(context) -> BuiltModel
solve_model(built_model, config) -> RawSolverResult
```

Variables minimes:

```text
x[team_id, group_id, number]
occupied[group_id, number]
real_home[team_id, group_id, number, round_index]
resource_excess[resource_id, round_index] si capacity soft
entity_excess[entity, group_id] si inevitable
```

Criteris d'acceptacio:

```text
cas simple de 8 equips resol OPTIMAL
cas de 14 equips reparteix 7/7
cas amb rival buit no consumeix recurs
cas entitat infactible retorna FEASIBLE/OPTIMAL amb exces minim
cas capacitat impossible amb mode soft retorna exces minim
cas capacitat impossible amb mode hard retorna INFEASIBLE
```

### Fase RS-06: solucio i partits reals

Objectiu:

```text
convertir resultat CP-SAT a assignacio de negoci
calcular partits reals, descansos i consum real
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/solution.py
tests/test_resource_solver_solution.py
```

Contractes:

```text
build_solution(raw_result, context) -> ResourceSolverResult
build_assignments(...)
build_real_matches(...)
build_resource_usage(...)
build_group_summary(...)
```

Criteris d'acceptacio:

```text
cada equip apareix una vegada
cada grup-numero te 0 o 1 equip
descansos es calculen quan opponent_number esta buit
resource_usage no suma descansos
group_summary inclou numeros_buits
```

### Fase RS-07: auditoria i explicabilitat

Objectiu:

```text
generar JSONs auditables del motor
explicar pressio, solucio, excessos i alternatives locals
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/audit.py
calendaritzacions/engine/variants/resource_solver/local_explanations.py
tests/test_resource_solver_audit.py
```

Contractes:

```text
build_resource_pressure_audit(context)
build_candidate_catalog_audit(context)
build_solver_model_summary(raw_result, built_model, context)
build_resource_solution_audit(result)
build_solver_explanations(result, context)
build_local_explanations(result, context)
```

Criteris d'acceptacio:

```text
payloads son JSON-ready
cap DataFrame cru dins JSON
alternatives locals son opcionals
si bloc supera threshold, s'audita que no s'ha enumerat
status FEASIBLE indica que no s'ha demostrat optimalitat
```

### Fase RS-08: service i registre de motor

Objectiu:

```text
exposar `ResourceSolverEngine.run(...)`
registrar engine_name = "resource_solver"
retornar EngineResult compatible
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/engine/variants/resource_solver/__init__.py
calendaritzacions/engine/registry.py
tests/test_resource_solver_service.py
```

Contractes:

```text
class ResourceSolverEngine:
    def run(input_path, config, progress=None) -> EngineResult
```

Flux:

```text
read_excel(input_path)
prepare input records
per categoria o fixture MVP:
  build context
  solve
  build solution
  build audits
write audit JSONs
write output compatible minim
return EngineResult
```

Criteris d'acceptacio:

```text
get_engine("resource_solver") funciona
process_calendarization(..., engine_name="resource_solver") entra al motor nou
no trenca engine_name="legacy"
retorna output_path i audit_paths
```

### Fase RS-09: comparatives contra legacy

Objectiu:

```text
executar fixtures petites amb legacy i resource_solver
comparar metriques, no igualtat exacta de grups
```

Write-set:

```text
tests/test_resource_solver_comparison.py
tests/fixtures/resource_solver/**
```

Metriques:

```text
exces_recursos_total
jornades_amb_exces
exces_entitat_total
descansos_per_grup
status solver
temps
```

Criteris d'acceptacio:

```text
fixtures petites executen rapid
no xarxa
no golden run llarg
comparativa queda documentada en asserts comprensibles
```

## 9. Subagents paralels recomanats

### Grup A: base i recursos

Agents:

```text
AGENT-RS-00 scaffold
AGENT-RS-01 resources-pressure
```

Poden treballar abans del solver. RS-01 depen dels tipus de RS-00.

### Grup B: grups i candidats

Agents:

```text
AGENT-RS-02 groups
AGENT-RS-03 candidates
```

RS-03 depen de `GroupSpec` i de la fase, pero pot usar fixtures simples mentre
RS-02 acaba.

### Grup C: constraints i model

Agents:

```text
AGENT-RS-04 constraints
AGENT-RS-05 model-objective
```

RS-05 no ha d'editar constraints individuals si RS-04 els esta implementant. Ha
de consumir-ne la interfici publica.

### Grup D: solucio i auditoria

Agents:

```text
AGENT-RS-06 solution
AGENT-RS-07 audit-local-explanations
```

Poden treballar amb `RawSolverResult` fake fins que RS-05 estigui llest.

### Grup E: integracio

Agents:

```text
AGENT-RS-08 service-registry
AGENT-RS-09 comparison
```

Han d'anar al final per evitar acoblar el motor abans que els contractes siguin
estables.

## 10. Regles per subagents

Cada subagent ha de respectar:

```text
no tocar fitxers fora del write-set sense avisar
no modificar legacy per adaptar-lo al motor nou
no canviar comportament de `legacy`
no introduir dependencia de FastAPI/Redis/reporting Excel al solver
afegir tests petits del seu modul
produir payloads JSON-ready quan toqui auditoria
usar dataclasses de `types.py` en comptes de dicts ad hoc quan sigui possible
```

Si cal afegir una dada nova a un contracte compartit:

```text
1. modificar `types.py`
2. actualitzar tests de contracte
3. documentar quin agent consumeix el camp
```

## 11. Estrategia de tests

### 11.1. Unit tests purs

Han de cobrir:

```text
normalitzacio hora a franja
estimacio capacitat
pressio per recurs
repartiment de grups
generacio candidats 1..8
patrons casa/fora per fase
opponent_number_by_round
descans quan rival buit
```

### 11.2. Tests de model petits

Fixtures recomanades:

```text
8 equips, 1 grup, capacitat suficient
14 equips, 2 grups de 7, descansos equilibrats
5 equips, 1 grup, 3 descansos
4 grups, entitat amb 5 equips, exces inevitable minim
2 recursos saturats amb capacity soft
capacity hard impossible
```

### 11.3. Tests d'auditoria

Han de verificar:

```text
JSON serialitzable
resource_solution no compta descansos com consum
solver_explanations marca FEASIBLE vs OPTIMAL
local_combinations pot quedar parcial per threshold
```

### 11.4. Tests d'integracio

Han de verificar:

```text
registre del motor
EngineResult compatible
legacy continua registrat
process_calendarization amb engine_name nou no passa per legacy
```

## 12. Ordre recomanat d'implementacio

Ordre lineal si no hi ha paralelisme:

```text
1. RS-00 scaffold
2. RS-01 resources-pressure
3. RS-02 groups
4. RS-03 candidates
5. RS-04 constraints
6. RS-05 model-objective
7. RS-06 solution
8. RS-07 audit
9. RS-08 service-registry
10. RS-09 comparison
```

Ordre paralel:

```text
RS-00 primer
RS-01 i RS-02 en paralel
RS-03 despres de RS-02
RS-04 pot comencar amb fixtures manuals
RS-05 despres de RS-04 base
RS-06 i RS-07 amb resultats fake mentre RS-05 madura
RS-08 i RS-09 al final
```

## 13. Definicio de fet de l'MVP

Es considera completat l'MVP quan:

```text
1. Existeix engine registrat `resource_solver`.
2. Pot executar una categoria petita sense tocar legacy.
3. CP-SAT decideix grup i numero.
4. `Num. sorteig` no afecta l'objectiu.
5. Capacitat de recursos es modela directament.
6. Partits contra descans no consumeixen recurs.
7. Numeros buits estan equilibrats.
8. Entitat separada es dura excepte infactibilitat local.
9. Es generen JSONs d'auditoria.
10. Tests petits passen.
11. Legacy continua passant els tests existents.
```

## 14. Riscos principals

### 14.1. OR-Tools no disponible

Mitigacio:

```text
import lazy dins model.py
tests amb skip si no esta instal.lat
documentar dependencia quan s'activi el motor real
```

### 14.2. Model massa gran

Mitigacio:

```text
MVP per categoria
time limit configurable
auditar num_variables i num_constraints
reduir candidats nomes si hi ha una regla dura real, no per preferencia
```

### 14.3. Recursos mal normalitzats

Mitigacio:

```text
auditar missing venue/day/time
normalitzacio determinista
no barrejar pistes buides amb pistes reals sense etiqueta explicita
```

### 14.4. Confondre descans amb partit

Mitigacio:

```text
tests especifics de rival buit
resource_usage calculat nomes des de partits reals
auditoria de jornades_descans
```

### 14.5. Relaxacions massa globals

Mitigacio:

```text
slack nomes per entitat/grup o recurs/jornada afectat
tests d'entitats factibles que han de continuar hard
auditar exces inevitable separat de exces evitable
```

## 15. Futures extensions previstes

Quan l'MVP estigui estable, es poden afegir com a constraints/plugins:

```text
preferencies `Num. sorteig`
semantica CASA/FORA
nivell i classificacio
fairness entre entitats
restriccions de dies
restriccions de modalitat
capacitats reals carregades de taula externa
dates reals per jornada
warm starts opcionals
```

Cada extensio nova ha de seguir el patro:

```text
constraint module separat
tests propis
termes d'objectiu separats
auditoria propia
config explicita
```

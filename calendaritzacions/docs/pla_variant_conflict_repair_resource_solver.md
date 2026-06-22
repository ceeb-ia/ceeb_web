# Pla d'implementacio: variant conflict-repair del resource_solver

## 0. Objectiu

Aquest document defineix una variant nova del `resource_solver` pensada per
escapar del component unic quan el run te milers d'equips i molts recursos
compartits.

La variant no ha de substituir ni modificar el motor actual. Ha de conviure com
un motor registrat separat i reutilitzar les peces existents sempre que sigui
possible:

```text
resource_solver actual:
  resol el context global, o components connexos segurs, amb recursos com a
  dependencies estructurals.

resource_solver_conflict_repair:
  resol primer components esportius mes petits, ignora l'acoblament global de
  recursos en la primera passada, detecta xocs reals i reoptimitza nomes blocs
  conflictius.
```

El problema que es vol atacar es aquest:

```text
team -> competition
team -> resource base
team -> linkage
```

Quan moltes competicions comparteixen `Pista joc + Dia partit + Horari partit`,
el node `resource` fa de pont i pot connectar gairebe tot el run. Aquesta
connectivitat es potencial: no vol dir que totes aquestes competicions xoquin
realment a la solucio final. La variant proposada converteix els recursos en una
fase de conciliacio posterior.

Flux objectiu:

```text
Excel
  -> context global resource_solver
  -> components inicials sense arestes de recurs
  -> solve inicial per component
  -> merge d'assignacions
  -> deteccio d'excessos reals per recurs+jornada
  -> blocs de reparacio
  -> re-solve dels blocs conflictius amb capacitat residual
  -> validacio global final
  -> Excel i auditories
```

## 1. Principis tancats

```text
1. No tocar el comportament de `resource_solver`, `resource_solver_linkage` ni
   `resource_solver_vinculacio`.
2. Implementar una variant nova registrable amb nom propi.
3. Reutilitzar `SolverContext`, `Candidate`, `GroupSpec`, `build_solver_model`,
   `solve_model`, `build_solution` i els writers existents.
4. Construir el context global una sola vegada des del dataframe complet.
5. No recalcular capacitats des de subsets del dataframe.
6. La primera passada no usa recursos com a arestes de particio.
7. Els linkages forts si que connecten components inicials.
8. La reparacio no reobre tot el mon: nomes blocs amb xocs reals.
9. Els equips fora del bloc de reparacio queden congelats.
10. La capacitat disponible en reparacio ha de tenir en compte l'us congelat.
11. L'MVP pot reordenar mes del compte dins un bloc reparat; la penalitzacio de
    canvi minim es una fase posterior.
12. Si la reparacio no millora o crea un bloc massa gran, el run ha de quedar
    auditable, no silencios.
```

## 2. No objectius de l'MVP

No implementar en la primera prova:

```text
1. Optimitzacio global exacta equivalent al solve actual.
2. Pistes internes com a variable nova del model.
3. Penalitzacio per mantenir el numero/grup inicial.
4. Lazy constraints incrementals dins una mateixa instancia CP-SAT.
5. Persistencia DB/Celery especifica per aquesta variant.
6. UI nova obligatoria.
7. Reparacio il-limitada fins a zero incidents.
8. Canvis al workbook actual fora dels artifacts addicionals.
```

La primera prova ha de respondre:

```text
redueix la mida maxima del model?
quin excés inicial apareix quan resolc per components esportius?
quants blocs de reparacio calen?
la reparacio redueix excessos sense disparar el temps?
quins casos acaben necessitant merge gran?
```

## 3. Encaix amb el codi actual

### 3.1. Contracte de motor

El contracte es `CalendarizationEngine.run`:

```text
calendaritzacions/engine/base.py
```

La variant ha de retornar `EngineResult`.

Registre actual:

```text
calendaritzacions/engine/registry.py
```

S'ha d'afegir una entrada nova, per exemple:

```python
_ENGINES["resource_solver_conflict_repair"] = _resource_solver_conflict_repair_engine()
```

No s'ha de canviar la instancia registrada per:

```text
resource_solver
resource_solver_linkage
resource_solver_vinculacio
```

### 3.2. Configuracio

El punt d'entrada d'aplicacio construeix `EngineConfig` a:

```text
calendaritzacions/application/use_cases.py
```

Per l'MVP es pot reutilitzar `EngineConfig` sense camps nous. La variant pot
interpretar els camps existents:

```text
phase_name
resource_solver_level_constraint_mode
resource_solver_linkage_mode
resource_solver_competition_grouping
```

Si es vol exposar per Django caldra afegir el nou engine a:

```text
calendaritzacions/django/models.py
calendaritzacions/django/forms.py
```

Per una primera prova tecnica pot ser suficient registrar el motor i executar-lo
des de tests o crides internes.

### 3.3. Peces reutilitzables

Reutilitzar directament:

```text
calendaritzacions/engine/variants/resource_solver/input_adapter.py
  build_context_from_dataframe
  competition_key_for_team

calendaritzacions/engine/variants/resource_solver/component_context.py
  filter_context_by_team_ids

calendaritzacions/engine/variants/resource_solver/model.py
  build_solver_model
  solve_model

calendaritzacions/engine/variants/resource_solver/solution.py
  build_solution
  result_to_json_ready

calendaritzacions/engine/variants/resource_solver/audit.py
  write_audit_payloads
  build_audit_payloads, quan encaixi amb el resultat final

calendaritzacions/reporting/resource_solver_excel_adapter.py
  write_resource_solver_workbook

calendaritzacions/reporting/resource_solver_plots.py
  write_resource_solver_final_plots
```

No reutilitzar com a particio inicial:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
```

Aquest modul es conservador i inclou `resource` com a node. La nova variant
necessita un graf inicial diferent.

## 4. Model mental de la variant

### 4.1. Graf inicial

El graf inicial no te nodes de recurs.

Opcio conceptual tipada:

```text
team -> competition
team -> linkage
```

Opcio agregada equivalent:

```text
nodes = competition_key
edge = hi ha linkage entre equips de competicions diferents
```

Regla:

```text
si no hi ha linkage entre competicions:
  una competicio = un component inicial

si hi ha linkage entre competicions:
  les competicions linkades es resolen juntes
```

Els equips continuen sent la unitat que resol CP-SAT. El graf nomes decideix
quins equips entren en cada solve inicial.

### 4.2. Que vol dir "cec als recursos"

La primera passada no ignora els recursos dins el model, pero no deixa que els
recursos connectin competicions externes.

Exemple:

```text
Lliga A i Lliga B comparteixen Pavello / Dissabte / 10:00.

Primera passada:
  Lliga A es resol sola.
  Lliga B es resol sola.
  Cadascuna veu les seves capacitats, pero no veu els locals de l'altra.

Conciliacio:
  el merge global detecta si A+B superen la capacitat real en alguna jornada.
```

### 4.3. Graf de conflictes

Despres del merge inicial:

```text
node = component inicial o competition_key
edge = comparteixen un recurs temporitzat amb excess real
```

Un recurs temporitzat es:

```text
base_resource_id|J<round_index>
```

Exemple:

```text
pavello-a|dissabte|10-00|J3
```

Els hubs amb excess creen blocs de reparacio. Si dos hubs comparteixen una
competicio afectada, han d'anar al mateix bloc.

### 4.4. Expansio per linkage

Qualsevol bloc de reparacio s'ha d'expandir amb els linkages necessaris.

Regla:

```text
si un equip reoptimitzat te linkage actiu amb un equip fora del bloc:
  afegir la competition_key de l'equip extern al bloc
```

Per l'MVP, no implementar referencia externa congelada per linkage. Es mes net
expandir el bloc.

## 5. Fases de pipeline

### 5.1. Fase A: construir context global

Responsabilitat:

```text
Llegir input i construir el mateix SolverContext que el resource_solver actual.
```

Pseudocodi:

```python
input_df = read_excel(input_path)
solver_config = coerce_resource_solver_config(config)
context = build_context_from_dataframe(input_df, solver_config)
```

Important:

```text
No construir contexts per competicio des de dataframes filtrats.
Les capacitats i recursos han de venir del context global.
```

### 5.2. Fase B: components inicials

Crear un helper nou:

```text
calendaritzacions/engine/variants/resource_solver/conflict_repair.py
```

Funcions recomanades:

```python
def build_initial_components(context: SolverContext) -> tuple[InitialComponent, ...]:
    ...
```

Contracte proposat:

```python
@dataclass(frozen=True)
class InitialComponent:
    component_id: str
    competition_keys: tuple[str, ...]
    team_ids: tuple[str, ...]
    linkage_keys: tuple[str, ...]
```

Com calcular `competition_key`:

```python
competition_key_for_team(team, context.config)
```

Com calcular linkage:

```text
mateixa logica que constraints/linkage.py:
  linkage_group normalitzat
  side no indiferent
  venue normalitzat
  bucket amb mes d'un equip
```

Per l'MVP es pot reutilitzar o duplicar minimament la logica de buckets, pero el
millor es extreure un helper compartit en una fase posterior.

### 5.3. Fase C: solve inicial

Per cada component:

```python
subcontext = filter_context_by_team_ids(context, component.team_ids)
built_model = build_solver_model(subcontext)
raw_result = solve_model(built_model, subcontext.config)
solution = build_solution(raw_result, subcontext)
```

Guardar per auditoria:

```text
initial_components/<component_id>/model_summary.json
initial_components/<component_id>/raw_result.json
initial_components/<component_id>/solution_partial.json
```

Si algun component inicial retorna `INFEASIBLE`, el run pot acabar amb estat
explicable. No intentar reparar recursos si no hi ha calendari inicial.

### 5.4. Fase D: merge inicial

Ajuntar totes les assignacions:

```python
initial_assignments = sorted(assignments_from_all_components)
initial_raw = SimpleNamespace(
    status="FEASIBLE" or "OPTIMAL",
    assignments=tuple(initial_assignments),
    objective_value=None,
    best_bound=None,
    wall_time=sum(component.wall_time),
    entity_excess={},
    logs=(...),
)
initial_result = build_solution(initial_raw, context)
```

Aquest `initial_result` permet obtenir:

```text
real_matches
resource_usage
group_summary
entity_excess
```

### 5.5. Fase E: detectar excessos reals

Un hub conflictiu ve de:

```python
for row in initial_result.resource_usage:
    if row.excess > 0:
        ...
```

Contracte proposat:

```python
@dataclass(frozen=True)
class ConflictHub:
    resource_id: str
    base_resource_id: str
    round_index: int
    locals_count: int
    capacity: int
    excess: int
    team_ids: tuple[str, ...]
    competition_keys: tuple[str, ...]
```

Cal mapar:

```text
team_id -> competition_key
team_id -> initial_component_id
```

### 5.6. Fase F: construir blocs de reparacio

Nodes:

```text
initial_component_id
```

Arestes:

```text
dos components comparteixen un ConflictHub
```

Despres expandir per linkage:

```text
mentre hi hagi un team del bloc amb linkage cap a un team fora:
  afegir el component extern
```

Contracte proposat:

```python
@dataclass(frozen=True)
class RepairBlock:
    block_id: str
    initial_component_ids: tuple[str, ...]
    team_ids: tuple[str, ...]
    conflict_resource_ids: tuple[str, ...]
    expanded_by_linkage: bool
```

### 5.7. Fase G: calcular capacitat residual

Per cada bloc, els equips fora del bloc queden congelats.

Cal calcular l'us congelat per recurs temporitzat:

```python
frozen_usage[resource_id] = locals_count_from_matches_outside_block
```

Per cada recurs temporitzat que apareix en candidats del bloc o en hubs
conflictius:

```text
remaining_capacity = original_capacity(resource_id) - frozen_usage[resource_id]
```

La constraint actual ja permet capacitat per clau temporitzada:

```text
calendaritzacions/engine/variants/resource_solver/constraints/resource_capacity.py
capacity_for_resource(context, resource_id):
  1. mira context.capacities[resource_id]
  2. si no hi es, treu |J i mira el recurs base
```

Per tant l'MVP pot crear un subcontext de reparacio amb overrides:

```python
repair_context.capacities[timed_resource_id] = CapacityEstimate(
    base_resource_id=timed_resource_id,
    capacity=max(0, remaining_capacity),
    method="conflict_repair_residual",
    demand_count=...
)
```

Nota:

```text
La capacitat residual pot ser 0. Aixo es valid per la constraint CP-SAT actual,
perque `capacity_for_resource` retorna la clau directa sense aplicar max(1).
```

### 5.8. Fase H: re-solve de blocs conflictius

Per cada bloc:

```python
repair_context = filter_context_by_team_ids(context, block.team_ids)
repair_context = with_residual_capacities(repair_context, frozen_usage)
built_model = build_solver_model(repair_context)
raw_result = solve_model(built_model, repair_context.config)
repair_solution = build_solution(raw_result, repair_context)
```

Si el bloc no es `FEASIBLE` o `OPTIMAL`:

```text
conservar la solucio inicial d'aquest bloc
marcar repair status = failed
continuar amb auditoria
```

Per l'MVP no cal penalitzar canvis respecte la solucio inicial. Fase posterior:

```text
afegir objective term change_penalty per candidats diferents dels inicials
```

### 5.9. Fase I: merge final

Construir assignacions finals:

```text
per blocs reparats amb exit:
  usar assignacions reparades

per la resta:
  usar assignacions inicials
```

Despres:

```python
final_raw = SimpleNamespace(assignments=final_assignments, ...)
final_result = build_solution(final_raw, context)
```

Validacions:

```text
1. Cada equip global te exactament una assignacio.
2. Cap equip desconegut.
3. Cada assignacio existeix com a Candidate del context global.
4. Cap group_id queda amb mida incorrecta.
5. Linkage audit final disponible.
6. Resource excess final calculat.
```

Es pot reutilitzar part de:

```text
calendaritzacions/engine/variants/resource_solver/component_merge.py
```

Pero l'MVP pot tenir una validacio propia mes simple si treballa amb objectes en
memoria.

### 5.10. Fase J: iteracio opcional

Per primera prova:

```text
max_repair_iterations = 1
```

Deixar el disseny preparat per:

```text
iteracio 0 = solucio inicial
iteracio 1 = reparacio dels blocs conflictius
iteracio 2 = nova reparacio si encara hi ha excessos grossos
```

No activar iteracions multiples fins tenir auditories estables.

## 6. Relacio amb nivells, entitats i linkages

### 6.1. Nivells

La variant ha de respectar el mode existent:

```text
off
soft
aggregate
hard
```

No cal codi especial si es reutilitza `build_context_from_dataframe`.

Efectes:

```text
hard:
  redueix candidats abans del solve i crea grups per familia dins de cada
  competicio. Es el mode mes interessant per rendiment.

aggregate:
  redueix molt variables respecte el mode soft pairwise.

soft:
  pot crear moltes variables en competicions grans.
```

Recomanacio per proves grans:

```text
level_constraint_mode = hard o aggregate
```

### 6.2. Entitats

La separacio d'entitat esta dins del model actual:

```text
calendaritzacions/engine/variants/resource_solver/constraints/entity_separation.py
```

En solve inicial funciona dins de cada component. En reparacio funciona dins del
bloc reparat.

Limit conegut:

```text
si dues competicions separades tenen restriccions d'entitat que nomes serien
rellevants globalment, l'MVP no les connecta. Actualment la logica d'entitat
esta lligada als grups accessibles per candidats, per tant normalment queda
dins competicio.
```

### 6.3. Linkages

Els linkages son dependencia estructural forta.

Regles:

```text
1. Un linkage intern a la mateixa competicio queda dins del solve normal.
2. Un linkage entre competicions connecta components inicials.
3. Un bloc de reparacio sempre s'expandeix pels linkages afectats.
4. No deixar un equip linkat fora congelat si l'altre pot canviar de numero.
```

Atencio amb `linkage_mode="simulated"`:

```text
Els linkages simulats poden recrear components grans. En l'MVP cal auditar
separadament input_linkage vs simulated_linkage si la informacio esta disponible.
Si el simulat connecta massa, considerar que nomes els linkages d'input
expandeixin blocs.
```

## 7. Artifacts i plots

Afegir artifacts propis de variant:

```text
conflict_repair_initial_components.json
conflict_repair_initial_solution.json
conflict_repair_conflict_hubs.json
conflict_repair_repair_blocks.json
conflict_repair_iteration_summary.json
conflict_repair_final_validation.json
```

Contingut minim:

### 7.1. Initial components

```json
{
  "artifact_type": "resource_solver_conflict_repair_initial_components",
  "component_count": 12,
  "components": [
    {
      "component_id": "I001",
      "team_count": 84,
      "competition_keys": ["fields|..."],
      "linkage_count": 0,
      "candidate_count": 672,
      "status": "OPTIMAL",
      "wall_time": 1.24
    }
  ]
}
```

### 7.2. Conflict hubs

```json
{
  "artifact_type": "resource_solver_conflict_repair_conflict_hubs",
  "summary": {
    "hubs_with_excess": 8,
    "total_excess": 17,
    "max_excess": 5
  },
  "hubs": [
    {
      "resource_id": "pavello-a|dissabte|10-00|J3",
      "locals_count": 7,
      "capacity": 4,
      "excess": 3,
      "team_ids": ["T1", "T9"],
      "competition_keys": ["league|A", "league|B"]
    }
  ]
}
```

### 7.3. Repair blocks

```json
{
  "artifact_type": "resource_solver_conflict_repair_blocks",
  "blocks": [
    {
      "block_id": "R001",
      "team_count": 126,
      "initial_component_ids": ["I001", "I004"],
      "conflict_resource_ids": ["pavello-a|dissabte|10-00|J3"],
      "expanded_by_linkage": false,
      "status": "FEASIBLE",
      "excess_before": 5,
      "excess_after": 1
    }
  ]
}
```

### 7.4. Plots recomanats

Per l'MVP, si es vol fer plots:

```text
1. components inicials per mida d'equips/candidats
2. top hubs amb excess abans de reparar
3. excess abans/despres per recurs+jornada
4. graf de conflictes entre components inicials
5. blocs de reparacio per mida i millora
6. evolucio total_excess per iteracio
```

Si no hi ha temps, generar nomes JSON. Els plots poden venir despres.

## 8. Fitxers nous proposats

MVP minim:

```text
calendaritzacions/engine/variants/resource_solver/conflict_repair.py
calendaritzacions/engine/variants/resource_solver/conflict_repair_service.py
calendaritzacions/tests/test_resource_solver_conflict_repair.py
calendaritzacions/tests/test_resource_solver_conflict_repair_service.py
```

Opcional si els plots es fan d'entrada:

```text
calendaritzacions/reporting/resource_solver_conflict_repair_plots.py
calendaritzacions/tests/test_resource_solver_conflict_repair_plots.py
```

Canvis petits de registre:

```text
calendaritzacions/engine/registry.py
calendaritzacions/django/models.py       # nomes si s'exposa a UI
calendaritzacions/django/forms.py        # nomes si s'exposa a UI
calendaritzacions/django/migrations/...  # nomes si s'exposa a UI
```

## 9. Esquelet de servei

Classe proposada:

```python
class ResourceSolverConflictRepairEngine:
    def run(self, input_path: str, config: Any, progress: Any | None = None) -> EngineResult:
        solver_config = coerce_resource_solver_config(config)
        input_df = read_excel(input_path)
        context = build_context_from_dataframe(input_df, solver_config)

        initial_components = build_initial_components(context)
        initial_partials = solve_initial_components(context, initial_components)
        initial_result = merge_assignments_as_result(context, initial_partials)

        conflict_hubs = detect_conflict_hubs(context, initial_result)
        repair_blocks = build_repair_blocks(context, initial_components, conflict_hubs)
        repaired_partials = solve_repair_blocks(context, initial_result, repair_blocks)

        final_result = merge_initial_and_repaired(context, initial_result, repaired_partials)
        audit_payloads = build_conflict_repair_audits(...)

        write_resource_solver_workbook(...)
        write_audit_payloads(...)

        return EngineResult(...)
```

Per evitar duplicar massa `ResourceSolverEngine.run`, es pot extreure mes
endavant una utilitat compartida per:

```text
pre-analysis
output_dir
write workbook
write final plots
```

Pero per l'MVP es acceptable certa duplicacio del servei si queda encapsulada.

## 10. Tests d'acceptacio

### 10.1. Components inicials no usen recursos

Fixture:

```text
T1: Lliga A, recurs R1
T2: Lliga B, recurs R1
sense linkage
```

Esperat:

```text
2 components inicials
```

El `decomposition.py` actual donaria 1 component per recurs compartit. La nova
variant ha de demostrar la diferencia.

### 10.2. Linkage connecta competicions

Fixture:

```text
T1: Lliga A, linkage L1 casa
T2: Lliga B, linkage L1 fora
```

Esperat:

```text
1 component inicial
```

### 10.3. Merge inicial detecta excess

Fixture:

```text
dos components inicials resolts separadament
mateix recurs temporitzat amb capacitat 1
dos locals en J1
```

Esperat:

```text
1 ConflictHub amb excess=1
```

### 10.4. Bloc de reparacio connecta components conflictius

Fixture:

```text
Hub H1 connecta I001 i I002
Hub H2 connecta I002 i I003
```

Esperat:

```text
1 RepairBlock amb I001, I002, I003
```

### 10.5. Capacitat residual

Fixture:

```text
capacitat original R|J1 = 3
equips congelats fora del bloc consumeixen 2
```

Esperat:

```text
repair_context.capacities["R|J1"].capacity == 1
```

### 10.6. Re-solve respecta capacitat congelada

Fixture petita amb un bloc reparable canviant numeros.

Esperat:

```text
excess_after < excess_before
assignacions finals tenen tots els equips exactament una vegada
```

### 10.7. Fallback si reparacio falla

Injectar `solve_model` que torna `INFEASIBLE` en reparacio.

Esperat:

```text
la solucio final conserva assignacions inicials del bloc
artifact marca repair status failed
run no perd assignacions
```

## 11. Riscos i decisions obertes

### 11.1. Qualitat de solucio

La variant no garanteix optim global. Pot quedar pitjor que el solve global en
qualitat fina, pero ha de ser mes escalable.

Mesura obligatoria:

```text
comparar total_excess inicial/final
comparar linkage violations
comparar entity_excess
comparar wall_time i mida maxima de model
```

### 11.2. Blocs de reparacio massa grans

Si molts hubs conflictius comparteixen competicions, el bloc de reparacio pot
tornar a ser gran.

Per l'MVP:

```text
si repair_block.candidate_count supera un llindar configurable:
  saltar reparacio del bloc
  marcar status="skipped_too_large"
  deixar artifact explicatiu
```

Llindar inicial suggerit:

```text
50_000 candidats
```

### 11.3. Linkage simulat

Els linkages simulats poden connectar massa. Cal auditar:

```text
linkage_source
input vs simulated
```

Si no es pot distingir amb fiabilitat, mantenir comportament conservador:

```text
tots els linkages connecten components
```

### 11.4. Canvis excessius en reparacio

Sense cost de canvi, un bloc reparat pot alterar molt la solucio inicial.

Fase posterior:

```text
afegir constraint/objectiu:
  keep_initial_assignment_bonus
  change_number_penalty
  change_group_penalty
```

No bloquejar l'MVP per aixo.

### 11.5. Capacitat residual negativa

Si els congelats ja excedeixen una capacitat:

```text
remaining_capacity = max(0, original - frozen_usage)
```

El bloc no pot arreglar l'exces causat nomes pels congelats. L'auditoria ha de
mostrar-ho:

```text
frozen_excess
repairable_excess
```

## 12. Ordre d'implementacio recomanat

### Subagent A. Graf inicial i helpers purs

Fitxers:

```text
calendaritzacions/engine/variants/resource_solver/conflict_repair.py
calendaritzacions/tests/test_resource_solver_conflict_repair.py
```

Tasques:

```text
1. InitialComponent dataclass.
2. build_initial_components(context).
3. detect_conflict_hubs(context, result).
4. build_repair_blocks(context, initial_components, hubs).
5. residual capacity helpers.
```

### Subagent B. Servei de variant

Fitxers:

```text
calendaritzacions/engine/variants/resource_solver/conflict_repair_service.py
calendaritzacions/engine/registry.py
calendaritzacions/tests/test_resource_solver_conflict_repair_service.py
```

Tasques:

```text
1. ResourceSolverConflictRepairEngine.run.
2. Solve inicial per component.
3. Merge inicial.
4. Re-solve d'un nivell de repair blocks.
5. EngineResult amb Excel i artifacts.
```

### Subagent C. Auditories i plots

Fitxers:

```text
calendaritzacions/engine/variants/resource_solver/conflict_repair.py
calendaritzacions/reporting/resource_solver_conflict_repair_plots.py
calendaritzacions/tests/test_resource_solver_conflict_repair_plots.py
```

Tasques:

```text
1. JSON artifacts estables.
2. Summary abans/despres.
3. Plots opcionals.
4. Integracio en audit_paths.
```

### Subagent D. Exposicio Django opcional

Fitxers:

```text
calendaritzacions/django/models.py
calendaritzacions/django/forms.py
calendaritzacions/django/migrations/
calendaritzacions/tests/test_django_calendaritzacions_forms.py
```

Tasques:

```text
1. Afegir engine choice.
2. Garantir que process_calendarization el routeja.
3. No canviar defaults.
```

## 13. Criteri de "primera prova acabada"

La primera prova es considera acabada quan:

```text
1. `get_engine("resource_solver_conflict_repair")` retorna el nou engine.
2. Un fixture amb dues competicions que comparteixen recurs es resol en dos
   components inicials.
3. El merge inicial detecta un excess real.
4. Es construeix almenys un RepairBlock.
5. El re-solve del RepairBlock pot reduir excess en un test petit.
6. El workbook final es genera amb el mateix writer que el resource_solver.
7. Els artifacts expliquen components inicials, hubs, blocs i resultat final.
8. El motor actual continua passant els seus tests sense canvis de comportament.
```

## 14. Glossari

```text
component inicial:
  conjunt d'equips resolt a la primera passada, connectat per competicio i
  linkages, pero no per recursos globals.

hub:
  recurs temporitzat `base_resource_id|Jx` amb locals assignats.

conflict hub:
  hub on `locals_count > capacity`.

bloc de reparacio:
  conjunt de components inicials que s'han de reoptimitzar junts perque
  comparteixen conflict hubs o linkages.

capacitat residual:
  capacitat disponible per al bloc de reparacio despres de restar l'us dels
  equips congelats fora del bloc.

equip congelat:
  equip que conserva l'assignacio inicial durant un re-solve de reparacio.
```

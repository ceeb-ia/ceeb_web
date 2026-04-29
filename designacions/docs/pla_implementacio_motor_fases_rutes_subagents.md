# Pla D'Implementacio Del Motor Per Fases, Rutes Incrementals I Repesca Assistida

Data: 2026-04-29

Aquest document descriu un pla d'implementacio per evolucionar el motor de designacions cap a un model per fases esportives, fragments de nivell coherent, rutes candidates generades contra l'estat actual i repesques controlades. Esta escrit perque un agent coordinador pugui repartir la feina entre subagents sense que aquests necessitin context previ de la conversa.

No substitueix immediatament el motor `legacy` ni el `package_solver` existent. La recomanacio es implementar-ho darrere d'un nou flag experimental i fer comparatives abans de posar-ho com a opcio principal.

## Objectiu Funcional

Millorar cobertura i qualitat de designacio en casos complexos:

- modalitats amb pocs partits;
- seus disperses;
- pocs tutors disponibles;
- pocs tutors amb vehicle;
- poca oferta de tutors A/B;
- subgrups inicials massa rigids;
- rutes actuals que es formen abans de saber quin tutor les pot assumir.

El nou motor ha de:

1. Prioritzar esportivament els partits d'alt nivell.
2. Crear fragments de partits coherents per nivell abans de formar rutes.
3. Assignar per fases acumulatives.
4. Generar rutes candidates contra l'estat actual de cada tutor.
5. Evitar duplicats de partit amb restriccions de set packing.
6. Penalitzar suaument la sobrecarrega de tutors ja assignats.
7. Fer repesques parcials conservadores i una repesca final mes completa.
8. Guardar recomanacions de swaps per validacio humana, no aplicar-les automaticament per defecte.
9. Exposar diagnostics i opcions UX prou clares per revisar el resultat.

## Estat Actual Del Codi

Peces ja existents i aprofitables:

- `designacions/optimization/levels.py`
  - ordre de nivells de tutor i partit;
  - `hardest_match_level(...)`;
  - `level_fit(...)`;
  - `level_distance_cost(...)`.

- `designacions/optimization/base_subgroups.py`
  - conversio dels subgrups legacy a objectes purs.

- `designacions/optimization/package_generation.py`
  - genera paquets base, splits i rutes fusionades;
  - ja calcula metadades de nivell en rutes.

- `designacions/optimization/package_scoring.py`
  - construeix candidats `tutor + paquet`;
  - aplica disponibilitat, vehicle, nivell, classificacio i warnings.

- `designacions/optimization/solver.py`
  - selecciona candidats evitant que un partit surti dues vegades;
  - evita mes d'un paquet per tutor i dia en el model actual;
  - te estrategia exacta acotada i greedy per conjunts grans.

- `designacions/main_fixed.py`
  - integra `assignment_engine = "package_solver"`;
  - transforma resultats del solver en assignacions persistibles;
  - conserva el motor legacy.

Limitacio conceptual actual:

- el `package_solver` genera candidats abans de tenir un estat acumulat per fases;
- no recalcula rutes tenint en compte assignacions ja fetes en fases previes;
- no te repesca post-solver implementada;
- no te recomanacions de swaps auditables;
- la UI nomes exposa `legacy` vs `package_solver`.

## Concepte Nou

El motor ha de funcionar per fases:

```text
Fase alta
  tutors A
  partits/rutes amb demanda maxima SENIOR, JUNIOR o JUVENIL

Fase mitjana
  tutors A i B
  partits/rutes restants fins a PREINFANTIL
  tutors ja assignats poden rebre mes partits si encaixa amb la ruta acumulada

Fase general
  tots els tutors
  tots els partits restants

Repesques
  parcials al final de fases critiques
  final global amb insercions i recomanacions de swaps
```

Cada fase resol un problema de seleccio de rutes amb set packing:

```text
variable x[tutor, ruta_extesa] = 1 si es selecciona

restriccions:
  cada partit com a maxim una vegada
  cada tutor pot rebre com a maxim una nova ruta extesa per fase
  la ruta extesa ha de ser compatible amb la ruta acumulada del tutor
  cap assignacio congelada de fases previes es modifica
  disponibilitat, mobilitat i nivell prohibit bloquegen el candidat
```

La restriccio no s'ha d'entendre com "un tutor nomes pot treballar en una fase". Un tutor pot rebre mes partits en fases posteriors si la nova ruta resultant encaixa amb el seu estat acumulat.

## Principi De Solver

No usar Hungarian com a solver principal quan les rutes candidates comparteixen partits.

Motiu:

- Hungarian garanteix una fila/columna en una matriu simple;
- no sap que dues rutes diferents poden contenir el mateix partit;
- per tant no pot garantir per si sol "un sol tutor per partit" si una ruta es una combinacio de partits.

El solver principal ha de ser set packing o equivalent:

- exact search acotat per conjunts petits;
- ILP/CP-SAT si s'accepta dependencia futura;
- greedy determinista amb millores locals per conjunts grans;
- top N pruning abans de resoldre quan hi hagi massa candidats.

Hungarian pot quedar nomes com a eina auxiliar per repesques simples de `tutor + partit individual`, sempre que cada tutor nomes pugui rebre un d'aquests partits en aquella passada.

## Arquitectura Proposada

Nous fitxers recomanats:

```text
designacions/optimization/level_fragments.py
designacions/optimization/state.py
designacions/optimization/phases.py
designacions/optimization/route_generation.py
designacions/optimization/phase_solver.py
designacions/optimization/phase_runner.py
designacions/optimization/rescue.py
designacions/optimization/recommendations.py
designacions/optimization/diagnostics.py
```

Fitxers existents a ampliar:

```text
designacions/optimization/contracts.py
designacions/optimization/package_scoring.py
designacions/optimization/solver.py
designacions/main_fixed.py
designacions/views.py
designacions/templates/upload.html
designacions/templates/cluster_preview_partial.html
designacions/templates/run_detail.html
designacions/templates/assignments.html
designacions/tests.py
```

Evitar que diversos subagents editin `main_fixed.py`, `views.py` o templates alhora. Aquests fitxers s'han de reservar per fases d'integracio.

## Contractes Nous

Afegir dataclasses pures o ampliar `contracts.py`.

### `LevelFragment`

Representa una unitat inicial coherent per nivell.

```python
LevelFragment(
    id: str,
    source_subgroup_id: str,
    match_ids: list[str],
    rows: list[Any],
    date: date | str | None,
    modality: str,
    start_dt: datetime | None,
    end_dt: datetime | None,
    venues: list[str],
    cluster_ids: list[str | None],
    cluster_statuses: list[str | None],
    level_demand: Any,
    max_level_span: int,
    classification_importance: float,
    weighted_coverage_value: float,
)
```

### `TutorRouteState`

Estat acumulat d'un tutor durant el run.

```python
TutorRouteState(
    tutor_id: str,
    date: str,
    assigned_match_ids: list[str],
    assigned_segments: list[Any],
    descriptors: list[MatchDescriptor],
    route_start_dt: datetime | None,
    route_end_dt: datetime | None,
    match_count: int,
    route_count: int,
    has_high_level_assignment: bool,
    warnings: list[str],
)
```

### `DesignationState`

Estat global acumulat.

```python
DesignationState(
    assigned_match_ids: set[str],
    assignments_by_tutor_day: dict[tuple[str, str], TutorRouteState],
    frozen_assignments: list[Any],
    pending_match_ids: set[str],
    diagnostics: dict[str, Any],
)
```

### `PhaseSpec`

Configura una fase.

```python
PhaseSpec(
    name: str,
    tutor_levels: list[str],
    allowed_max_level_position: int | None,
    allowed_level_labels: list[str],
    allow_exceptional: bool,
    rescue_after_phase: bool,
    max_route_size: int,
    top_n_routes_per_tutor: int,
)
```

### `RouteCandidate`

Ruta candidata calculada contra l'estat actual.

```python
RouteCandidate(
    id: str,
    phase_name: str,
    tutor_id: str,
    new_match_ids: list[str],
    full_route_match_ids: list[str],
    inserted_into_existing_route: bool,
    date: str,
    start_dt: datetime | None,
    end_dt: datetime | None,
    level_demand: Any,
    level_fit: str,
    requires_vehicle: bool,
    warning_codes: list[str],
    blocking_reasons: list[str],
    cost: float,
    score_breakdown: dict[str, Any],
)
```

### `SwapRecommendation`

Proposta auditable, no aplicada automaticament.

```python
SwapRecommendation(
    id: str,
    type: str,
    gain: int,
    moves: list[dict[str, Any]],
    freed_resource: dict[str, Any],
    warnings: list[str],
    blocking_risks: list[str],
    score_delta: dict[str, Any],
    explanation: str,
)
```

## Parametres De Configuracio

Nous parametres interns amb defaults recomanats:

```text
assignment_engine = "phased_route_solver"

level_fragment_max_size = 2
level_fragment_max_span = 3

phase_high_levels = SENIOR,JUNIOR,JUVENIL
phase_medium_max_level = PREINFANTIL

route_max_new_matches_per_phase = 2
route_top_n_per_tutor = 20
route_top_n_per_match = 8

load_penalty_per_assigned_match = 60
load_penalty_per_existing_route = 30
underused_tutor_bonus = 50
high_level_easy_route_penalty = 150

partial_rescue_top_n_tutors = 5
final_rescue_top_n_tutors = 8
allow_swap_recommendations = true
auto_apply_swaps = false

set_packing_exact_candidate_limit = 28
```

Jerarquia de costos:

```text
1. nivell forbidden, disponibilitat impossible i mobilitat impossible bloquegen
2. cobertura i cobertura de nivell alt manen
3. exceptional es penalitza abans de mirar costos fins
4. mobilitat i vehicle decideixen entre candidats esportivament validos
5. classificacio ordena dins candidats validos
6. carrega acumulada reparteix quan les opcions son semblants
7. warnings i desempats tanquen la decisio
```

## Penalitzacio De Carrega Acumulada

Objectiu:

- evitar que tutors A/B acumulin molts partits mentre tutors C/D queden sense res;
- afavorir varietat quan hi ha alternatives igualment viables;
- no sacrificar cobertura ni nivell.

Formula inicial:

```text
load_penalty =
  assigned_match_count_for_tutor * load_penalty_per_assigned_match
+ existing_route_count_for_tutor * load_penalty_per_existing_route
+ high_level_easy_route_penalty si tutor A/B rep ruta facil i hi ha tutors C/D viables
- underused_tutor_bonus si el tutor encara no te cap partit
```

Regles:

- no aplicar bonus d'infrautilitzat si el nivell es `forbidden`;
- no aplicar bonus si la mobilitat es inviable;
- no permetre que el bonus superi una diferencia esportiva important;
- registrar `load_penalty` i `underused_bonus` al `score_breakdown`.

## Fragmentacio Per Nivell

Responsable: `level_fragments.py`.

Entrada:

- `BaseSubgroup` o equivalent amb `rows`.

Sortida:

- llista de `LevelFragment`.

Regles:

1. Ordenar partits per hora.
2. Mirar posicions dins `MATCH_LEVEL_ORDER`.
3. Crear fragments de maxim `level_fragment_max_size` partits.
4. La diferencia maxima dins fragment ha de ser `level_fragment_max_span`.
5. Si no es compleix, separar fins que es compleixi.
6. El `level_demand` del fragment sempre es `hardest_match_level(...)`.

Exemple:

```text
SENIOR + INFANTIL + ALEVI
=>
SENIOR
INFANTIL + ALEVI
```

Diagnostics:

- `level_fragment_count`;
- `fragmented_subgroup_count`;
- `max_observed_level_span`;
- exemples de fragments creats per excés de discrepancia.

## Generacio De Rutes Per Fase

Responsable: `route_generation.py`.

La generacio no ha de crear rutes en abstracte. Ha de crear rutes per:

```text
tutor + fase + estat acumulat + fragments pendents
```

Tipus de candidats:

1. Ruta nova amb 1 fragment.
2. Ruta nova amb 2 fragments compatibles.
3. Insercio d'1 fragment en ruta ja existent del tutor.
4. Insercio de 2 fragments en ruta ja existent si el cost combinatori es assumible.

Restriccions dures:

- partit ja assignat: no entra;
- tutor fora de fase per nivell: no entra;
- disponibilitat no cobreix ruta completa: no entra;
- canvi de cluster sense vehicle: no entra en mode estricte;
- `level_fit = forbidden`: no entra;
- gap insuficient: no entra.

Restriccions suaus:

- warnings de mobilitat;
- outlier o cluster desconegut;
- vehicle gastat en ruta facil;
- carrega acumulada del tutor;
- classificacio exigent amb tutor mes fluix dins candidats validos.

Pruning recomanat:

- generar totes les combinacions simples viables;
- calcular score;
- conservar top N per tutor;
- conservar top N per partit;
- conservar sempre algun candidat per partit si existeix;
- limitar rutes cross-cluster segons pressio de vehicle.

## Solver Per Fase

Responsable: `phase_solver.py`.

Entrada:

- `PhaseSpec`;
- `DesignationState`;
- `RouteCandidate[]`.

Sortida:

- rutes seleccionades;
- partits pendents de la fase;
- diagnostics del solver.

Restriccions:

```text
per cada partit pendent:
  suma candidates que contenen partit <= 1

per cada tutor i dia:
  suma candidates noves seleccionades <= 1

per cada candidat:
  si blocking_reasons no buit, no seleccionable
```

Objectiu lexicografic:

```text
1. maximitzar cobertura ponderada de partits de la fase
2. maximitzar cobertura de nivell alt
3. minimitzar assignacions exceptional
4. maximitzar nombre de partits coberts
5. minimitzar sobrecarrega de tutors
6. minimitzar cost de mobilitat/vehicle
7. minimitzar warnings
8. minimitzar cost total
```

Implementacio inicial:

- reutilitzar parts de `solver.py`;
- afegir `phase_name`, `route_candidate_id`, `full_route_match_ids`;
- exact search per conjunts petits;
- greedy multi-pass per conjunts grans;
- comparar diverses ordenacions i quedar-se amb millor `solution_key`.

## Orquestracio De Fases

Responsable: `phase_runner.py`.

Flux:

```text
1. construir BaseSubgroup des dels subgrups legacy
2. crear LevelFragment
3. inicialitzar DesignationState
4. per cada PhaseSpec:
   a. filtrar fragments pendents de la fase
   b. filtrar tutors elegibles de la fase
   c. generar RouteCandidate contra estat actual
   d. resoldre set packing de fase
   e. congelar assignacions seleccionades
   f. actualitzar DesignationState
   g. executar repesca parcial si toca
5. executar repesca final
6. generar recomanacions de swaps
7. retornar assignacions finals i diagnostics
```

El runner ha de ser Django-free fins on sigui possible. `main_fixed.py` nomes hauria d'adaptar dataframes a contractes i transformar resultats a persistencia.

## Repesques Parcials

Responsable: `rescue.py`.

Quan executar:

- despres de fase alta;
- opcionalment despres de fase mitjana;
- no cal despres de fase general, perque ja ve la repesca final.

Objectiu:

- recuperar pendents critics de la fase sense comprometre fases posteriors.

Regles:

- nomes partits individuals o fragments molt petits;
- no tocar assignacions ja congelades;
- no permetre `level_forbidden`;
- `exceptional` nomes si `allow_exceptional_routes` o perfil ho permet;
- top N tutors per partit;
- set packing petit, no greedy pur si hi ha mes d'un pendent.

Flux:

```text
1. prendre pendents de la fase
2. calcular top N tutors compatibles per cada partit
3. crear candidats d'insercio en ruta acumulada
4. crear candidats de ruta nova si tutor encara esta lliure o poc carregat
5. resoldre set packing
6. congelar assignacions noves
7. registrar que venen de `partial_rescue:<phase>`
```

Diagnostics:

- `partial_rescue_attempted_match_count`;
- `partial_rescue_recovered_match_count`;
- `partial_rescue_blocking_reasons`;
- exemples de partits no recuperables.

## Repesca Final

Responsable: `rescue.py`.

La repesca final pot ser mes ambiciosa, pero ha de continuar sent segura.

Passades:

```text
A. Insercio directa
   afegir un partit pendent a una ruta existent si encaixa completament

B. Ruta nova
   tutor lliure o infrautilitzat cobreix 1-2 pendents compatibles

C. Relaxacio controlada
   permetre exceptional o outlier amb warning segons perfil
   mai level_forbidden
   mai disponibilitat impossible

D. Recomanacions de swap
   no aplicar automaticament
   guardar propostes auditables
```

La repesca final ha de maximitzar cobertura sense generar errors durs. Si cal empitjorar una assignacio existent, no s'aplica: es guarda com a recomanacio.

## Ampliacio Recomanada De Repesca Final

Data: 2026-04-29

Despres de provar el primer `phased_route_solver` amb el run 136, s'ha detectat un cas clar: queden molts tutors `NIVELLD1` sense assignar tot i existir moltes parelles manualment viables entre aquests tutors i partits pendents. El problema no es principalment de nivell ni disponibilitat, sino de generacio i seleccio de candidats: la repesca actual encara depen massa de rutes candidates generades amb poda, i no esgota una capa simple de `partit pendent x tutor viable`.

Per corregir-ho sense fer swaps automatics, cal afegir dues capes finals de repesca despres de la repesca final existent.

### Nova Repesca Final 1: Rutes Noves Amb Pendents

Objectiu:

- crear rutes 100% noves nomes amb partits no assignats;
- no inserir en rutes existents;
- no dependre de les rutes candidates generades en fases anteriors;
- aprofitar tutors lliures o poc usats que poden cobrir 2 partits pendents compatibles.

Entrada:

```text
pending_fragments
tutors
DesignationState actual
config
```

Regles:

```text
1. Considerar nomes fragments/partits no assignats.
2. Generar rutes noves d'1 o 2 fragments pendents.
3. Permetre 3 fragments nomes si:
   - mateixa pista o mateixa seu;
   - mateixa data;
   - gaps clarament suficients;
   - config `rescue_new_routes_max_size >= 3`.
4. No inserir aquestes rutes dins una ruta ja assignada.
5. Validar disponibilitat completa del tutor per la nova ruta.
6. Validar que la nova ruta no entra en conflicte amb la ruta acumulada del tutor.
7. Validar nivell:
   - `level_forbidden` no entra;
   - `exceptional` nomes si el perfil ho permet.
8. Validar mobilitat:
   - cross-cluster sense vehicle no entra;
   - gap insuficient no entra;
   - outlier/missing cluster pot entrar nomes segons perfil i amb warning.
```

Solver:

```text
set packing:
  cada partit <= 1 vegada
  cada tutor-dia <= 1 nova ruta en aquesta passada
```

Objectiu:

```text
1. maximitzar partits recuperats
2. preferir tutors sense assignacio
3. preferir rutes de 2 partits davant 1 si son igualment viables
4. minimitzar exceptional
5. minimitzar mobilitat/warnings
6. minimitzar cost
```

Parametres recomanats:

```text
rescue_new_routes_enabled = true
rescue_new_routes_max_size = 2
rescue_new_routes_same_venue_max_size = 3
rescue_new_routes_top_n_per_tutor = 30
rescue_new_routes_top_n_per_match = 10
```

Diagnostics:

```text
new_route_rescue_attempted_match_count
new_route_rescue_candidate_count
new_route_rescue_selected_route_count
new_route_rescue_recovered_match_count
new_route_rescue_unrecovered_match_ids
new_route_rescue_blocking_reason_counts
```

### Nova Repesca Final 2: Individual Top N Iterativa

Objectiu:

- esgotar possibilitats simples despres de totes les rutes;
- assignar partits pendents individuals a tutors viables;
- no tocar assignacions existents;
- evitar que quedin tutors D/C lliures mentre hi ha partits baixos clarament assignables.

Funcionament:

```text
while hi ha pendents i hi ha progrés:
  1. Per cada partit pendent individual:
       calcular top N tutors viables contra estat actual.
  2. Construir candidats `tutor + partit`.
  3. Resoldre matching/set packing simple.
  4. Aplicar assignacions seleccionades.
  5. Actualitzar estat.
  6. Repetir fins que no es recuperi cap partit o s'arribi al limit.
```

Primera iteracio recomanada:

- considerar primer tutors sense cap assignacio;
- si encara queden pendents, considerar tutors ja assignats nomes si el partit individual encaixa sense moure res;
- no fer swaps;
- no generar rutes de mes d'un partit en aquesta capa.

Restriccions dures:

```text
level_forbidden => prohibit
fora disponibilitat => prohibit
gap amb ruta acumulada insuficient => prohibit
cross-cluster sense vehicle => prohibit
partit ja assignat => prohibit
```

Restriccions suaus:

```text
exceptional => penalitzacio alta o prohibit segons perfil
outlier/missing cluster => warning o prohibit segons perfil
tutor ja carregat => penalitzacio de carrega
```

Parametres recomanats:

```text
individual_rescue_enabled = true
individual_rescue_top_n_tutors = 8
individual_rescue_max_iterations = 5
individual_rescue_max_total_assignments = null
individual_rescue_include_assigned_tutors_after_iteration = 1
individual_rescue_require_progress = true
```

### Proteccio Contra Bucle Infinit

La repesca individual iterativa ha de tenir garanties explicites de terminacio.

Condicions de parada obligatories:

```text
1. Si una iteracio recupera 0 partits, parar.
2. Si no disminueix el conjunt de pending_match_ids, parar.
3. Si `iteration >= individual_rescue_max_iterations`, parar.
4. Si no queden candidats viables, parar.
5. Si el nombre de pendents actual es igual al de la iteracio anterior i no hi ha assignacions noves, parar.
```

Registre recomanat per iteracio:

```python
iteration_summary = {
    "iteration": iteration,
    "pending_before": len(pending_before),
    "candidate_count": candidate_count,
    "selected_count": selected_count,
    "recovered_match_count": recovered_count,
    "pending_after": len(pending_after),
    "stopped_reason": stopped_reason,
}
```

`stopped_reason` pot ser:

```text
no_pending_matches
no_viable_candidates
no_progress
max_iterations_reached
max_total_assignments_reached
```

Invariant que s'ha de comprovar en tests:

```text
pending_after < pending_before
```

sempre que `recovered_match_count > 0`.

Si aquesta invariant no es compleix, la funcio ha de parar i registrar `stopped_reason = "no_progress"`.

### Ordre Final De Repesques Recomanat

Ordre complet despres de les fases:

```text
1. Repesca parcial alta, conservadora.
2. Repesca parcial mitjana, opcional.
3. Repesca final existent amb rutes/insercions contra estat.
4. Repesca final extra: rutes noves nomes amb pendents.
5. Repesca final extra: individual top N iterativa.
6. Recomanacions de swaps, no aplicades.
```

Motiu:

- primer s'intenta mantenir coherencia de ruta;
- despres es creen rutes noves per pendents que havien quedat fora de la poda anterior;
- finalment s'esgota el cas simple `partit individual + tutor viable`;
- nomes al final es proposen swaps humans.

### Tests Necessaris Per Aquesta Ampliacio

Afegir tests purs:

1. `new_route_rescue` recupera dos pendents amb un D1 lliure quan son compatibles.
2. `new_route_rescue` no usa un partit ja assignat.
3. `individual_rescue` recupera un pendent amb un D1 lliure encara que el generador de rutes previ no l'hagi seleccionat.
4. `individual_rescue` para quan una iteracio no recupera cap partit.
5. `individual_rescue` respecta `individual_rescue_max_iterations`.
6. `individual_rescue` no genera duplicats de partit.
7. `individual_rescue` no assigna `level_forbidden`.
8. `individual_rescue` no toca assignacions existents.
9. Cas tipus run 136 sintetic: diversos D1 lliures i partits baixos pendents; la repesca individual augmenta cobertura.

### Criteri D'Acceptacio De La Millora

Amb un run tipus 136:

- el nombre de pendents ha de baixar respecte la primera versio del `phased_route_solver`;
- els tutors D1 lliures han de reduir-se si hi ha partits pendents viables;
- no s'han d'introduir `level_forbidden`;
- no s'han d'introduir errors durs de mobilitat/disponibilitat;
- les assignacions recuperades han de quedar marcades amb stage:
  - `new_route_rescue`
  - `individual_rescue:<iteration>`

## Recomanacions De Swaps

Responsable: `recommendations.py`.

Principi:

- qualsevol canvi que mogui o desassigni una assignacio ja feta es recomanacio, no accio automatica.

Tipus inicials:

### `one_swap_to_recover_pending`

Exemple:

```text
Moure partit X de Tutor A a Tutor C
Alliberar Tutor A
Assignar pendent Y a Tutor A
Guany net: +1 partit assignat
```

### `vehicle_release`

Exemple:

```text
Moure una ruta facil d'un tutor amb vehicle a un tutor sense vehicle
Usar tutor amb vehicle per pendent cross-cluster
```

### `level_release`

Exemple:

```text
Moure partit baix d'un tutor A/B a un tutor C/D
Usar tutor A/B per pendent de nivell mes alt
```

Restriccions:

- no proposar moviments amb `level_forbidden`;
- no proposar moviments fora de disponibilitat;
- no proposar moviments amb error dur de mobilitat;
- mostrar warnings informatius si existeixen.

Persistencia inicial:

- guardar dins `result_summary["swap_recommendations"]`;
- no crear model DB nou en la primera iteracio, llevat que la UI necessiti acceptar/rebutjar de forma persistent.

Payload recomanat:

```json
{
  "id": "swap:1",
  "type": "vehicle_release",
  "gain": 1,
  "moves": [
    {"match_id": "X", "from_tutor_id": "A", "to_tutor_id": "C"},
    {"match_id": "Y", "from_tutor_id": null, "to_tutor_id": "A"}
  ],
  "warnings": ["cross_cluster_with_vehicle_warning"],
  "score_delta": {
    "covered_matches": 1,
    "level_exceptional_delta": 0,
    "warning_delta": 1
  },
  "explanation": "Allibera un tutor amb vehicle per cobrir un pendent entre clusters."
}
```

## Diagnostics I Observabilitat

Responsable: `diagnostics.py` i integracio a `main_fixed.py`.

Afegir al `result_summary`:

```text
engine_name
phase_solver_summary
level_fragment_summary
phase_summaries
partial_rescue_summary
final_rescue_summary
swap_recommendations
load_distribution_summary
coverage_by_level
coverage_by_phase
coverage_by_hour
coverage_by_cluster
vehicle_usage_summary
selected_by_level_fit
unassigned_by_reason
```

`phase_summaries` hauria d'incloure:

```text
phase_name
eligible_tutor_count
pending_fragment_count_before
route_candidate_count
viable_route_candidate_count
selected_route_count
selected_match_count
pending_match_count_after
selected_by_level_fit
load_penalty_total
blocking_reason_counts
```

`load_distribution_summary`:

```text
assigned_matches_by_tutor_level
assigned_matches_by_tutor
unused_tutors_by_level
overloaded_tutors
underused_viable_tutors
```

## Integracio Backend

Responsable: subagent d'integracio backend.

Canvis:

1. Afegir `assignment_engine = "phased_route_solver"` com a valor acceptat.
2. Mantenir `legacy` per defecte fins a validacio real.
3. Integrar el nou runner dins el bucle per modalitat de `main_fixed.py`.
4. Reutilitzar persistencia actual de `Assignment`.
5. Afegir `stage` o diagnostics per saber si una assignacio ve de:
   - `phase:high`;
   - `partial_rescue:high`;
   - `phase:medium`;
   - `phase:general`;
   - `final_rescue`.
6. No aplicar recomanacions de swap automaticament.
7. Guardar recomanacions a `result_summary`.

Risc:

- `main_fixed.py` ja es gran. Evitar posar logica nova dins aquest fitxer. Ha de quedar com a orquestrador prim.

## UI I UX

Responsable: subagent UI/UX.

### Formulari D'Upload

Substituir el checkbox simple per selector:

```text
Motor d'assignacio:
  - Legacy estable
  - Package solver experimental
  - Motor per fases i rutes experimental
```

Afegir perfil:

```text
Perfil del motor:
  - Estricte
  - Equilibrat
  - Maxima cobertura
```

Paràmetres visibles recomanats:

- temps mateixa pista;
- temps canvi de pista;
- temps canvi de cluster;
- fragmentacio per nivell activada;
- maxima discrepancia de nivell en fragment;
- maxim partits per fragment;
- permetre exceptional en repesca;
- generar recomanacions de millora.

Paràmetres avançats o ocults:

- top N intern;
- exact solver candidate limit;
- pesos numerics detallats;
- route candidate budgets.

### Preview

El preview hauria de mostrar:

- estimacio de fragments per nivell;
- pressio per nivell;
- pressio de vehicle;
- colls d'ampolla per hora;
- tutors A/B disponibles per franja;
- avis si hi ha pocs tutors A per partits alts.

### Run Detail

Afegir bloc de resum:

- cobertura global;
- cobertura per fase;
- cobertura per nivell;
- tutors sobrecarregats;
- tutors viables sense assignacio;
- recomanacions de swap pendents de revisar.

### Assignments Page

Afegir columna o badge:

- origen: fase alta, fase mitjana, fase general, repesca;
- `level_fit`;
- warnings de mobilitat;
- si forma part d'una recomanacio.

Afegir seccio "Recomanacions":

```text
Proposta 1: guany +1 partit
Moviments:
  X: Tutor A -> Tutor C
  Y: Sense tutor -> Tutor A
Avisos:
  canvi de cluster amb vehicle
Accions:
  Revisar
  Aplicar
  Ignorar
```

Primera iteracio UX:

- mostrar recomanacions;
- no cal implementar botó "Aplicar" si complica massa;
- si s'implementa "Aplicar", ha de reutilitzar validacions manuals existents.

## Pla Per Subagents

### Subagent 1: Contractes I Estat

Fitxers:

- `designacions/optimization/contracts.py`
- `designacions/optimization/state.py`

Objectiu:

- afegir dataclasses noves;
- helpers per actualitzar estat;
- helpers per obtenir ruta acumulada per tutor-dia;
- tests unitaris purs.

No tocar:

- `main_fixed.py`;
- templates.

### Subagent 2: Fragmentacio Per Nivell

Fitxers:

- `designacions/optimization/level_fragments.py`
- `designacions/tests.py`

Objectiu:

- implementar fragmentacio max 2 partits;
- max span 3 dins `MATCH_LEVEL_ORDER`;
- conservar `hardest_match_level`;
- conservar classificacio i metadades.

Tests:

- `SENIOR + INFANTIL + ALEVI => SENIOR / INFANTIL+ALEVI`;
- fragment amb categories desconegudes no peta;
- `level_demand` sempre es el mes exigent.

### Subagent 3: Scoring Amb Estat I Carrega

Fitxers:

- `designacions/optimization/package_scoring.py` o nou `route_scoring.py`
- `designacions/tests.py`

Objectiu:

- afegir cost de carrega acumulada;
- bonus de tutor infrautilitzat;
- penalitzacio per usar A/B en ruta facil amb alternatives C/D;
- score breakdown auditable.

Tests:

- amb dos tutors iguals, prefereix qui te menys carrega;
- no prefereix un tutor infrautilitzat si el nivell es forbidden;
- la penalitzacio de carrega no supera una incompatibilitat dura.

### Subagent 4: Generacio De Rutes Per Fase

Fitxers:

- `designacions/optimization/route_generation.py`
- `designacions/tests.py`

Objectiu:

- generar candidats per tutor contra `DesignationState`;
- suportar ruta nova i insercio en ruta existent;
- validar gaps, vehicle, disponibilitat i nivell;
- pruning top N.

Tests:

- no genera ruta amb partit ja assignat;
- genera insercio si encaixa entre partits existents;
- bloqueja cross-cluster sense vehicle;
- permet cross-cluster amb vehicle i warning si gap suficient.

### Subagent 5: Solver Per Fase

Fitxers:

- `designacions/optimization/phase_solver.py`
- `designacions/optimization/solver.py` si es reutilitza logica
- `designacions/tests.py`

Objectiu:

- seleccionar rutes evitant duplicats de partit;
- limitar una ruta nova per tutor-dia i fase;
- objectiu lexicografic;
- exact search acotat i greedy fallback.

Tests:

- dues rutes comparteixen partit: nomes se'n tria una;
- tutor amb ruta acumulada pot rebre una ruta extesa compatible;
- exceptional perd contra acceptable si cobertura igual;
- mes cobertura guanya si no introdueix forbidden.

### Subagent 6: Runner De Fases

Fitxers:

- `designacions/optimization/phases.py`
- `designacions/optimization/phase_runner.py`
- `designacions/tests.py`

Objectiu:

- definir fases alta, mitjana i general;
- executar flux complet sense Django;
- actualitzar `DesignationState`;
- produir assignacions candidates finals i diagnostics.

Tests:

- fase alta nomes usa tutors A;
- fase mitjana pot afegir partits a tutors A ja assignats si encaixa;
- partits assignats en fase alta no es dupliquen;
- tutors C no entren abans de fase general.

### Subagent 7: Repesques

Fitxers:

- `designacions/optimization/rescue.py`
- `designacions/tests.py`

Objectiu:

- repesca parcial conservadora;
- repesca final amb insercio directa i ruta nova;
- no tocar assignacions congelades;
- no aplicar swaps.

Tests:

- recupera pendent individual si hi ha tutor viable;
- no recupera si nomes hi ha forbidden;
- no modifica assignacions existents;
- repesca final pot usar tutor infrautilitzat.

### Subagent 8: Recomanacions De Swaps

Fitxers:

- `designacions/optimization/recommendations.py`
- `designacions/tests.py`

Objectiu:

- generar recomanacions `one_swap_to_recover_pending`;
- generar recomanacions `vehicle_release`;
- generar recomanacions `level_release`;
- payload auditable.

Tests:

- proposta amb guany +1 es detecta;
- no proposa moviment inviable;
- no proposa level_forbidden;
- recomanacio no canvia l'estat.

### Subagent 9: Diagnostics

Fitxers:

- `designacions/optimization/diagnostics.py`
- `designacions/tests.py`

Objectiu:

- construir `phase_solver_summary`;
- cobertura per nivell/fase/hora/cluster;
- distribucio de carrega;
- resum de recomanacions.

Tests:

- recomptes coherents;
- tutors sense assignar per nivell;
- selected_by_level_fit correcte.

### Subagent 10: Integracio Backend

Fitxers:

- `designacions/main_fixed.py`
- `designacions/views.py`
- possibles tests d'integracio.

Objectiu:

- afegir `phased_route_solver`;
- connectar runner;
- persistir assignacions;
- guardar diagnostics;
- mantenir legacy i package_solver intactes.

Regla:

- aquest subagent s'ha d'executar despres dels subagents 1-9 o quan els contractes estiguin estables.

### Subagent 11: UI/UX

Fitxers:

- `designacions/templates/upload.html`
- `designacions/templates/cluster_preview_partial.html`
- `designacions/templates/run_detail.html`
- `designacions/templates/assignments.html`
- `designacions/views.py` si cal exposar context.

Objectiu:

- selector de motor;
- perfil de motor;
- diagnostics per fase;
- recomanacions visibles.

Regla:

- no dependre d'un model DB nou en primera iteracio;
- llegir de `result_summary`.

## Ordre Recomanat D'Execucio

### Bloc A: Paralelitzable

Poden anar en paralel:

- Subagent 1: Contractes i estat.
- Subagent 2: Fragmentacio per nivell.
- Subagent 3: Scoring amb carrega.
- Subagent 5: Solver per fase, si usa contractes provisionals.
- Subagent 9: Diagnostics, amb payload acordat.

### Bloc B: Depen De Contractes

Despres del Bloc A:

- Subagent 4: Generacio de rutes per fase.
- Subagent 6: Runner de fases.

### Bloc C: Depen Del Runner

Despres del Bloc B:

- Subagent 7: Repesques.
- Subagent 8: Recomanacions de swaps.

### Bloc D: Integracio

Ultim:

- Subagent 10: Backend.
- Subagent 11: UI/UX.

## Estrategia De Tests

Tests purs:

- `levels.py`;
- `level_fragments.py`;
- `state.py`;
- `route_generation.py`;
- `phase_solver.py`;
- `rescue.py`;
- `recommendations.py`;
- `diagnostics.py`.

Tests d'integracio:

- run sintetic amb `SENIOR`, `INFANTIL`, `ALEVI`;
- run amb pocs tutors A i molts C;
- run amb tutor A ja carregat i tutor C lliure per partit facil;
- run amb cross-cluster i nomes un tutor amb vehicle;
- run amb pendent recuperable per insercio final;
- run amb swap recomanat pero no aplicat.

Comparatives reals:

- repetir runs historics 96/97/132/133/134 si estan disponibles;
- comparar `legacy`, `package_solver`, `phased_route_solver`;
- revisar:
  - cobertura total;
  - cobertura de nivells alts;
  - `level_exceptional_selected_count`;
  - pendents per disponibilitat;
  - pendents per vehicle;
  - distribucio de carrega per tutor;
  - warnings de mobilitat.

Comandes de validacio previstes:

```text
python -m compileall designacions/optimization designacions/main_fixed.py designacions/views.py
python manage.py test designacions.tests.DesignacionsOptimizationPackageSolverTests
python manage.py test designacions.tests
```

Adaptar a Docker si l'entorn ho requereix.

## Criteris D'Acceptacio

Funcional:

- cap partit assignat a dos tutors;
- cap tutor fora de disponibilitat;
- cap `level_forbidden` seleccionat;
- fases respecten tutors elegibles;
- tutors ja assignats poden rebre mes partits nomes si la ruta acumulada es viable;
- repesques no modifiquen assignacions congelades;
- swaps nomes es guarden com a recomanacio.

Qualitat:

- cobertura igual o millor que `package_solver` en casos tensos, o explicacio clara si baixa per criteri esportiu;
- menys casos de tutors A sobrecarregats quan hi ha alternatives viables;
- diagnostics suficients per entendre per que queda pendent un partit;
- UI mostra fase/origen i recomanacions sense ocultar warnings.

Regressio:

- `legacy` continua funcionant igual;
- `package_solver` continua disponible;
- el nou motor nomes s'activa amb `assignment_engine = "phased_route_solver"`.

## Riscos I Decisions Pendents

### Risc 1: Combinatoria

Mitigacio:

- top N per tutor;
- top N per partit;
- maxim 2 nous fragments per ruta en primera versio;
- exact solver acotat i greedy fallback.

### Risc 2: Massa Penalitzacio De Carrega

Mitigacio:

- pesos baixos inicials;
- diagnostics de `load_penalty`;
- comparar cobertura amb i sense penalitzacio.

### Risc 3: Fases Massa Rigides

Mitigacio:

- repesca parcial;
- repesca final;
- recomanacions de swaps;
- no aplicar swaps automaticament.

### Risc 4: UI Massa Complexa

Mitigacio:

- mostrar perfil simple a usuaris normals;
- deixar pesos en configuracio interna;
- recomanacions amb explicacio curta i guany net.

### Decisions Pendents

1. El nou motor ha de quedar ocult darrere feature flag intern o visible a upload com experimental?
2. Es permet `exceptional` en fase alta si no hi ha cap A disponible?
3. Els outliers poden ser assignables amb warning en perfil maxima cobertura?
4. Cal crear model DB per recomanacions o n'hi ha prou amb `result_summary` inicialment?
5. Quan una recomanacio s'aplica manualment, s'ha de marcar com acceptada/rebutjada?

## Definicio De Primera Versio Recomanada

Per reduir risc, la primera versio hauria de limitar-se a:

1. Fragments per nivell.
2. Tres fases fixes.
3. Rutes de maxim 2 fragments nous.
4. Insercio simple en ruta existent.
5. Penalitzacio suau de carrega.
6. Repesca parcial alta i final.
7. Recomanacions de swap nomes calculades i mostrades.
8. Sense aplicar swaps automaticament.
9. Sense dependencia externa d'ILP.

Un cop validat, es pot evolucionar cap a:

- rutes de mes de 2 fragments;
- ILP/CP-SAT;
- aplicacio assistida de recomanacions;
- perfils de relaxacio mes sofisticats;
- outliers virtuals integrats amb el preview de clusters.

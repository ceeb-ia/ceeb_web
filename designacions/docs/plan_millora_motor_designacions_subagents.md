# Pla De Millora Del Motor De Designacions Per Casos Amb Seus Disperses I Pocs Tutors

## Objectiu

Aquest document descriu la problematica detectada en el motor de designacions quan hi ha moltes seus disperses, pocs tutors disponibles, pocs tutors amb vehicle o modalitats amb baixa densitat de partits. L'objectiu es donar context suficient a un subagent extern per estudiar i implementar millores sense necessitar context previ de la conversa.

No es proposa tocar la clusteritzacio com a unic mecanisme de millora. La clusteritzacio ajuda a validar mobilitat, pero el run 96 mostra que la incidencia alta tambe ve de com s'usen els tutors disponibles i de com s'optimitza la cobertura global.

## Context Funcional

El modul `designacions` assigna tutors de joc a partits. El motor principal esta a:

- `designacions/main_fixed.py`
- Entrada principal: `main(...)`
- Persistencia a BD: `persist_assignacions_to_db(...)`
- Diagnosi de viabilitat/mobilitat: `designacions/services/assignment_feasibility.py`
- Diagnosi manual i avisos: `designacions/services/manual_assignment.py`
- Models principals: `DesignationRun`, `Match`, `Availability`, `Assignment`, `AddressCluster` a `designacions/models.py`

El flux actual, simplificat, es:

1. Llegeix fitxers de partits i disponibilitats.
2. Filtra per modalitat, dates i fase.
3. Geocodifica adreces i calcula clusters geografics.
4. Construeix subgrups de partits per dia i pista.
5. Fusiona subgrups si son compatibles en temps i cluster.
6. Assigna tutors a subgrups amb Hungarian (`linear_sum_assignment`).
7. Fa una repesca segmentant subgrups fallits.
8. Desa assignacions, mapa i resum d'incidencies.

## Diagnosi Del Run 96

Run analitzat:

- `DesignationRun.id = 96`
- Nom: `Volei 24/4`
- Estat: `done`
- Modalitat: `VOLEIBOL`
- Partits: 101
- Assignats: 69
- No assignats: 32
- Incidencia aproximada: 31.7%
- Tutors amb disponibilitat: 60
- Tutors sense assignar al final: 4

Parametres rellevants del run:

- `cluster_eps_m = 600`
- `cluster_min_samples = 2`
- `max_partits_subgrup = 3`
- `gap_same_pitch_min = 90`
- `gap_diff_pitch_min = 120`
- `gap_diff_cluster_min = 150`
- `fase = FS2`

Desglossament dels 32 partits no assignats:

- `outside_availability_window`: 16
- `cross_cluster_without_vehicle`: 8
- `outlier_cluster_for_mobility_validation`: 8

Lectura important:

- La incidencia no es nomes un problema de clusteritzacio.
- Hi ha un problema d'optimitzacio global: alguns tutors poden estar sent usats en assignacions facilment cobertes mentre altres partits queden bloquejats per vehicle, finestra horaria o outliers.
- El sistema actual assigna inicialment un subgrup per tutor i nomes despres intenta rescatar. Aixo pot gastar recursos escassos, especialment tutors amb vehicle o tutors amb finestres llargues.

## Limitacions De L'Algorisme Actual

### 1. Optimitzacio Massa Local

L'assignacio inicial resol una matriu tutor-subgrup amb Hungarian. Aixo troba una combinacio barata entre tutors i subgrups, pero no modela be la ruta completa del tutor durant el dia.

Conseqüencia:

- Un tutor amb vehicle pot quedar assignat a un subgrup que tambe podria fer un tutor sense vehicle.
- Despres, quan cal cobrir una transicio entre clusters, ja no queda cap tutor adequat.
- La repesca reutilitza tutors, pero ja parteix d'una solucio inicial que pot haver pres decisions suboptimes.

### 2. Vehicle No Es Tracta Com A Recurs Escas

El motor valida mobilitat, pero no sembla reservar tutors amb vehicle per als casos que realment els necessiten.

En el run 96:

- 42 disponibilitats indiquen `No tinc Vehicle Propi`.
- Només 8 tenen `Cotxe`.
- 6 tenen `Moto`.
- 3 tenen `Bicicleta`.
- 1 te `Patinet electric`.

Si els tutors amb vehicle s'usen massa aviat en partits senzills, apareixen incidencies `cross_cluster_without_vehicle`.

### 3. Outliers Son Bloqueig Dur

Quan una seu queda com a outlier o sense cluster fiable, la validacio de mobilitat no pot decidir amb garanties. Ara aixo pot acabar com:

- `outlier_cluster_for_mobility_validation`
- `missing_cluster_for_mobility_validation`

En modalitats amb poques seus o seus disperses, aixo penalitza molt. L'usuari ara pot corregir clusters al preview, pero encara cal que el motor tingui una estrategia robusta quan queden outliers.

### 4. La Repesca Segmenta Pero No Reoptimitza Globalment

El rescue actual:

- Agafa subgrups fallits.
- Els parteix en segments contigus.
- Torna a provar amb tutors lliures.
- Despres prova reutilitzant tutors.

Pero no desfà assignacions inicials per millorar la cobertura total. Per tant, si una decisio inicial bloqueja 2 partits posteriors, el rescue pot no poder recuperar-los.

### 5. Avisos De Mobilitat Insuficients

Actualment s'avisen alguns conflictes de mobilitat, pero funcionalment interessa que qualsevol canvi de pista quedi avisat per revisio humana, encara que sigui viable.

Nova regla desitjada:

- Si un tutor te partits en mes d'una pista/seu en el mateix dia, s'ha de generar sempre un avis.
- Si el canvi es dins del mateix cluster i compleix gaps, ha de ser warning informatiu.
- Si el canvi es entre clusters i compleix gaps amb vehicle, ha de ser warning informatiu.
- Si el canvi es entre clusters sense vehicle o amb gap insuficient, ha de ser error o warning fort segons mode.
- Si hi ha outlier o cluster desconegut, ha de quedar avisat explicitament.

## Hipotesi Principal

La designacio actual pot no ser la mes optima possible. No vol dir que sigui incorrecta, sino que l'objectiu actual prioritza cost local de tutor-subgrup i despres intenta reparar. En casos tensos, caldria optimitzar primer la cobertura global i l'ús dels recursos escassos.

Objectiu recomanat:

1. Maximitzar nombre de partits assignats.
2. Minimitzar errors durs de mobilitat/disponibilitat.
3. Reservar tutors amb vehicle per necessitats reals de mobilitat.
4. Minimitzar warnings.
5. Minimitzar cost esportiu: nivell, classificacio, preferencies, etc.

## Proposta 1: Motor De Rutes Per Tutor

Canviar el model mental de "tutor contra subgrup" a "tutor contra ruta diaria".

Una ruta es una sequencia ordenada de segments que un tutor pot fer en un dia:

- Mateixa modalitat.
- Dins disponibilitat.
- Amb temps suficient entre partits.
- Amb mobilitat valida o avisada.
- Amb cost acumulat.

Exemple:

- Tutor A, 2026-04-24:
  - 18:00 Escola X
  - 19:30 Escola Y
  - 21:00 Escola Y

Cada transicio entre pistes calcula:

- mateix pitch?
- mateix cluster?
- clusters diferents?
- outlier?
- te vehicle?
- minuts disponibles?
- gap requerit?
- tipus d'avis/error?

Despres l'optimitzador escull un conjunt de rutes que maximitzi cobertura sense assignar un tutor dues vegades en conflicte.

Avantatge:

- Evita gastar tutors amb vehicle en assignacions que no els necessiten.
- Permet veure clarament quins tutors cobreixen mes partits.
- Dona millor base per explicar per que queden partits sense assignar.

Implementacio possible:

- Generar candidats de ruta per tutor i dia.
- Limitar combinatoria amb beam search o dynamic programming.
- Fer scoring multiobjectiu.
- Seleccionar rutes amb un solver simple inicialment: greedy iteratiu amb reoptimitzacio local, o ILP si es vol mes rigor.

## Proposta 2: Reserva De Tutors Amb Vehicle

Abans de l'assignacio inicial, classificar subgrups/segments segons necessitat de mobilitat:

- `vehicle_required`: segments o combinacions que impliquen canvi de cluster.
- `vehicle_preferred`: outliers o zones no fiables.
- `vehicle_not_needed`: mateixa pista o mateix cluster sense salt.

Regla recomanada:

- Tutors amb vehicle han de tenir una penalitzacio extra si s'assignen a feina que pot fer un tutor sense vehicle.
- Aquesta penalitzacio no ha de ser absoluta, pero ha de protegir recursos escassos.

Exemple de scoring:

- Tutor sense vehicle en mateixa pista: viable.
- Tutor sense vehicle dins mateix cluster: viable amb warning si canvia pista.
- Tutor sense vehicle entre clusters: no viable en mode estricte.
- Tutor amb vehicle entre clusters: viable si gap suficient, amb warning.
- Tutor amb vehicle en partit unic facil: viable pero amb cost extra si hi ha demanda pendent amb vehicle_required.

## Proposta 3: Outliers Com A Zona Virtual

No tractar sempre l'outlier com a bloqueig dur. Alternatives:

1. Nearest cluster:
   - Assignar temporalment l'outlier al cluster mes proper si esta dins un llindar ampli.
   - Marcar `cluster_status = virtual_nearest` o equivalent.
   - Generar warning sempre.

2. Zona manual:
   - Permetre que l'usuari assigni outliers a una zona/cluster des del preview.
   - Ja hi ha base per overrides manuals.

3. Distancia real:
   - Si es disposa de coordenades, calcular distancia aproximada entre seus.
   - Validar mobilitat per temps/distancia en lloc de cluster binari.

4. Mode permissiu amb warning:
   - Si no hi ha cluster pero la seu esta geocodificada, permetre assignacio amb warning si hi ha molt marge temporal.

## Proposta 4: Reoptimitzacio Despres De Rescue

El rescue actual recupera molt poc en el run 96:

- `rescue_segments_generated = 82`
- `rescue_matches_recovered = 1`

Aixo suggereix que segmentar mes no resol si els tutors adequats ja estan mal posicionats.

Millora proposada:

- Despres d'identificar pendents, detectar quins tutors assignats podrien desbloquejar-los.
- Provar swaps locals:
  - desassignar ruta/subgrup facil d'un tutor amb vehicle
  - passar-la a un tutor sense vehicle compatible
  - usar el tutor amb vehicle per recuperar pendent critic

Tipus de cerca:

- 1-swap: canviar assignacio entre dos tutors.
- 2-swap: alliberar un tutor amb vehicle fent dos canvis.
- augmenting path: trobar cadena de substitucions que incrementa cobertura.

Objectiu:

- Acceptar swaps si augmenten partits assignats.
- Si cobertura igual, acceptar si redueixen errors o warnings.

## Proposta 5: Pre-Diagnosi De Capacitat

Abans d'executar l'assignacio completa, calcular:

- Demanda per hora.
- Demanda per cluster.
- Demanda per zona/outlier.
- Tutors disponibles per hora.
- Tutors amb vehicle disponibles per hora.
- Tutors sense vehicle disponibles per cluster/pista.

Per al run 96, per exemple:

- A les 18:00 hi ha 38 partits, 12 pendents.
- A les 19:30 hi ha 16 partits, 6 pendents.
- Hi ha molts tutors sense vehicle i pocs amb vehicle.

Aquesta pre-diagnosi hauria de mostrar:

- Colls d'ampolla horaris.
- Colls d'ampolla de vehicle.
- Seus outlier que poden provocar bloqueig.
- Recomanacions concretes:
  - moure outlier a cluster manual
  - relaxar mobilitat
  - reduir buffer final
  - augmentar radi o usar zona virtual
  - demanar mes tutors amb vehicle

## Proposta 6: Modes De Rigor

Afegir perfils de motor configurables per run/modalitat:

### Mode Estricte

- Com ara o mes conservador.
- Cross-cluster sense vehicle prohibit.
- Outlier prohibit si afecta mobilitat.
- Canvi de pista sempre avisat.

### Mode Operatiu

- Cross-cluster sense vehicle pot ser warning si:
  - hi ha marge temporal molt superior al gap.
  - clusters son propers o distancia estimada baixa.
  - el tutor ja accepta mobilitat urbana.

### Mode Max Cobertura

- Prioritza reduir partits no assignats.
- Permet mes warnings.
- Mai hauria d'amagar avisos.
- Tot canvi de pista queda visible per revisio.

## Nova Regla D'Avis: Qualsevol Canvi De Pista

Requisit funcional explicit:

Sempre que un tutor tingui una sequencia de partits amb canvi de pista/seu en el mateix dia, el sistema ha de generar un avis revisable per l'usuari.

Categories suggerides:

- `same_cluster_pitch_change_warning`
  - Canvi de pista dins el mateix cluster.
  - Viable si compleix gap, pero revisar.

- `cross_cluster_with_vehicle_warning`
  - Canvi entre clusters amb vehicle i gap suficient.
  - Viable, pero revisar.

- `cross_cluster_without_vehicle`
  - Canvi entre clusters sense vehicle.
  - Error en mode estricte, warning fort en mode relaxat.

- `cross_cluster_gap_violation`
  - Canvi entre clusters amb gap insuficient.
  - Error.

- `outlier_mobility_warning`
  - Almenys una seu de la transicio no te cluster fiable.
  - Warning o error segons mode.

- `missing_cluster_mobility_warning`
  - Falta cluster o geocodificacio.
  - Warning o error segons mode.

La UI hauria de mostrar aquests avisos encara que la designacio sigui automatica i "valida".

## Indicadors Nous A Guardar Al Result Summary

Per fer el motor auditable, el `result_summary` hauria d'incloure:

- `coverage_by_hour`
- `coverage_by_cluster`
- `coverage_by_modality`
- `vehicle_usage_summary`
- `vehicle_reserved_count`
- `vehicle_used_on_easy_segments`
- `pitch_change_warning_count`
- `pitch_change_warnings`
- `route_summary_by_referee`
- `unassigned_by_reason_hour_cluster`
- `outlier_assignments_allowed`
- `relaxed_rule_applications`

## Recomanacio D'Implementacio Incremental

### Fase 1: Mes diagnosi i avisos

- Afegir warning per qualsevol canvi de pista.
- Separar warnings informatius d'errors bloquejants.
- Enriquir `result_summary` amb desglossaments per hora, cluster, vehicle i tutor.
- No canviar encara l'assignador.

### Fase 2: Penalitzacio de vehicles mal usats

- Afegir cost extra per usar tutor amb vehicle en subgrups que no requereixen vehicle quan hi ha demanda pendent vehicle_required.
- Comparar resultats amb run 96.

### Fase 3: Outliers virtuals

- Permetre nearest cluster o assignacio virtual amb warning.
- Integrar-ho amb el preview i amb les assignacions finals.

### Fase 4: Reoptimitzacio local

- Implementar swaps locals per desbloquejar pendents.
- Mesurar si augmenta cobertura sense multiplicar warnings greus.

### Fase 5: Motor de rutes

- Substituir progressivament l'assignacio tutor-subgrup per generacio i seleccio de rutes.
- Mantenir compatibilitat amb el format actual de `Assignment`.

## Criteris D'Exit

Per validar la millora, usar run 96 com a cas de prova:

- Reduir `unassigned_matches` per sota de 32.
- No introduir `mobility_errors` ocults.
- Generar warnings per tots els canvis de pista.
- Reduir `cross_cluster_without_vehicle`.
- Explicar clarament els pendents restants.
- Evitar que tutors amb vehicle quedin assignats a tasques facils si bloquegen pendents critics.

## Preguntes Per Al Subagent

1. Quants partits del run 96 es podrien recuperar nomes reassignant tutors amb vehicle?
2. Quins tutors amb vehicle estan usats en segments que no requerien vehicle?
3. Quins pendents `outside_availability_window` son realment impossibles i quins depenen del buffer final?
4. Quins outliers tenen coordenades i podrien rebre cluster virtual?
5. Quin impacte tindria avisar tots els canvis de pista en nombre de warnings?
6. Es suficient una reoptimitzacio local o cal un motor de rutes?

## Estat Del Codi Despres De La Iteracio Amb Subagents Del 2026-04-27

Punt on es deixa el codi: Fase 1 aplicada i Fase 2 aplicada de forma conservadora. Fase 3, Fase 4 i Fase 5 queden pendents.

### Fase 1 Aplicada

- `designacions/services/assignment_feasibility.py`
  - S'han separat incidencies bloquejants i avisos informatius amb `severity`.
  - `mobility_reason_codes(...)` continua retornant nomes codis bloquejants per no trencar l'assignador.
  - `inspect_mobility_transitions(...)` ara pot retornar avisos informatius per:
    - `same_cluster_pitch_change_warning`
    - `cross_cluster_with_vehicle_warning`
    - `outlier_mobility_warning`
    - `missing_cluster_mobility_warning`

- `designacions/services/manual_assignment.py`
  - `build_run_mobility_summary(...)` separa `mobility_errors` i `mobility_warnings`.
  - S'han afegit `pitch_change_warning_count` i `pitch_change_warnings`.
  - Les assignacions amb canvi de pista viable queden marcades com a warning revisable, no com a error.

- UI/backend:
  - `designacions/templates/assignments.html` i `designacions/templates/run_detail.html` mostren els warnings com avisos informatius de mobilitat.
  - `designacions/services/assignment_explainer.py` diferencia `blocking_reasons` i `advisory_reasons`.

### Fase 2 Aplicada

- Nou fitxer `designacions/services/vehicle_policy.py`.
- Es classifica cada unitat assignable, entenent unitat com a subgrup inicial o segment de repesca:
  - `vehicle_required`
  - `vehicle_preferred`
  - `vehicle_not_needed`
- `designacions/main_fixed.py` integra una penalitzacio configurable per usar tutors amb vehicle en unitats `vehicle_not_needed` quan:
  - hi ha pressio de segments `vehicle_required`;
  - el tutor candidat te vehicle;
  - existeix com a minim una alternativa viable sense vehicle.
- La penalitzacio es controla amb:
  - `vehicle_policy_enabled` (per defecte activat)
  - `vehicle_easy_segment_penalty` (per defecte `250.0`)
- El `result_summary` incorpora:
  - `vehicle_usage_summary`
  - `vehicle_used_on_easy_segments`
  - `vehicle_reserved_count`

### Validacio Executada

- OK: `docker compose run --rm web python manage.py test designacions.tests.DesignacionsDateAwareHelpersTests designacions.tests.DesignacionsManualAssignmentsTests.test_build_run_mobility_summary_marks_valid_multi_cluster_assignment_as_warning designacions.tests.DesignacionsManualAssignmentsTests.test_build_run_mobility_summary_keeps_pitch_change_issue_as_warning --verbosity 1`
- OK: `docker compose run --rm web python manage.py test designacions.tests.DesignacionsProgressFlowTests --verbosity 1`
- OK: `docker compose run --rm web python -m compileall designacions/services/assignment_feasibility.py designacions/services/manual_assignment.py designacions/services/vehicle_policy.py designacions/main_fixed.py designacions/views.py designacions/services/assignment_explainer.py`

### Validacio Amb Risc Residual

- Una execucio amplia de `DesignacionsManualAssignmentsTests` ha fallat amb multiples respostes `302` en endpoints que esperaven `200`, i un cas d'assignacio manual que ha quedat seleccionant un tutor diferent. Els tests enfocats sobre mobilitat i resum passen. Abans de donar la iteracio per tancada en produccio, cal revisar si aquests `302` son un requisit d'autenticacio/context de suite o una regressio no relacionada amb la logica nova.

### Pendents Recomanats

- Executar comparativa real amb el run 96 abans i despres de la Fase 2.
- Revisar si `vehicle_easy_segment_penalty = 250.0` es prou fort o massa agressiu.
- Afegir diagnostics agregats per hora/cluster (`coverage_by_hour`, `coverage_by_cluster`, `unassigned_by_reason_hour_cluster`), que encara no s'han implementat.
- No iniciar Fase 3 d'outliers virtuals fins que la comparativa de run 96 confirmi l'impacte de Fase 1 i Fase 2.

## Pla D'Implementacio Nou: Motor De Paquets I Rutes Candidates Amb Solver Global

Aquest pla substitueix la idea de fer nomes swaps locals com a seguent gran pas. La comparativa entre run 96 i run 97 indica que la penalitzacio de vehicle aplicada sobre subgrups inicials no te impacte perque els subgrups inicials es construeixen dins del mateix cluster. Les necessitats reals de vehicle apareixen quan es considera una ruta completa o quan la repesca intenta reutilitzar tutors ja assignats.

Objectiu del nou disseny:

- Mantenir la formacio actual de subgrups base com a punt de partida.
- Generar variants candidates: subgrups base, divisions, fusions i rutes.
- Puntuar aquestes variants segons cobertura, nivell, mobilitat, vehicle, pressio horaria i warnings.
- Seleccionar globalment una combinacio de tutor-paquet sense duplicar partits.
- Rebaixar el paper de la repesca: de mecanisme principal de reparacio a capa post-solver de diagnosi i relaxacio controlada.

### Arquitectura Proposada

Paquets nous recomanats:

- `designacions/optimization/__init__.py`
- `designacions/optimization/contracts.py`
- `designacions/optimization/pressure.py`
- `designacions/optimization/base_subgroups.py`
- `designacions/optimization/package_generation.py`
- `designacions/optimization/package_scoring.py`
- `designacions/optimization/solver.py`
- `designacions/optimization/rescue.py`
- `designacions/optimization/summary.py`

Fitxers existents a integrar:

- `designacions/main_fixed.py`
  - Ha de quedar com a orquestrador temporal, no com a lloc on creix tota la logica nova.
  - Idealment, la nova ruta d'execucio s'activa amb `assignment_engine = "package_solver"` o similar.

- `designacions/services/assignment_feasibility.py`
  - Continuar usant descriptors, disponibilitat, mobilitat i severitat de warnings.

- `designacions/services/vehicle_policy.py`
  - Reutilitzar `has_vehicle`, classificacio vehicle i cost d'oportunitat, pero orientat a paquets/rutes, no nomes subgrups inicials.

- `designacions/services/manual_assignment.py`
  - Continuar sent la font de resum i validacio final post-assignacio.

- `designacions/models.py`
  - No es recomana afegir models nous en la primera iteracio. Guardar diagnostics a `DesignationRun.result_summary`.

### Fase A: Contractes I Model Intern

Objectiu: crear estructures estables perque diferents subagents puguin treballar sense tocar `main_fixed.py`.

Fitxer: `designacions/optimization/contracts.py`

Dataclasses suggerides:

- `BaseSubgroup`
  - `id`
  - `match_ids`
  - `date`
  - `modality`
  - `start_dt`
  - `end_dt`
  - `venue_ids` o `venues`
  - `cluster_ids`
  - `cluster_statuses`
  - `match_count`
  - `level_demand`
  - `classification_pressure`

- `PackageCandidate`
  - `id`
  - `kind`: `base`, `split`, `merged_route`, `split_merged_route`, `single_match`
  - `subgroup_ids`
  - `match_ids`
  - `date`
  - `modality`
  - `start_dt`
  - `end_dt`
  - `requires_vehicle`
  - `vehicle_preferred`
  - `warning_codes`
  - `pressure_relief_score`
  - `base_difficulty_score`

- `TutorCandidate`
  - `id`
  - `code`
  - `modality`
  - `level`
  - `transport`
  - `has_vehicle`
  - `availability_by_date`

- `AssignmentCandidate`
  - `tutor_id`
  - `package_id`
  - `match_ids`
  - `is_viable`
  - `blocking_reasons`
  - `warning_codes`
  - `cost`
  - `score_breakdown`

- `SolverResult`
  - `selected_assignments`
  - `unassigned_match_ids`
  - `rejected_candidates_summary`
  - `objective_summary`

Criteri d'exit:

- Els contractes es poden testejar sense Django DB.
- Hi ha conversors des de files pandas actuals cap a `BaseSubgroup` i `TutorCandidate`.

Subagent recomanat:

- Subagent 1: crear contractes i helpers de serialitzacio.

### Fase B: Pressio I Colls D'Ampolla

Objectiu: transformar distribucions en scores locals per hora, cluster, nivell i vehicle.

Fitxer: `designacions/optimization/pressure.py`

Metriques recomanades:

- `general_pressure`
  - Per bucket `(date, modality, time_bucket)`.
  - Formula inicial: `demand / max(viable_tutor_supply, 1)`.

- `vehicle_pressure`
  - Per bucket `(date, modality, time_bucket)`.
  - Formula inicial: `vehicle_demand / max(vehicle_tutor_supply, 1)`.
  - La demanda de vehicle inicial es pot estimar amb outliers, clusters aillats i possibles rutes cross-cluster candidates.

- `level_pressure`
  - Per bucket i nivell/categoria.
  - Formula inicial: partits/subgrups amb demanda esportiva alta respecte tutors amb nivell acceptable.

- `cluster_pressure`
  - Per `(date, modality, time_bucket, cluster_id)`.
  - Serveix per detectar clusters amb baixa oferta local o molta demanda.

Regles importants:

- La pressio ha de ser local, no global del run.
- No s'ha d'usar la pressio per assignar directament, sino per prioritzar generacio i puntuacio de paquets.
- La pressio ha de ser auditable al `result_summary`.

Sortides a `result_summary`:

- `pressure_summary`
- `pressure_by_hour`
- `pressure_by_cluster`
- `vehicle_pressure_by_hour`
- `level_pressure_by_hour`

Subagent recomanat:

- Subagent 2: implementar calcul de pressions i tests amb dades sintetiques.

### Fase C: Subgrups Base I Variants Per Divisio

Objectiu: mantenir els subgrups base actuals, pero generar divisions candidates quan el bloc base sigui massa rigid.

Fitxer: `designacions/optimization/base_subgroups.py`

Integracio:

- Reutilitzar `_build_daily_subgroups_with_stats(...)` de `main_fixed.py` inicialment.
- A mig termini, moure la logica de subgrups a aquest paquet per reduir `main_fixed.py`.

Fitxer: `designacions/optimization/package_generation.py`

Variants de divisio:

- `base`: subgrup original.
- `single_match`: cada partit sol.
- `contiguous_split`: particions contigues del subgrup.

Quan generar divisions:

- Subgrup amb menys de `K` tutors viables.
- Subgrup amb partits en buckets d'alta pressio.
- Subgrup que impedeix una ruta cross-cluster valuosa.
- Subgrup amb cost de nivell molt irregular entre partits.

Limits per controlar combinatoria:

- No dividir subgrups de 1 partit.
- Per defecte, generar divisions nomes si `len(subgroup) <= 3`.
- Retenir com a maxim `max_split_variants_per_subgroup`.

Subagent recomanat:

- Subagent 3: generacio de variants de divisio i tests de no duplicacio interna.

### Fase D: Generacio De Rutes Candidates

Objectiu: generar fusions candidates entre subgrups o variants, especialment cross-cluster, quan resolen pressio real.

Fitxer: `designacions/optimization/package_generation.py`

Regles per generar rutes:

- Mateix dia.
- Mateixa modalitat.
- Ordre temporal valid.
- Gap suficient segons:
  - mateixa pista: `gap_same_pitch_min`
  - diferent pista mateix cluster: `gap_diff_pitch_min`
  - diferent cluster: `gap_diff_cluster_min`
- Si creua cluster, `requires_vehicle = True`.
- Si hi ha outlier o cluster desconegut, `vehicle_preferred = True` i warning explicit.
- La ruta nomes es conserva si existeix almenys un tutor viable per disponibilitat, nivell i vehicle si cal.

Pressupost de rutes dificils:

- Per `(date, modality)`, calcular `vehicle_capable_referees`.
- Retenir com a maxim:
  - `max(vehicle_capable_referees * route_candidate_factor, vehicle_capable_referees + route_candidate_buffer)`
- Valors inicials:
  - `route_candidate_factor = 2`
  - `route_candidate_buffer = 3`

Score previ de ruta:

- `coverage_value`
- `pressure_relief_score`
- `level_fit_potential`
- `vehicle_opportunity_cost`
- `mobility_risk_cost`
- `warning_cost`

Criteri important:

- No generar rutes perque siguin possibles.
- Generar rutes si redueixen pressio o cobreixen partits que probablement quedaran pendents.

Subagent recomanat:

- Subagent 4: generacio de rutes candidates i pressupost per vehicle.

### Fase E: Scoring Tutor-Paquet

Objectiu: valorar cada parella tutor-paquet amb una funcio de cost explicable.

Fitxer: `designacions/optimization/package_scoring.py`

Entrades:

- `TutorCandidate`
- `PackageCandidate`
- pressions calculades
- configuracio del run

Validacions bloquejants:

- Modalitat incompatible.
- Disponibilitat insuficient.
- Nivell/categoria no puntuable si el mode ho considera bloquejant.
- Cross-cluster sense vehicle en mode estricte.
- Gap insuficient.
- Assignacions locked incompatibles.

Warnings:

- Canvi de pista mateix cluster.
- Cross-cluster amb vehicle.
- Outlier o cluster desconegut en mode permissiu.
- Gap ajustat pero no invalid.

Components de cost:

- `coverage_reward`: maxim prestigi per cobrir mes partits.
- `level_cost`: ajust tutor vs categoria.
- `classification_cost`: cost esportiu segons posicio dels equips.
- `mobility_cost`: canvi de pista/cluster/gap.
- `vehicle_cost`: cost d'oportunitat de gastar vehicle.
- `pressure_relief_reward`: bonus per reduir pressio alta.
- `warning_cost`: warnings informatius penalitzen, pero menys que errors.

Sortida:

- `AssignmentCandidate` amb `score_breakdown`.

Subagent recomanat:

- Subagent 5: scoring i tests de casos minimals.

### Fase F: Solver Global De Paquets

Objectiu: seleccionar assignacions tutor-paquet sense duplicar partits i maximitzant cobertura.

Fitxer: `designacions/optimization/solver.py`

Model recomanat:

- Variables binaries:
  - `x[tutor_id, package_id] in {0,1}`

Restriccions:

- Cada partit com a maxim una vegada:
  - `sum(x[t,p] for p containing match_id) <= 1`
- Cada tutor com a maxim una ruta principal per dia:
  - `sum(x[t,p] for p in day) <= 1`
- Nomes candidats viables:
  - no crear variables per candidats amb errors bloquejants.
- Assignacions locked:
  - o be generar paquets obligatoris,
  - o be excloure partits locked i reservar el tutor corresponent.

Objectiu lexicografic recomanat:

1. Maximitzar partits assignats.
2. Minimitzar errors bloquejants. En principi han de ser zero.
3. Minimitzar partits pendents en buckets d'alta pressio.
4. Minimitzar cost de nivell/classificacio.
5. Minimitzar mal us de vehicle.
6. Minimitzar warnings.

Implementacio inicial:

- Preferencia: usar `scipy.optimize.milp` si la versio disponible ho permet.
- Fallback: greedy amb reparacio si no hi ha solver MILP disponible.
- No afegir dependencia externa nova sense validar entorn Docker.

Resultat:

- `SolverResult`
- llista de partits assignats amb tutor
- llista de pendents amb motiu
- resum d'objectiu

Subagent recomanat:

- Subagent 6: solver MILP/fallback greedy i tests de no duplicacio.

### Fase G: Repesca Post-Solver

Objectiu: mantenir repesca, pero com a capa limitada de recuperacio i explicacio.

Fitxer: `designacions/optimization/rescue.py`

Tipus de repesca:

- `single_match_rescue`
  - Generar paquet individual per pendent.
  - Intentar encaixar sense desassignar res.

- `relaxed_warning_rescue`
  - Permetre outlier o missing cluster com warning si el mode del run ho accepta.
  - Mai amagar el warning.

- `augmenting_path_rescue`
  - Cadena curta de substitucions.
  - Acceptar nomes si augmenta cobertura o redueix errors sense perdre partits.

Regles:

- No executar repesca abans del solver.
- No crear errors bloquejants ocults.
- Guardar `rescue_summary` al `result_summary`.

Subagent recomanat:

- Subagent 7: repesca post-solver i diagnostics.

### Fase H: Integracio Amb Persistencia I UI

Fitxer principal:

- `designacions/main_fixed.py`

Canvi recomanat:

- Afegir selector d'engine:
  - `assignment_engine = "legacy"` per defecte inicial si cal conservador.
  - `assignment_engine = "package_solver"` per activar nou motor.

Persistencia:

- Reutilitzar `persist_assignacions_to_db(...)`.
- El format final ha de poder convertir-se a `df_assignacions` amb les mateixes columnes actuals:
  - `Codi Partit`
  - `Tutor Codi`
  - `Tutor Nom`
  - `Tutor Cognoms`
  - `Classificacio Equips`

UI:

- Inicialment no cal nova UI.
- Afegir al `result_summary`:
  - `engine_name`
  - `package_solver_summary`
  - `pressure_summary`
  - `selected_package_count`
  - `candidate_package_count`
  - `solver_unassigned_details`
  - `rescue_summary`

Subagent recomanat:

- Subagent 8: integracio fina a `main_fixed.py`, persistencia i resum.

### Fase I: Tests I Comparativa

Fitxer:

- `designacions/tests.py`

Tests nous recomanats:

- Contractes:
  - paquets no dupliquen partits internament.

- Pressio:
  - bucket amb mes demanda que oferta dona pressio alta.
  - vehicle pressure nomes puja quan hi ha demanda que requereix vehicle.

- Generacio de rutes:
  - no genera cross-cluster sense gap suficient.
  - no genera ruta vehicle_required si no hi ha cap tutor amb vehicle viable.
  - limita top N segons pressupost de vehicles.

- Solver:
  - no assigna el mateix partit dues vegades.
  - prefereix cobrir mes partits encara que el cost esportiu sigui una mica pitjor.
  - reserva vehicle per ruta cross-cluster quan hi ha alternatives sense vehicle per subgrups facils.

- Integracio:
  - run sintetic on legacy deixa un pendent per vehicle i package_solver el recupera.
  - run sintetic on no hi ha vehicles i package_solver no inventa assignacions invalides.

Comparativa obligatoria:

- Run 96 legacy vs package_solver.
- Run 97 legacy vs package_solver.

Indicadors:

- `assigned`
- `unassigned_matches`
- `remaining_unassigned_breakdown`
- `mobility_error_count`
- `mobility_warning_count`
- `vehicle_used_on_easy_segments_count`
- `candidate_package_count`
- `selected_package_count`
- temps d'execucio

### Orquestracio Recomanada Amb Subagents

L'agent principal hauria de fer:

- Llegir estat actual del repo i assegurar que tests enfocats passen abans de començar.
- Obrir una branca o deixar clar que es treballa en workspace brut.
- Delegar subtasques amb write scopes separats.
- Evitar que dos subagents editin `main_fixed.py` alhora.
- Integrar per capes:
  - contractes
  - pressio
  - generacio
  - scoring
  - solver
  - integracio
  - tests

Assignacio de subagents:

- Subagent A: `optimization/contracts.py`
- Subagent B: `optimization/pressure.py`
- Subagent C: `optimization/package_generation.py`
- Subagent D: `optimization/package_scoring.py`
- Subagent E: `optimization/solver.py`
- Subagent F: `optimization/rescue.py`
- Subagent G: tests sintetiques
- Agent principal: integracio a `main_fixed.py`, revisio, execucio de tests i comparativa run 96/97.

### Preguntes Obertes Abans D'Implementar

1. Quin ha de ser el mode per defecte quan el nou motor existeixi: `legacy` o `package_solver`?
2. Es permet afegir una dependencia de solver MILP si `scipy.optimize.milp` no esta disponible o no dona prou garanties?
3. Quin criteri de nivell es considera bloquejant i quin nomes penalitzacio?
4. Els outliers poden ser assignats amb warning en algun mode, o continuen sent bloqueig dur fins a Fase 3?
5. Quants warnings informatius son acceptables si la cobertura puja?
6. Quin limit de temps d'execucio es considera acceptable per un run de 100-300 partits?
7. Les assignacions locked han de bloquejar tambe el tutor per tot el dia o nomes per la finestra del partit/ruta locked?

## Estat D'Implementacio Del Motor Package Solver Del 2026-04-27

Punt on es deixa el codi: implementacio incremental disponible darrere del flag `assignment_engine = "package_solver"`. El motor per defecte continua sent `legacy`.

### Fase A Implementada: Contractes

Fitxers:

- `designacions/optimization/__init__.py`
- `designacions/optimization/contracts.py`

Canvis:

- Afegides dataclasses pures sense dependencia Django:
  - `BaseSubgroup`
  - `PackageCandidate`
  - `TutorCandidate`
  - `AssignmentCandidate`
  - `SolverResult`
- Afegits helpers de normalitzacio d'IDs i `to_dict()`.
- `PackageCandidate` suporta camps operatius que necessita el generador:
  - `coverage_value`
  - `route_score`
  - `cluster_ids`
  - `cluster_statuses`
  - `venues`
  - `component_ids`
  - `level_demand`
  - `classification_pressure`

### Fase B Implementada: Pressio

Fitxer:

- `designacions/optimization/pressure.py`

Canvis:

- Afegit `build_pressure_summary(...)`.
- Calcula:
  - `pressure_by_hour`
  - `vehicle_pressure_by_hour`
  - `level_pressure_by_hour`
  - `pressure_by_cluster`
  - `pressure_summary`
- Funciona amb dataclasses, dicts o objectes equivalents.
- No depen de Django.

Limitacio actual:

- La pressio de vehicle inicial depen de paquets/subgrups que ja indiquen demanda de vehicle. Encara no estima de forma profunda demanda futura de rutes abans de generar-les.

### Fase C Implementada: Subgrups Base I Divisions

Fitxer:

- `designacions/optimization/base_subgroups.py`
- `designacions/optimization/package_generation.py`

Canvis:

- `build_base_subgroups_from_rows(...)` converteix els subgrups actuals del motor a `BaseSubgroup`.
- `generate_package_candidates(...)` genera:
  - `base`
  - `single_match`
  - `contiguous_split`
- La divisio es limita amb:
  - `max_split_subgroup_size`
  - `max_split_variants_per_subgroup`

### Fase D Implementada: Rutes Candidates

Fitxer:

- `designacions/optimization/package_generation.py`

Canvis:

- Genera rutes:
  - `merged_route`
  - `split_merged_route`
- Regles implementades:
  - mateix dia
  - mateixa modalitat
  - ordre temporal valid
  - gap minim segons config
  - `requires_vehicle` si hi ha clusters diferents
  - `vehicle_preferred` si hi ha cluster no fiable
  - retencio limitada per pressupost de vehicles

Limits configurables:

- `route_candidate_factor`
- `route_candidate_buffer`
- `gap_same_pitch_min`
- `gap_diff_pitch_min`
- `gap_diff_cluster_min`

### Fase E Implementada: Scoring Tutor-Paquet

Fitxer:

- `designacions/optimization/package_scoring.py`

Canvis:

- Afegit `build_assignment_candidates(...)`.
- Valida:
  - modalitat
  - disponibilitat simple
  - vehicle requerit
  - nivell simplificat
- Calcula `cost` i `score_breakdown`.
- Penalitza warnings i mal us de vehicle quan hi ha pressio.

Limitacio actual:

- El cost de nivell es simplificat i encara no replica completament la logica esportiva de `_compute_subgroup_base_cost(...)`.

### Fase F Implementada: Solver Global

Fitxer:

- `designacions/optimization/solver.py`

Canvis:

- Afegit `solve_assignment_candidates(...)`.
- Garanteix:
  - cada partit com a maxim una vegada
  - cada tutor com a maxim un paquet per dia
- Estrategia:
  - cerca exacta acotada per conjunts petits
  - greedy deterministic per conjunts grans
- Objectiu implementat:
  - maximitzar cobertura
  - minimitzar cost

Limitacio actual:

- No usa encara MILP extern ni `scipy.optimize.milp`.
- Les restriccions locked encara no estan integrades.

### Fase G No Implementada Encara: Repesca Post-Solver

Estat:

- No s'ha creat `designacions/optimization/rescue.py`.
- El solver ja retorna pendents, pero encara no hi ha repesca post-solver.

Pendent:

- `single_match_rescue`
- `relaxed_warning_rescue`
- `augmenting_path_rescue`

### Fase H Implementada Parcialment: Integracio

Fitxer:

- `designacions/main_fixed.py`

Canvis:

- Afegit selector:
  - `assignment_engine = "legacy"` per defecte.
  - `assignment_engine = "package_solver"` per activar nou flux.
- El nou flux s'integra dins del bucle per modalitat.
- El resultat inclou:
  - `engine_name`
  - `package_solver_summary`
  - `candidate_package_count`
  - `selected_package_count`
- La persistencia continua passant per `persist_assignacions_to_db(...)`.

Limitacions actuals:

- El motor nou encara conviu dins `main_fixed.py`; cal extreure orquestracio a un servei propi si creix.
- La comparativa amb runs reals 96/97 encara no s'ha executat amb `assignment_engine = "package_solver"`.

### Fase I Implementada Parcialment: Tests

Fitxer:

- `designacions/tests.py`

Tests afegits:

- `DesignacionsOptimizationPackageSolverTests.test_solver_never_assigns_same_match_twice`
- `DesignacionsOptimizationPackageSolverTests.test_route_generation_is_limited_by_vehicle_budget`

Validacions executades:

- OK: `docker compose run --rm web python -m compileall designacions/optimization designacions/main_fixed.py`
- OK: `docker compose run --rm web python manage.py test designacions.tests.DesignacionsProgressFlowTests --verbosity 1`
- OK: `docker compose run --rm web python manage.py test designacions.tests.DesignacionsOptimizationPackageSolverTests designacions.tests.DesignacionsProgressFlowTests --verbosity 1`
- OK: prova sintetica manual amb `assignment_engine = "package_solver"` dins `manage.py shell`, assignant 2/2 partits.
- Nota final: despres d'aquestes validacions s'ha fet un microajust a `package_generation.py` per tenir en compte `TutorCandidate.availability_by_date` durant la generacio de rutes. No s'ha pogut reexecutar Docker per limit d'us de l'entorn, pero `git diff --check` no mostra errors.

### Decisions Preses Durant La Implementacio

- El mode per defecte queda com `legacy` per no canviar comportament productiu sense comparativa.
- No s'ha afegit cap dependencia nova de solver.
- Outliers i clusters no fiables continuen generant warnings/costos, pero no s'ha implementat encara mode permissiu complet.
- Les assignacions locked es deixen com a pendent tecnic del solver.

### Proxim Pas Recomanat

Executar comparativa real:

- Run 96 amb `assignment_engine = "legacy"` vs `package_solver`.
- Run 97 amb `assignment_engine = "legacy"` vs `package_solver`.

Abans de considerar-lo productiu cal revisar:

- qualitat de nivell/categoria respecte el motor legacy;
- tractament de locked assignments;
- tractament de repesca post-solver;
- rendiment amb 100-300 partits;
- si el solver genera massa paquets o massa warnings.

## Actualitzacio De Direccio: Motor Level-Aware I Rutes Amb Criteri Esportiu

Data: 2026-04-27

Aquesta seccio actualitza el pla despres de les primeres proves reals amb el motor `package_solver`.

### Que S'ha Vist Als Runs Reals

Run 98:

- Va donar el mateix patro que els runs 96/97.
- Diagnosi: no estava usant realment el motor nou. El `params` no contenia `assignment_engine = "package_solver"` i el `result_summary.engine_name` era `legacy`.
- Accio aplicada: afegit selector/checkbox de motor al formulari i al preview:
  - `designacions/templates/upload.html`
  - `designacions/templates/cluster_preview_partial.html`
  - `designacions/views.py`

Run 132:

- Ja usava `package_solver`.
- Problema observat: partits `SENIOR` assignats a tutors `NIVELLC1` o `NIVELLD1`.
- Diagnosi:
  - `_level_rank(...)` mirava el digit final del nivell.
  - `NIVELLA1`, `NIVELLB1`, `NIVELLC1`, `NIVELLD1` quedaven tots aproximadament com a rang `1`.
  - Aixo feia que el motor nou no distingis A/B/C/D.
- Accio aplicada:
  - `designacions/optimization/package_scoring.py` ara usa escales ordenades explicites de tutors i categories.
  - El cost de nivell passa a ser distancia normalitzada entre escala de tutor i escala de categoria.
  - `designacions/optimization/package_generation.py` conserva la categoria mes exigent quan fusiona rutes.

Run 133:

- Millora respecte run 132: diversos `SENIOR` ja van a `NIVELLA1`.
- Problema encara present: encara hi ha algun `SENIOR` assignat a `NIVELLB1` o `NIVELLC1`.
- Diagnosi:
  - El nivell encara es tracta com un cost dins una suma global.
  - Cobertura, vehicle, ruta i pressio poden compensar massa un mal encaix de nivell.
  - El solver prioritza valor de cobertura i cost total, pero no imposa jerarquia esportiva forta.
- Exemple conceptual de costos actuals:
  - `SENIOR + A`: `level_cost = 0`
  - `SENIOR + B`: `level_cost ~= 250`
  - `SENIOR + C`: `level_cost ~= 500`
  - `SENIOR + D`: `level_cost ~= 750`
  - Un `classification_fit_cost` s'afegeix si el partit es important per classificacio, pero continua sent penalitzacio, no restriccio.

### Canvis Ja Aplicats Despres De La Primera Implementacio

Fitxers afectats:

- `designacions/optimization/classification.py`
- `designacions/optimization/base_subgroups.py`
- `designacions/optimization/contracts.py`
- `designacions/optimization/package_generation.py`
- `designacions/optimization/package_scoring.py`
- `designacions/optimization/solver.py`
- `designacions/main_fixed.py`
- `designacions/tests.py`

Canvis aplicats:

- Afegit `classification_importance`:
  - mes alt per partits de part alta de classificacio;
  - bonus per top 3;
  - bonus per posicions properes;
  - `1 vs 2` queda com a importancia maxima o quasi maxima.
- Afegit `weighted_coverage_value`:
  - un partit normal val aproximadament `1.0`;
  - un partit classificatoriament important pot pujar fins aproximadament `1.4`;
  - objectiu: prioritzar partits importants sense sacrificar massivament cobertura.
- El solver ara prioritza:
  - `weighted_covered_value`;
  - nombre de partits coberts;
  - cost total;
  - menys assignacions.
- Afegit `classification_fit_cost`:
  - penalitza tutors mes fluixos en partits classificatoriament importants.
- Fix de persistencia de classificacions:
  - les posicions es calculaven dins `df_partits_modalitat`, pero es persistia `df_partits` original;
  - ara es copien `Posicio Equip Local` i `Posicio Equip Visitant` al dataframe global abans de persistir.

Validacions:

- `DesignacionsOptimizationPackageSolverTests` ampliat amb proves de:
  - no duplicar partits;
  - limitar rutes per pressupost de vehicle;
  - distancia de nivell per lletra A/B/C/D;
  - penalitzacio per classificacio amb tutor feble;
  - prioritzacio per cobertura ponderada.

### Interpretacio Actual Dels Costos

El cost actual de cada candidat `tutor + paquet` es:

```text
 level_cost
+ classification_fit_cost
+ mobility_cost
+ vehicle_cost
+ warning_cost
+ base_difficulty_cost
- pressure_relief_reward
```

`level_cost`:

- Mesura distancia entre categoria del partit i nivell del tutor.
- Ara es basa en escales explicites.
- Actualment es una penalitzacio, no un filtre dur.
- Problema: encara pot ser compensat per altres factors.

`classification_fit_cost`:

- Penalitza que un partit classificatoriament important caigui a un tutor fluix.
- Ha d'actuar despres del nivell, no substituir-lo.
- Serveix per ordenar entre candidats acceptables, per exemple:
  - `SENIOR 1vs2` hauria de tendir mes a A que `SENIOR 8vs10`.

`mobility_cost`:

- Penalitza canvis de cluster, outliers, missing cluster i warnings de mobilitat.
- No ha de poder justificar assignacions esportivament dolentes.

`vehicle_cost`:

- Penalitza gastar vehicle en segments facils quan hi ha pressio de vehicle.
- Ha de decidir dins el conjunt de tutors esportivament elegibles.

`warning_cost`:

- Cost baix per avisos informatius.
- Ha de servir per desempatar o ordenar, no per dominar.

`base_difficulty_cost`:

- Avui pesa poc.
- Ve de dificultat generica del paquet/ruta.
- No ha de ser criteri principal.

`pressure_relief_reward`:

- Redueix cost si el paquet alleuja pressio horaria/vehicle.
- Risc: si pesa massa pot compensar mal nivell.
- Recomanacio: mantenir-lo subordinat a elegibilitat de nivell.

### Nova Decisio De Disseny: El Nivell Ha De Manar

El criteri esportiu principal ha de ser el nivell.

Regla conceptual:

```text
1. Primer: el tutor es esportivament elegible per aquest paquet/ruta?
2. Despres: vehicle i mobilitat.
3. Despres: classificacio dins candidats elegibles.
4. Despres: pressio, warnings i altres refinaments.
```

Per tant, el nivell no hauria de ser nomes un pes dins una suma.

El model recomanat es:

- `gap 0`: ideal.
- `gap 1`: acceptable si cal.
- `gap >= 2`: inviable o quasi inviable.
- Extrems de categoria:
  - `SENIOR + A`: ideal.
  - `SENIOR + B`: excepcional pero possible.
  - `SENIOR + C/D`: inviable o penalitzacio prohibitiva.

No cal fer tots els casos rigids, pero si cal evitar que el solver pugui compensar `SENIOR + C/D` amb vehicle, cobertura o pressio.

### Nova Fase Prioritaria: Rutes Level-Aware

Objectiu:

- Les rutes candidates no s'han de formar nomes per proximitat horaria/geografica.
- S'han de formar sabent quin tipus de tutor les pot pitar be.

Cada `PackageCandidate` hauria d'exposar:

```python
level_demand
level_gap_by_tutor
eligible_level_band
classification_importance
requires_vehicle
vehicle_preferred
weighted_coverage_value
```

Abans d'acceptar o prioritzar una ruta candidata, caldria validar:

- quants tutors tenen nivell suficient per aquesta ruta;
- quants d'aquests tutors tenen vehicle si la ruta el requereix;
- si la ruta consumeix un tutor A/B que faria falta per una altra ruta mes critica;
- si dividir la ruta genera mes cobertura esportivament valida que fusionar-la.

### Proposta De Solver Per Jerarquies

Canviar el model de `cost suma` cap a `restriccions + objectiu`.

Fase 1: construir elegibilitat esportiva.

Per cada `tutor + paquet`:

```text
level_fit =
  ideal
  acceptable
  exceptional
  forbidden
```

Regles inicials suggerides:

- `forbidden`:
  - `SENIOR` amb `NIVELLC1`, `NIVELLD1` o `D`;
  - categories altes amb gap extrem;
  - nivell no reconegut si la categoria es alta.
- `exceptional`:
  - `SENIOR` amb `NIVELLB1`;
  - gap 1 en paquet amb alta classificacio.
- `acceptable`:
  - gap 1 en categories no extremes.
- `ideal`:
  - gap 0 o tutor superior proper.

Fase 2: generar rutes amb aquesta elegibilitat.

- No generar o no retenir rutes sense tutors `ideal/acceptable`.
- Rutes amb nomes candidats `exceptional` han de quedar com a fallback, no com a candidates normals.
- Rutes `forbidden` no entren al solver.

Fase 3: solver lexicografic.

Objectiu recomanat:

```text
1. maximitzar cobertura de partits amb assignacio esportivament valida
2. maximitzar cobertura de categories altes
3. minimitzar assignacions exceptional
4. maximitzar weighted_coverage_value per classificacio
5. minimitzar cost vehicle/mobilitat
6. minimitzar warnings i altres costos
```

Aixo evita que un `SENIOR + C` sigui triat nomes perque millora vehicle o ruta.

### Canvis Concrets Que Ha De Fer El Proper Agent

1. Crear o ampliar modul de nivell:

Fitxer proposat:

- `designacions/optimization/levels.py`

Responsabilitats:

- Definir escales de tutor i partit.
- Calcular `level_gap`.
- Classificar `level_fit` com `ideal`, `acceptable`, `exceptional`, `forbidden`.
- Exposar helpers sense dependencia Django.

2. Actualitzar `package_scoring.py`.

Canvis:

- Substituir part del `level_cost` per `level_fit`.
- Si `level_fit == forbidden`, `is_viable = False` amb reason `level_forbidden`.
- Si `level_fit == exceptional`, aplicar penalitzacio molt alta i comptador separat:
  - per exemple `exceptional_level_penalty = 3000` o superior.
- Mantenir `level_cost` numeric per ordenar dins el mateix grup.

3. Actualitzar `package_generation.py`.

Canvis:

- Durant generacio de rutes, estimar tutors elegibles per nivell.
- Penalitzar o descartar rutes sense candidats `ideal/acceptable`.
- En retencio de rutes candidates, ordenar per:
  - cobertura viable per nivell;
  - nivell de demanda;
  - classificacio;
  - vehicle;
  - route_score.

4. Actualitzar `solver.py`.

Canvis:

- Afegir objectiu lexicografic amb:
  - `covered_match_count`;
  - `covered_high_level_value`;
  - `exceptional_level_count` negatiu;
  - `weighted_covered_value`;
  - `total_cost` negatiu.
- En greedy, afegir passades que prioritzin:
  - menys `exceptional`;
  - mes cobertura alta;
  - menor cost.

5. Actualitzar resultats i diagnostics.

Afegir a `package_solver_summary`:

- `level_forbidden_candidate_count`
- `level_exceptional_selected_count`
- `selected_by_level_fit`
- `senior_assignments_by_tutor_level`
- exemples de pitjors assignacions de nivell.

6. Tests obligatoris.

Afegir tests:

- `SENIOR + C/D` es inviable.
- `SENIOR + B` es exceptional.
- Si hi ha A disponible, `SENIOR` no va a B.
- Si no hi ha A pero hi ha B, `SENIOR` pot anar a B si no deixa altres partits de mes nivell desatesos.
- La ruta amb mes partits no guanya si obliga un `SENIOR + C`.
- La classificacio decideix entre dos tutors elegibles, no entre elegible i prohibit.

### Recomanacio De Pesos Mentre No Hi Hagi Solver Jerarquic

Si abans d'implementar el model level-aware es vol una millora rapida:

```python
level_distance_weight = 2000
classification_fit_weight = 1000
exceptional_level_penalty = 3000
```

Pero aquesta es nomes una mitigacio. La solucio correcta es separar:

- elegibilitat esportiva;
- construccio de rutes;
- optimitzacio de cobertura;
- refinament per vehicle/classificacio/pressio.

## Estat Implementat: Model Level-Aware Amb Rutes Filtrades

Data: 2026-04-27

S'ha aplicat la primera versio funcional del model level-aware.

### Canvis Implementats

Fitxer nou:

- `designacions/optimization/levels.py`

Funcions i constants:

- `TUTOR_LEVEL_ORDER`
- `MATCH_LEVEL_ORDER`
- `level_gap(...)`
- `level_fit(...)`
- `level_distance_cost(...)`
- labels:
  - `ideal`
  - `acceptable`
  - `exceptional`
  - `forbidden`
  - `unscorable`

Regles aplicades:

- `SENIOR + NIVELLA1`: `ideal`
- `SENIOR + NIVELLB1`: `exceptional`
- `SENIOR + NIVELLC1/NIVELLD1/D`: `forbidden`
- gap gran de nivell: `forbidden`
- gap petit: `acceptable` o `exceptional` segons categoria i importancia de classificacio

Fitxer:

- `designacions/optimization/package_scoring.py`

Canvis:

- `level_fit == forbidden` fa el candidat inviable amb reason `level_forbidden`.
- `level_fit == exceptional` continua sent viable pero rep `exceptional_level_penalty`.
- `score_breakdown` inclou:
  - `level_fit`
  - `level_exceptional`
  - `level_cost`
  - `classification_fit_cost`

Fitxer:

- `designacions/optimization/package_generation.py`

Canvis:

- Les rutes candidates calculen `level_fit_summary`.
- `eligible_tutor_count` compta tutors `ideal + acceptable`.
- Les rutes fusionades sense cap tutor `ideal/acceptable` es descarten per defecte.
- Es poden permetre rutes nomes `exceptional` amb `allow_exceptional_routes=True`.
- La retencio de rutes prioritza:
  - tutors `ideal/acceptable`
  - `weighted_coverage_value`
  - `classification_importance`
  - `route_score`

Fitxer:

- `designacions/optimization/solver.py`

Canvis:

- L'objectiu lexicografic ara penalitza assignacions `exceptional` abans de mirar cost.
- `objective_summary` inclou `selected_exceptional_level_count`.
- El greedy tambe considera `level_exceptional` per evitar triar l'opcio mes barata si es esportivament pitjor.

Fitxer:

- `designacions/main_fixed.py`

Canvis:

- `package_solver_summary` inclou:
  - `level_forbidden_candidate_count`
  - `level_blocking_counts`
  - `selected_by_level_fit`
  - `level_exceptional_selected_count`

### Tests Implementats

Fitxer:

- `designacions/tests.py`

Tests del paquet:

- No duplicar partits.
- Limitar rutes per pressupost de vehicle.
- Distancia de nivell per lletra A/B/C/D.
- Penalitzacio de classificacio amb tutor feble.
- Prioritzacio per cobertura ponderada.
- Preferir candidat no `exceptional` abans que una petita millora de cost.
- `SENIOR + C/D` inviable.

Validacio executada:

- `docker compose exec -T web python -m compileall designacions/optimization designacions/main_fixed.py designacions/tests.py`
- `docker compose exec -T web python manage.py test designacions.tests.DesignacionsOptimizationPackageSolverTests --verbosity 1`

Resultat:

- 7 tests OK.

### Punt On Queda El Codi

El nou motor ja no es nomes un solver per costos continus. Ara aplica:

```text
1. elegibilitat esportiva de nivell
2. filtratge de rutes sense tutors aptes
3. penalitzacio forta de casos exceptional
4. optimitzacio de cobertura ponderada i cost
```

El motor continua darrere del flag:

```python
assignment_engine = "package_solver"
```

El mode per defecte continua sent `legacy`.

### Seguent Validacio Recomanada

Executar un run nou amb el mateix set que 96/97/132/133 i comprovar:

- `engine_name == "package_solver"`
- `selected_by_level_fit`
- `level_exceptional_selected_count`
- si encara hi ha `SENIOR` amb B;
- confirmar que ja no hi ha `SENIOR` amb C/D;
- revisar si la cobertura baixa massa per culpa del bloqueig esportiu.

Si baixa massa la cobertura:

- activar temporalment `allow_exceptional_routes=True`;
- revisar si falten tutors A/B amb vehicle;
- estudiar una repesca post-solver que nomes permeti relaxacions controlades.

### Correccio Posterior: `level_demand` Amb Ordre Esportiu

Problema detectat al run 134:

- El resum del solver indicava que no seleccionava candidats `forbidden`.
- Pero a la BD apareixien partits `SENIOR` amb tutors C/D.
- Diagnosi:
  - el bloqueig `SENIOR + C/D = forbidden` funcionava correctament;
  - el problema era que alguns paquets/splits no conservaven `level_demand = SENIOR`;
  - `base_subgroups.py` feia `min(values)` sobre categories fora del `CategoricalDtype` ordenat del legacy;
  - `package_generation.py` podia heretar `level_demand` del subgrup base en splits en comptes de recalcular-lo per les files seleccionades.

Fix aplicat:

- `designacions/optimization/levels.py`
  - afegit `hardest_match_level(...)`.
- `designacions/optimization/base_subgroups.py`
  - `_level_demand(rows)` ara usa `hardest_match_level(...)`.
- `designacions/optimization/package_generation.py`
  - splits i talls contigus recalculen `level_demand` a partir de les files seleccionades.
  - rutes fusionades usen `hardest_match_level(...)` entre components.

Test afegit:

- Un split que conte un partit `SENIOR` conserva `level_demand = SENIOR`.
- Aquest split amb tutor `NIVELLC1` queda inviable amb `level_forbidden`.

Validacio:

- `DesignacionsOptimizationPackageSolverTests`: 8 tests OK.

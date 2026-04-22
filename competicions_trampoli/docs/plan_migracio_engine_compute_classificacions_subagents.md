# Pla D'Implementacio De La Migracio Del Compute De Classificacions Per Subagents

## Objectiu
- Desmonolititzar `competicions_trampoli/services/legacy/services_classificacions_2.py` sense perdre comportament.
- Portar el runtime de calcul a una estructura nova, petita i mantenible.
- Permetre treball paral.lel de diversos subagents amb write scopes disjunts, dependencies clares i poc context implicit.
- Deixar `competicions_trampoli/services/classificacions/compute.py` com a frontera publica estable i neta.

## Resum Executiu
- Avui el monolit de compute barreja en un sol fitxer:
  - normalitzacio de schema
  - filtres i context d'equips
  - queries ORM
  - resolucio de camps i agregacions
  - seleccio d'exercicis
  - candidate source i contributors
  - desempats i pipeline runtime
  - mode `victories`
  - agrupacio final per `individual`, `equips` i `entitat`
  - render de columnes raw i payloads de detall
- La migracio correcta no es "partir el fitxer en trossos arbitraris".
- La migracio correcta es construir un `engine` intern per fases i canviar el punt d'entrada nomes quan hi hagi paritat suficient.

## Regla Principal
- Aquesta feina es una refactoritzacio estructural amb risc funcional alt.
- Cap subagent no ha de "netejar" logica mentre extreu codi.
- La semantica publica de `compute_classificacio()` s'ha de conservar:
  - mateixa entrada
  - mateixa sortida
  - mateixes claus de `row`
  - mateixa compatibilitat amb `tipus=individual|equips|entitat`
- La migracio s'ha de fer amb tall progressiu:
  - primer mòduls nous
  - despres orquestracio nova
  - finalment cutover del bridge
- No s'ha de reobrir el debat de producte mentre s'esta extraient el runtime.

## Estat Actual

### Punt D'Entrada Public
- `competicions_trampoli/services/classificacions/compute.py`

### Bridge Temporal Actual
- `competicions_trampoli/services/classificacions/_compute_bridge.py`
  importa directament des de:
- `competicions_trampoli/services/classificacions/engine/schema.py`
- `competicions_trampoli/services/classificacions/engine/orchestrator.py`

### Moduls Ja Separats O Quasi Separats
- `competicions_trampoli/services/classificacions/filters.py`
- `competicions_trampoli/services/classificacions/_filters_impl.py`
- `competicions_trampoli/services/classificacions/partitions.py`
- `competicions_trampoli/services/classificacions/_partitions_impl.py`
- `competicions_trampoli/services/classificacions/pipeline_runtime.py`
- `competicions_trampoli/services/classificacions/provenance/`
- `competicions_trampoli/services/classificacions/ties/`
- `competicions_trampoli/services/classificacions/engine/common.py`
- `competicions_trampoli/services/classificacions/engine/model_utils.py`
- `competicions_trampoli/services/classificacions/engine/schema.py`
- `competicions_trampoli/services/classificacions/engine/loaders.py`
- `competicions_trampoli/services/classificacions/engine/score_values.py`
- `competicions_trampoli/services/classificacions/engine/filter_runtime.py`
- `competicions_trampoli/services/classificacions/engine/partition_runtime.py`
- `competicions_trampoli/services/classificacions/engine/selection.py`
- `competicions_trampoli/services/classificacions/engine/selection_runtime.py`
- `competicions_trampoli/services/classificacions/engine/metrics_runtime.py`
- `competicions_trampoli/services/classificacions/engine/victories.py`
- `competicions_trampoli/services/classificacions/engine/teams.py`
- `competicions_trampoli/services/classificacions/engine/detail_payload.py`
- `competicions_trampoli/services/classificacions/engine/ranking.py`

### Monolit Residual A Aprimar
- `competicions_trampoli/services/classificacions/engine/orchestrator.py`

### Oracle Legacy Encara Present
- `competicions_trampoli/services/legacy/services_classificacions_2.py`

### Actualitzacio 2026-04-22
- El punt d'entrada public ja no depen del legacy. El cutover funcional del bridge esta fet.
- La Fase 4 queda funcionalment tancada en aquesta iteracio:
  - `selection_runtime.py` ja exposa exports per a l'orquestrador i cobreix selected rows, candidate source i contributors.
  - `metrics_runtime.py` ja exposa adapters bound per metriques, desempats i pipeline maps.
  - `victories.py` ja exposa adapters bound per al mode `mode_resultat_aparells=victories`.
  - `teams.py` ja agrupa i compon rows d'equip des de l'orquestrador.
  - `detail_payload.py` i `ranking.py` continuen sent els owners del detail/display i del ranking.
- L'orquestrador encara no es "prim". El fitxer segueix contenint molt codi duplicat del snapshot legacy, pero l'execucio efectiva ja consumeix els runtimes nous per:
  - selection
  - metrics/ties
  - victories
  - teams
  - detail/display
- Validacio executada en aquesta iteracio:
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.test_engine_selection_runtime competicions_trampoli.tests.scoring.test_engine_metrics_runtime competicions_trampoli.tests.equips.test_engine_team_runtime competicions_trampoli.tests.classificacions.test_compute_engine_parity --verbosity 1`
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.classificacions.test_filters competicions_trampoli.tests.equips.test_classificacio_integration competicions_trampoli.tests.scoring.team.test_classificacio_detail_sections competicions_trampoli.tests.inscripcions.groups.test_birth_ranges --verbosity 1`
- Resultat: `24 + 47` tests en verd.
- Conclusio d'estat:
  - Fase 1, 2 i 3: completes a efectes practics
  - Fase 4: completada funcionalment
  - Fase 5: pendent de completar fisicament
  - Fase 6: funcionalment feta
  - Fase 7 i 8: pendents
- Seguent pas recomanat:
  - entrar a Fase 5 per aprimar `engine/orchestrator.py`
  - substituir blocs locals morts per imports directes o eliminar-los
  - deixar l'orquestrador com a compositor real de fases
  - ampliar una mica mes la paritat abans d'eliminar el legacy
- Actualitzacio Fase 5 - primera passada:
  - eliminat del `compute path` el bloc local de `victories` a `engine/orchestrator.py`
  - eliminats els helpers inline de `detail payload` dins `compute_classificacio()`, ja que el cami actiu passa per `engine/detail_payload.py`
  - la validacio continua verda amb la mateixa bateria de `24 + 47` tests
  - encara queden pendents dins `engine/orchestrator.py`:
    - `_rank_v2` local residual
    - helpers locals de `ties`
    - bloc gran de selection local definit dins `compute_classificacio()` i sobreescrit posteriorment per `selection_runtime`
    - config d'equips encara owned localment
  - conclusio:
    - Fase 5 esta començada i validada
    - cal una segona passada per completar l'aprimament fisic del fitxer

- Actualitzacio Fase 5 - tancament fisic:
  - orquestracio implementada amb subagents d'auditoria S5.A, S5.B i S5.C, mantenint `engine/orchestrator.py` com a write scope exclusiu de l'integrador.
  - eliminat el bloc local de `selection` dins `compute_classificacio()` que quedava sobreescrit per `selection_runtime`.
  - eliminats els blocs locals de metriques/pipeline i detail/display ja substituits per `metrics_runtime` i `detail_payload`.
  - eliminats residus locals de `score_values` i `_rank_v2`; el cami actiu usa els owners nous.
  - `engine/orchestrator.py` passa aproximadament de 5.676 linies a 2.447 linies.
  - validacio executada:
    - `docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.test_engine_selection_runtime competicions_trampoli.tests.scoring.test_engine_metrics_runtime competicions_trampoli.tests.equips.test_engine_team_runtime competicions_trampoli.tests.classificacions.test_compute_engine_parity competicions_trampoli.tests.scoring.team.test_classificacio_detail_sections --verbosity 1`
  - resultat: `51` tests en verd.
  - conclusio:
    - Fase 5 queda tancada a efectes practics.
    - Queden duplicats top-level de compatibilitat a aprimar en Fase 8 o abans de retirar el legacy, sobretot schema/common/particions, pero ja no bloquegen el compositor runtime.
    - Fase 7 pendent: ampliar paritat i eliminar `services/legacy/services_classificacions_2.py`.

## Decisions Tancades
- `compute.py` continua sent la frontera publica.
- La logica nova no es reparteix al nivell superior de `services/classificacions/`.
- La logica nova viu dins d'un subpaquet nou:
  - `competicions_trampoli/services/classificacions/engine/`
- `filters.py` i `partitions.py` continuen sent boundaries publics de normalitzacio.
- El nou `engine` pot consumir `filters.py`, `partitions.py`, `pipeline_runtime.py`, `provenance/` i `ties/`, pero no ha de tornar a crear un nou monolit intern.
- `services_classificacions_2.py` es mante durant la migracio com a oracle temporal i es retira al final.

## No Objectius
- No redissenyar la shape del resultat de compute.
- No canviar `views`, `export`, `live`, `builder` o `validation` fora del necessari per consumir la nova frontera.
- No reescriure `pipeline_runtime.py`.
- No canviar contractes de `desempat` mes enlla del que calgui per desacoblar el compute.
- No optimitzar SQL ni perf com a objectiu principal d'aquesta fase.

## Arquitectura Objectiu

```text
competicions_trampoli/services/classificacions/
  compute.py
  filters.py
  partitions.py
  pipeline_runtime.py
  provenance/
  ties/
  engine/
    __init__.py
    common.py
    model_utils.py
    schema.py
    loaders.py
    score_values.py
    filter_runtime.py
    partition_runtime.py
    selection.py
    selection_runtime.py
    metrics_runtime.py
    victories.py
    teams.py
    detail_payload.py
    ranking.py
    orchestrator.py
```

## Responsabilitat De Cada Modul Objectiu

### `engine/common.py`
- clones JSON defensius
- enters positius
- normalitzacio textual
- deduplicacio d'ids
- helpers petits shared que avui estan duplicats dins del monolit

### `engine/model_utils.py`
- `_is_relational_field`
- `_filter_in`
- `_display_value`

### `engine/schema.py`
- owner unic de `DEFAULT_SCHEMA` complet del compute
- merge i normalitzacio final del schema de compute
- adaptacio temporal amb `filters.py` i `partitions.py`

### `engine/loaders.py`
- carrega `CompeticioAparell`, `Inscripcio`, `ScoreEntry`, `TeamScoreEntry`
- construeix indexos base:
  - `notes_by_app`
  - `notes_by_key`
  - `team_notes_by_app`
  - `team_notes_by_key`
  - `ins_ids_by_app`
  - `team_ids_by_app`

### `engine/score_values.py`
- conversions numeriques
- lectura de camps de `ScoreEntry`
- agregacions simples

### `engine/filter_runtime.py`
- matching runtime de filtres sobre inscripcions i membres
- logica de grups normalitzats

### `engine/partition_runtime.py`
- resolucio de valor de particio per inscripcio o equip
- custom labels i claus finals de particio
- particions de rang d'any de naixement en runtime

### `engine/selection.py`
- seleccio d'exercicis
- normalitzacio de `candidate_source`
- seleccio de participants
- resolucio d'agregacions petites i neutrals

### `engine/selection_runtime.py`
- construccio de rows candidats per exercici
- caches de selected rows
- contributors
- resolucio efectiva per app i per field

### `engine/metrics_runtime.py`
- calcul de metriques i desempats
- tie keys
- integracio amb `pipeline_runtime.py`
- `calc_metric_value_for_ins`
- `calc_metric_value_for_group`
- `calc_metric_value_for_native_team`

### `engine/victories.py`
- `mode_resultat_aparells=victories`

### `engine/teams.py`
- resolucio d'equips natius i derivats
- agrupacio de membres
- score per equip i agregacio final

### `engine/detail_payload.py`
- columnes raw
- rows de jutges
- seccions de detall
- `cells`, `display`, `detail`

### `engine/ranking.py`
- `_rank_v2`

### `engine/orchestrator.py`
- nou `compute_classificacio()`
- coordina fases i moduls
- no conte logica pesada de negoci

## Mapa De Migracio Fitxer Actual -> Fitxer Nou

### Des de `services_classificacions_2.py`
- capcalera i constants shared -> `engine/common.py`, `engine/schema.py`
- helpers ORM i display -> `engine/model_utils.py`
- filtres runtime -> `engine/filter_runtime.py`
- particions runtime -> `engine/partition_runtime.py`
- valors i agregacions -> `engine/score_values.py`
- seleccio d'exercicis i participants -> `engine/selection.py`
- selected rows i contributors -> `engine/selection_runtime.py`
- desempats i pipeline -> `engine/metrics_runtime.py`
- victories -> `engine/victories.py`
- equips -> `engine/teams.py`
- payload raw/detail/display -> `engine/detail_payload.py`
- ranking -> `engine/ranking.py`
- `compute_classificacio()` -> `engine/orchestrator.py`

## Invariants De No Regressio

### Imports publics
- `from ...services.classificacions.compute import DEFAULT_SCHEMA, compute_classificacio`
  ha de continuar funcionant.

### Sortida
- s'han de mantenir claus com:
  - `participant`
  - `entitat_nom`
  - `score`
  - `tie`
  - `punts`
  - `posicio`
  - `by_app`
  - `by_app_base`
  - `cells`
  - `display`
  - `detail` si aplica

### Modes
- `individual`
- `entitat`
- `equips` amb:
  - `derived_from_individual`
  - `native_team`

### Cobertura critica a preservar
- filtres de membres i equips
- detail sections
- raw columns
- `team_pool`
- `per_member`
- `global_pool`
- particions per rang d'edat/any de naixement
- `victories`

## Estrategia D'Orquestracio

### Regles
- Cap subagent no edita simultaniament el mateix fitxer.
- Els subagents creen o modifiquen nomes els fitxers del seu write set.
- L'integrador es l'unic que toca:
  - `engine/orchestrator.py`
  - `services/classificacions/compute.py`
  - `services/classificacions/_compute_bridge.py`
  - eliminacio final de codi legacy
- Cada fase ha d'acabar amb codi integrable.
- No es permet deixar un modul nou mig connectat si encara no hi ha tests o bridge temporal per sostenir-lo.

### Protocol De Handoff
- Cada subagent ha d'entregar:
  - fitxers tocats
  - quines funcions ha mogut
  - quines dependencies espera
  - quins tests ha afegit o tocat
  - quins punts segueixen depenent del monolit

## Fase 0. Congelar Contracte I Mapa De Fitxers

### Owner
- Integrador principal

### Write set
- aquest document

### Objectiu
- congelar noms de mòduls
- congelar write scopes
- congelar ordre d'integracio

### Done
- arbre objectiu acceptat
- phases acceptades
- sense solapament de write scopes entre subagents

## Fase 1. Crear El Paquet `engine` I Shared Primitives

### Objectiu
- preparar els mòduls compartits que bloquegen la resta de feina paral.lela

## Subagent S1.1 - Skeleton del paquet
### Write set
- `competicions_trampoli/services/classificacions/engine/__init__.py`
- `competicions_trampoli/services/classificacions/engine/common.py`
- `competicions_trampoli/services/classificacions/engine/model_utils.py`

### Tasques
- crear el subpaquet
- moure o reimplementar sense canvis funcionals:
  - json clone petit
  - `normalize_positive_int`
  - `normalized_text_token`
  - dedupe ids
  - `_is_relational_field`
  - `_filter_in`
  - `_display_value`

### Restriccions
- no tocar encara `compute.py`
- no moure l'orquestracio

### Done
- mòduls nous importables
- zero dependencies circulars

## Subagent S1.2 - Harness de paritat
### Write set
- `competicions_trampoli/tests/classificacions/test_compute_engine_parity.py`

### Tasques
- crear harness de comparacio:
  - runtime legacy actual
  - runtime nou futur
- preparar fixtures minimals per comparar sortides parcials o finals

### Restriccions
- pot usar skip temporals o imports condicionals fins que hi hagi orquestrador nou
- no tocar tests existents fora del seu write set

### Done
- existeix un lloc central per afegir casos de paritat fase a fase

## Dependencia
- cap feina de fases 2-5 no ha d'arrencar sense aquesta fase mergejada

## Fase 2. Extreure Mòduls Fulla En Paral.lel

### Objectiu
- extreure els blocs amb menys dependencies creuades

## Subagent S2.1 - Score values
### Write set
- `competicions_trampoli/services/classificacions/engine/score_values.py`
- tests nous o ajustats sota:
  - `competicions_trampoli/tests/scoring/`

### Tasques
- extreure:
  - `_to_float`
  - `_try_strict_float`
  - `_numeric_scalar_or_1x1`
  - `_field_value_from_entry`
  - `_get_score_field`
  - `_median`
  - `_apply_simple_agg`

### Done
- modul pur amb tests d'unitat propis

## Subagent S2.2 - Selection pura
### Write set
- `competicions_trampoli/services/classificacions/engine/selection.py`
- tests nous sota:
  - `competicions_trampoli/tests/scoring/`

### Tasques
- extreure:
  - `_pick_exercicis`
  - `_pick_exercicis_rows`
  - `_pick_exercicis_tuples`
  - `_normalize_exercicis_cfg`
  - `_normalize_candidate_source_mode`
  - `_normalize_candidate_source_cfg`
  - `_normalize_field_mode`
  - `_normalize_optional_agg`
  - `_pick_participants`
  - `_normalize_participants_cfg`

### Done
- modul pur sense ORM

## Subagent S2.3 - Ranking
### Write set
- `competicions_trampoli/services/classificacions/engine/ranking.py`
- tests nous sota:
  - `competicions_trampoli/tests/classificacions/`

### Tasques
- extreure `_rank_v2`

### Done
- ranking desacoblat del monolit

## Subagent S2.4 - Victories
### Write set
- `competicions_trampoli/services/classificacions/engine/victories.py`
- tests nous sota:
  - `competicions_trampoli/tests/scoring/`

### Tasques
- extreure:
  - `_normalize_mode_resultat_aparells`
  - `_sanitize_victories_compare_ties`
  - `_normalize_victories_cfg`
  - `_row_base_for_app`
  - `_row_has_app`
  - `_compute_victory_points_for_entries`
  - `_apply_victories_per_app_to_rows`

### Done
- modul sense dependencies d'orquestracio dura

## Subagent S2.5 - Runtime de filtres
### Write set
- `competicions_trampoli/services/classificacions/engine/filter_runtime.py`
- tests nous sota:
  - `competicions_trampoli/tests/classificacions/`
  - `competicions_trampoli/tests/scoring/team/`

### Tasques
- extreure:
  - `_normalized_group_filter_value`
  - `_inscripcio_matches_filter_field`
  - `_inscripcio_matches_classificacio_filters`
  - `_native_team_members_match_classificacio_filters`

### Restriccions
- no tocar `filters.py` public excepte imports menors si cal

### Done
- matching runtime separat de la normalitzacio publica

## Subagent S2.6 - Runtime de particions
### Write set
- `competicions_trampoli/services/classificacions/engine/partition_runtime.py`
- tests nous sota:
  - `competicions_trampoli/tests/inscripcions/groups/`
  - `competicions_trampoli/tests/classificacions/`

### Tasques
- extreure:
  - `_inscripcio_value_for_partition`
  - `_birth_year_range_partition_value`
  - `_birth_year_range_partition_value_for_team`
  - `_build_particions_custom_index`
  - `_resolve_partition_display`
  - `_partition_key_from_entries`
  - `_partition_key_from_entries_for_team`
  - `_years_old`
  - `_bucket_edat`
  - `_resolve_particio_equip`

### Done
- claus de particio resoltes fora del monolit

## Fase 3. Extreure Schema I Loaders

### Objectiu
- separar entrada i pretractament del compute

## Subagent S3.1 - Schema owner unic
### Write set
- `competicions_trampoli/services/classificacions/engine/schema.py`
- `competicions_trampoli/services/classificacions/compute.py`

### Tasques
- crear owner unic de `DEFAULT_SCHEMA`
- encapsular merge final de schema
- fer que `compute.py` importi `DEFAULT_SCHEMA` des del mòdul nou quan sigui segur

### Restriccions
- no tallar encara el bridge de compute

### Done
- `DEFAULT_SCHEMA` deixa de dependre del legacy

## Subagent S3.2 - Loaders ORM
### Write set
- `competicions_trampoli/services/classificacions/engine/loaders.py`
- tests nous sota:
  - `competicions_trampoli/tests/classificacions/`
  - `competicions_trampoli/tests/equips/`

### Tasques
- extreure la carrega de:
  - aparells
  - inscripcions
  - score entries
  - team score entries
- construir indexos canònics

### Done
- queries principals fora de l'orquestrador

## Fase 4. Extreure Runtime Pesat Amb Paral.lelisme Controlat

### Objectiu
- treure el nucli que avui viu com a funcions internes de `compute_classificacio()`

## Subagent S4.1 - Selection runtime
### Write set
- `competicions_trampoli/services/classificacions/engine/selection_runtime.py`
- tests nous sota:
  - `competicions_trampoli/tests/scoring/team/`
  - `competicions_trampoli/tests/classificacions/`

### Tasques
- extreure:
  - resolvers per app
  - `_score_camps_for_app`
  - `resolve_score_fields_for_app_exercise`
  - `_resolve_ex_cfg_for_app`
  - `_copy_ex_row_with_value`
  - `_merge_source_rows`
  - `_build_candidate_rows_from_source_rows`
  - families `_get_selected_rows_*`
  - families `_get_main_selected_*`
  - contributors

### Restriccions
- no tocar desempats ni detail payload

### Done
- selected rows i candidate source fora del monolit

## Subagent S4.2 - Metrics runtime
### Write set
- `competicions_trampoli/services/classificacions/engine/metrics_runtime.py`
- tests nous sota:
  - `competicions_trampoli/tests/scoring/team/`
  - `competicions_trampoli/tests/classificacions/`

### Tasques
- extreure:
  - `_normalize_tie_camps`
  - `_is_pipeline_tie`
  - `_pipeline_tie_signature`
  - `_tie_key`
  - `_pipeline_subject_key`
  - `_sanitize_desempat_for_tipus`
  - `calc_criterion_value`
  - `calc_metric_value_for_ins`
  - `calc_metric_value_for_group`
  - `calc_metric_value_for_native_team`
  - adaptador de runtime al `pipeline_runtime.py`

### Restriccions
- no tocar `ties/` ni `pipeline_runtime.py` fora del necessari per imports

### Done
- desempats calculables sense tancar-se al monolit

## Subagent S4.3 - Teams runtime
### Write set
- `competicions_trampoli/services/classificacions/engine/teams.py`
- tests nous sota:
  - `competicions_trampoli/tests/equips/`
  - `competicions_trampoli/tests/scoring/team/`

### Tasques
- extreure:
  - `_legacy_native_equip_for_classificacio`
  - `_resolve_inscripcio_equip_for_classificacio`
  - resolucio de `grouped`
  - score per equip
  - composicio final de rows d'equip

### Restriccions
- no generar detall UI aqui

### Done
- equip runtime separat de l'orquestrador

## Subagent S4.4 - Detail payload
### Write set
- `competicions_trampoli/services/classificacions/engine/detail_payload.py`
- tests nous sota:
  - `competicions_trampoli/tests/scoring/team/test_classificacio_detail_sections.py`

### Tasques
- extreure:
  - raw value helpers
  - judge rows helpers
  - builtin/detail helpers
  - section builders
  - `_build_detail_payload`
  - `_attach_display_cells`

### Restriccions
- no tocar ranking
- no tocar team grouping

### Done
- render de detail fora del monolit

## Fase 5. Construir L'Orquestrador Nou

### Owner
- Integrador principal

### Write set
- `competicions_trampoli/services/classificacions/engine/orchestrator.py`
- `competicions_trampoli/services/classificacions/engine/__init__.py`

### Objectiu
- composar els moduls nous en un nou `compute_classificacio()`

### Tasques
- preparar pipeline d'execucio:
  1. schema
  2. config runtime
  3. loaders
  4. per-ins base
  5. metrics/ties
  6. victories si aplica
  7. particions
  8. rows finals per tipus
  9. ranking
  10. display/detail
- mantenir el monolit com a oracle de referencia mentre no hi hagi paritat suficient

### Done
- el nou orquestrador retorna resultats compatibles en els casos coberts

## Fase 6. Cutover Del Bridge

### Owner
- Integrador principal

### Write set
- `competicions_trampoli/services/classificacions/compute.py`
- `competicions_trampoli/services/classificacions/_compute_bridge.py`

### Tasques
- canviar `compute.py` per apuntar a `engine/orchestrator.py`
- deixar `_compute_bridge.py` com a compat temporal o eliminar-lo si ja no aporta res

### Restriccions
- cap subagent extern toca aquests fitxers

### Done
- els consumidors publics ja no depenen del legacy

## Fase 7. Eliminacio Del Legacy

### Owner
- Integrador principal

### Write set
- `competicions_trampoli/services/legacy/services_classificacions_2.py`
- imports residuals afectats

### Tasques
- eliminar codi ja migrat
- preservar, si cal, wrappers temporals minimals
- actualitzar comentaris i imports morts

### Restriccions
- nomes quan la suite i la paritat estiguin verdes

### Done
- el compute ja no depen del fitxer monolitic

## Fase 8. Consolidacio Final

### Objectiu
- deixar l'estructura nova ben lligada

### Tasques
- revisar dependencies circulars
- revisar `__all__`
- revisar docstrings curtes dels mòduls
- afegir document curt d'arquitectura del `engine` si cal

### Done
- estructura final coherent
- sense bridges innecessaris

## Matriu De Dependencies

### Bloquejants primers
- Fase 1 abans de Fases 2-5

### Poden anar en paral.lel
- S2.1
- S2.2
- S2.3
- S2.4
- S2.5
- S2.6

### Requereixen fase 2 feta o gairebe feta
- S3.1
- S3.2
- S4.1
- S4.2
- S4.3
- S4.4

### Exclusius de l'integrador
- Fase 5
- Fase 6
- Fase 7
- Fase 8

## Tests I Verificacio

## Suite minima obligatoria per fase
- `competicions_trampoli/tests/classificacions/test_filters.py`
- `competicions_trampoli/tests/equips/test_classificacio_integration.py`
- `competicions_trampoli/tests/scoring/team/test_classificacio_filters_and_validation.py`
- `competicions_trampoli/tests/scoring/team/test_classificacio_detail_sections.py`
- `competicions_trampoli/tests/inscripcions/groups/test_birth_ranges.py`

## Suite de fum obligatoria al cutover
- `competicions_trampoli/tests/classificacions/test_backend_smoke.py`
- `competicions_trampoli/tests/classificacions/test_live_cache.py`
- `competicions_trampoli/tests/classificacions/test_export_excel.py`

## Test nou recomanat de paritat
- `competicions_trampoli/tests/classificacions/test_compute_engine_parity.py`

### Casos que la paritat ha de cobrir
- individual simple
- entitat simple
- derived team amb `per_member`
- derived team amb `team_pool`
- native team
- detail sections raw
- filtres de grup
- particions per rang de naixement
- victories

## Guardrails Per A Subagents

### Prohibit
- tocar `engine/orchestrator.py` si no ets l'integrador
- tocar `compute.py` si no ets l'integrador
- retocar comportament "de passada"
- fer neteja de noms o reestils fora del write set
- reordenar imports d'altres fitxers sense necessitat funcional

### Obligatori
- afegir tests de la part extreta
- mantenir el comportament actual
- documentar al handoff quines funcions ja no s'han d'importar del monolit

## Riscos Principals
- dependencies circulars entre `selection_runtime`, `metrics_runtime`, `teams` i `detail_payload`
- desempat pipeline consumint helpers encara enganxats al monolit
- regressions subtils a `detail`
- duplicacio temporal de `DEFAULT_SCHEMA`
- drift entre helpers ja extrets a `filters.py` / `partitions.py` i el runtime nou

## Mitigacions
- shared primitives a Fase 1
- modules fulla abans dels pesats
- un sol owner per `DEFAULT_SCHEMA`
- integrador unic per al cutover
- harness de paritat abans del tall final

## Criteri De Tancament
- `compute.py` deixa d'importar del legacy
- `services_classificacions_2.py` ja no es usa pel runtime public
- els tests critics de classificacions passen
- la nova estructura te responsabilidades clares i sense monolit reempaquetat

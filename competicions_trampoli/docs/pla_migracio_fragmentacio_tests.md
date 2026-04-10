# Pla De Migracio De Fragmentacio Del Paquet De Tests

## Resum Executiu

Faria la migracio en **6 fases**.

L'objectiu no es reescriure tests ni canviar cobertura funcional, sino **moure'ls a fitxers i paquets mes petits**, amb imports estables i amb el minim risc de regressio estructural.

Aquest document esta pensat perque **diversos agents en paral.lel i amb poc context** puguin executar la migracio amb exit.

## Estat De Tancament

- La migracio queda tancada quan el nou arbre sota `competicions_trampoli/tests/` es l'unica superficie executable oficial.
- `competicions_trampoli/tests/__init__.py` ha de ser minim i no ha d'importar wrappers legacy.
- Els antics fitxers `competicions_trampoli/tests/test_*.py` s'han de retirar del discovery; no hi ha compatibilitat temporal dins el patró `test*.py`.
- Runner oficial: `docker compose run --rm web python manage.py test competicions_trampoli.tests --verbosity 1`

## Objectiu

- Reduir la mida dels fitxers-monolit.
- Fer que cada fitxer de tests tingui una responsabilitat clara.
- Permetre trobar un test per domini sense navegar per milers de linies.
- Evitar conflictes de merge entre agents.
- Mantenir el paquet `competicions_trampoli.tests` funcional durant tota la migracio.

## No Objectius

- No canviar el comportament dels tests.
- No canviar l'API productiva.
- No fer refactors de negoci aprofitant la migracio.
- No reanomenar tests si no es estrictament necessari.

## Estat Actual Que Motiva La Migracio

- `test_team_scoring.py`: 7016 linies, 162 tests.
- `test_classificacions.py`: 5024 linies, 125 tests.
- `test_inscripcions_sort_groups.py`: 3925 linies, 102 tests.
- `test_equips_context.py`: 1301 linies, 34 tests.
- `test_scoring_judge.py`: 1300 linies, 39 tests.

## Estructura Objectiu

```text
competicions_trampoli/tests/
  base.py
  __init__.py

  architecture/
    test_architecture_canonicity.py
    test_migrations.py

  access/
    test_competition_access.py
    test_aparell_catalog_ownership.py
    test_public_live_tokens.py

  ui/
    test_competicio_background_template.py

  scoring/
    test_engine_alias_resolution.py

    judge/
      test_media_context.py
      test_exclusions_and_partial_save.py
      test_video_api.py
      test_messages.py
      test_updates_cursor.py
      test_package_contract.py

    team/
      test_member_treatment_schema.py
      test_builder_and_schema_resolution.py
      test_scoring_and_judge_permissions.py
      test_classificacio_compute_modes.py
      test_classificacio_detail_sections.py
      test_classificacio_filters_and_validation.py
      test_birth_partitions.py
      test_series_workspace.py
      test_updates_and_notes.py
      test_rotacions_integration.py

  classificacions/
    test_backend_smoke.py
    test_compute_core.py
    test_schema_validation.py
    test_partitions.py
    test_victories.py
    test_builder_hydration.py
    test_filters.py
    test_export_excel.py
    test_templates_competition.py
    test_templates_global.py
    test_live_cache.py

  equips/
    test_context_flow.py
    test_workspace_ui.py
    test_preview_and_autocreate.py
    test_classificacio_integration.py
    test_history_and_audit.py

  inscripcions/
    test_backend_smoke.py
    test_excel_import.py
    test_manual_form.py
    test_aparell_exclusions.py
    test_media_flow.py

    groups/
      test_birth_ranges.py
      test_filters_and_sort_stack.py
      test_custom_order_and_history.py
      test_preview_and_apply.py
      test_reconfiguration.py
      test_workspace_contracts.py

  rotacions/
    test_ordering_display.py
    test_competitive_timing.py
    test_visual_ordering.py
    test_package_contract.py
```

## Regles Globals De Migracio

- Moure tests sense canviar assertions ni fixtures, excepte imports.
- Si una classe es mantingues intacta, preferir moure la classe sencera abans que partir-la.
- Si una classe gegant es fragmenta per subdominis, fer-ho en talls tematics i estables.
- No deixar imports circulars entre fitxers de tests.
- Mantenir `base.py` com a lloc unic per al mixin `_BaseTrampoliDataMixin` tret que hi hagi una necessitat clara de nous mixins compartits.
- Reduir al minim el codi duplicat introduit per la migracio.
- Cada PR d'agent ha d'incloure una actualitzacio coherent de `competicions_trampoli/tests/__init__.py` si aquest fitxer continua sent necessari.
- Si es decideix buidar o simplificar `__init__.py`, aquesta decisio s'ha de fer en una fase dedicada i no de forma accidental.

## Convencions Per A Agents En Paral.lel

### Regles d'ownership

- Cada agent rep un **subarbre exclusiu** de `competicions_trampoli/tests`.
- Un agent no ha d'editar fitxers fora del seu scope, excepte el coordinador.
- El coordinador es l'unic que toca:
  - `competicions_trampoli/tests/__init__.py`
  - indexs o docs de seguiment
  - ajustos finals de compatibilitat

### Regles de moviment

- Primer crear el fitxer nou.
- Despres copiar o moure la classe o bloc de tests.
- Despres ajustar imports locals.
- Despres eliminar el bloc antic del monolit.
- Despres executar els tests del fitxer nou.

### Regles de validacio minima per PR

- Els tests del nou fitxer passen.
- El fitxer origen continua passant si encara existeix.
- No queden classes duplicades carregades a dos moduls amb el mateix nom si el discovery les executaria dues vegades.
- `rg` sobre el nom de classe ha de tornar una sola definicio final.

## Fases

## Fase 0. Preparacio I Contracte De Migracio

### Objectiu

Fixar l'estrategia comun, evitar que cada agent improvisi i crear l'esquelet de paquets.

### Responsable

- 1 agent coordinador.

### Tasques

- Crear els nous directoris paquet amb `__init__.py` minim:
  - `tests/access`
  - `tests/architecture`
  - `tests/classificacions`
  - `tests/equips`
  - `tests/inscripcions`
  - `tests/inscripcions/groups`
  - `tests/rotacions`
  - `tests/scoring`
  - `tests/scoring/judge`
  - `tests/scoring/team`
  - `tests/ui`
- Decidir si `tests/__init__.py` es mantindra com a facade temporal o es buidara al final.
- Deixar aquest document i, si cal, un checklist curt de seguiment.

### Dependencies

- Cap.

### Criteri De Done

- L'arbre objectiu existeix.
- El paquet es pot importar.
- La resta d'agents ja poden treballar en scopes disjunts.

## Fase 1. Extraccions De Baix Risc I 1 Classe = 1 Fitxer

### Objectiu

Treure del mig les parts evidents i cohesionades, sense tocar encara els monolits grans per dins.

### Workstreams En Paral.lel

- Agent A: `tests/access/*`
- Agent B: `tests/architecture/*`
- Agent C: `tests/rotacions/*`
- Agent D: `tests/scoring/judge/*`
- Agent E: `tests/ui/test_competicio_background_template.py` i `tests/scoring/test_engine_alias_resolution.py`
- Agent F: `tests/inscripcions/test_manual_form.py`, `tests/inscripcions/test_aparell_exclusions.py`, `tests/inscripcions/test_media_flow.py`

### Fonts Actuals

- `test_access_and_catalog.py`
- `test_architecture_canonicity.py`
- `test_migrations.py`
- `test_rotacions.py`
- `test_scoring_judge.py`
- `test_templates_and_sort_basics.py`
- `test_inscripcions_forms_media.py`

### Criteri De Tall

- Una classe sencera actual es converteix en un fitxer nou si ja te un ambit clar.

### Criteri De Done

- Els fitxers de destinacio existeixen i passen.
- Els monolits originals s'han reduit o eliminat sense duplicar classes.

## Fase 2. Refactor D'Inscripcions I Equips

### Objectiu

Fragmentar dominis grans pero encara raonables: `inscripcions_sort_groups.py`, `inscripcions_backend_smoke.py` i `equips_context.py`.

### Workstreams En Paral.lel

- Agent G: `tests/inscripcions/test_backend_smoke.py`
- Agent H: `tests/inscripcions/test_excel_import.py`
- Agent I: `tests/inscripcions/groups/test_birth_ranges.py`
- Agent J: `tests/inscripcions/groups/test_filters_and_sort_stack.py`
- Agent K: `tests/inscripcions/groups/test_custom_order_and_history.py`
- Agent L: `tests/inscripcions/groups/test_preview_and_apply.py`
- Agent M: `tests/inscripcions/groups/test_reconfiguration.py`
- Agent N: `tests/inscripcions/groups/test_workspace_contracts.py`
- Agent O: `tests/equips/test_context_flow.py`
- Agent P: `tests/equips/test_workspace_ui.py`
- Agent Q: `tests/equips/test_preview_and_autocreate.py`
- Agent R: `tests/equips/test_classificacio_integration.py`
- Agent S: `tests/equips/test_history_and_audit.py`

### Tall Proposat Per `test_inscripcions_sort_groups.py`

- `test_birth_ranges.py`
  - configuracio i preview de `birth year ranges`
- `test_filters_and_sort_stack.py`
  - filtres, sort context, tail order i stack de sorting
- `test_custom_order_and_history.py`
  - custom order, history, reorder i wrappers legacy
- `test_preview_and_apply.py`
  - `groups_preview_*` i `groups_apply_*`
- `test_reconfiguration.py`
  - `GroupNameSyncTests` i `ProgrammedGroupReconfigurationTests`
- `test_workspace_contracts.py`
  - `GroupManagerV1Tests`

### Tall Proposat Per `test_equips_context.py`

- `test_context_flow.py`
  - flux minim i mutacions de context base
- `test_workspace_ui.py`
  - shell del workspace, filtres, resolucio de seleccio, membres
- `test_preview_and_autocreate.py`
  - `equips_preview_*` i `equips_auto_create_*`
- `test_classificacio_integration.py`
  - `EquipContextClassificacioTests`
- `test_history_and_audit.py`
  - `EquipContextHistorySnapshotTests`
  - `BaseTeamContextAuditCommandTests`

### Criteri De Done

- `test_inscripcions_sort_groups.py` ha desaparegut o ha quedat buit pendent d'eliminacio immediata.
- `test_equips_context.py` ha desaparegut o ha quedat reduit a zero.
- No hi ha solapament entre agents en els mateixos fitxers.

## Fase 3. Fragmentacio De `test_classificacions.py`

### Objectiu

Separar clarament calcul, validacio, templates, export i live cache.

### Workstreams En Paral.lel

- Agent T: `tests/classificacions/test_backend_smoke.py`
- Agent U: `tests/classificacions/test_compute_core.py`
- Agent V: `tests/classificacions/test_schema_validation.py`
- Agent W: `tests/classificacions/test_partitions.py`
- Agent X: `tests/classificacions/test_victories.py`
- Agent Y: `tests/classificacions/test_builder_hydration.py`
- Agent Z: `tests/classificacions/test_filters.py`
- Agent AA: `tests/classificacions/test_export_excel.py`
- Agent AB: `tests/classificacions/test_templates_competition.py`
- Agent AC: `tests/classificacions/test_templates_global.py`
- Agent AD: `tests/classificacions/test_live_cache.py`

### Tall Proposat

- `test_compute_core.py`
  - `test_compute_classificacio_*` no relacionats amb partitions ni victories
  - errors de preview de compute
- `test_schema_validation.py`
  - `test_classificacio_save_*` generals
  - canonicalitzacio, tie pipeline, mode resolution, candidate source
- `test_partitions.py`
  - custom partitions
  - birth year ranges
  - validacions de particio
- `test_victories.py`
  - tots els `*_victories_*`
  - validacions de `save` especifiques d'aquest mode
- `test_builder_hydration.py`
  - `ClassificacioBuilderHydrationTests`
  - helpers estrictament lligats al builder
- `test_filters.py`
  - `ClassificacioFilterSemanticsTests`
- `test_export_excel.py`
  - `ClassificacionsExportExcelTests`
- `test_templates_competition.py`
  - `ClassificacioTemplateFlowTests`
- `test_templates_global.py`
  - `GlobalClassificacioTemplateManagementTests`
- `test_live_cache.py`
  - `LiveClassificacionsRedisCacheTests`

### Dependencies

- Fase 0 completada.
- No depen de la fragmentacio de `team_scoring`.

### Criteri De Done

- `test_classificacions.py` eliminat.
- Les noves suites tenen noms coherents i responsabilitat unica.

## Fase 4. Fragmentacio De `test_team_scoring.py`

### Objectiu

Atacar el monolit mes gran al final, quan la resta del paquet ja esta ordenat i hi ha menys soroll de merge.

### Requisit Previ

- Fases 1, 2 i 3 completades.

### Per Que Va Al Final

- Barreja scoring, judge, classificacions, series, notes, updates i integracio amb rotacions.
- Te moltes dependencies conceptuals amb els dominis ja separats.
- Es el fitxer amb mes risc de tall incorrecte.

### Workstreams En Paral.lel

- Agent AE: `tests/scoring/team/test_member_treatment_schema.py`
- Agent AF: `tests/scoring/team/test_builder_and_schema_resolution.py`
- Agent AG: `tests/scoring/team/test_scoring_and_judge_permissions.py`
- Agent AH: `tests/scoring/team/test_classificacio_compute_modes.py`
- Agent AI: `tests/scoring/team/test_classificacio_detail_sections.py`
- Agent AJ: `tests/scoring/team/test_classificacio_filters_and_validation.py`
- Agent AK: `tests/scoring/team/test_birth_partitions.py`
- Agent AL: `tests/scoring/team/test_series_workspace.py`
- Agent AM: `tests/scoring/team/test_updates_and_notes.py`
- Agent AN: `tests/scoring/team/test_rotacions_integration.py`

### Tall Proposat

- `test_member_treatment_schema.py`
  - `TeamMemberTreatmentSchemaTests`
- `test_builder_and_schema_resolution.py`
  - builder context
  - scoring schema builder
  - metric meta
  - schema resolution
  - scoreable codes
  - contracte de form d'aparell
- `test_scoring_and_judge_permissions.py`
  - scoring save partial per equips
  - permisos runtime
  - judge admin
  - judge portal
  - media i video sobre team subject
- `test_classificacio_compute_modes.py`
  - compute amb `TeamScoreEntry`
  - native team vs derived team
  - team pool i global pool
  - tie break principal
- `test_classificacio_detail_sections.py`
  - raw columns
  - detail payloads
  - detail sections
  - team members tables
  - export excel normalitzat per team raw detail
- `test_classificacio_filters_and_validation.py`
  - filtres de membres i grups
  - save/validation de detail schema
  - aggregates i exercise selection scope
  - stale native context i capability flags
- `test_birth_partitions.py`
  - tots els `*_birth_partition_*`
  - normalitzacio de team age partition legacy
- `test_series_workspace.py`
  - tots els `series_*`
  - navegacio de series a inscripcions
- `test_updates_and_notes.py`
  - `scoring_updates_*`
  - `judge_updates_*`
  - `scoring_notes_home_*`
  - feeds combinats
- `test_rotacions_integration.py`
  - `rotacions_*` lligats a team series

### Criteri De Done

- `test_team_scoring.py` eliminat.
- Cada fitxer nou queda per sota d'un llindar orientatiu de 1200-1500 linies.

## Fase 5. Consolidacio, Compatibilitat I Verificacio Final

### Objectiu

Tancar la migracio sense detritus estructural.

### Responsable

- 1 agent coordinador.

### Tasques

- Revisar i simplificar `competicions_trampoli/tests/__init__.py`.
- Eliminar fitxers monolit antics que hagin quedat buits o obsolets.
- Verificar que el discovery de Django o pytest no executa el mateix test dues vegades.
- Verificar imports trencats o rutes de mòduls antigues.
- Fer una passada final de noms incoherents.

### Criteri De Done

- L'arbre final coincideix substancialment amb l'objectiu.
- No queden facades temporals innecesaries.
- La suite es pot executar per dominis.

## Ordre De Merge Recomanat

1. Fase 0
2. Fase 1
3. Fase 2
4. Fase 3
5. Fase 4
6. Fase 5

Dins de cada fase, els workstreams en paral.lel poden mergejar-se en qualsevol ordre si:

- no toquen el mateix fitxer
- el coordinador rebaseja `__init__.py` si cal
- cada PR deixa el paquet en estat consistent

## Checklist Operatiu Per A Cada Agent

1. Confirmar el write scope assignat.
2. Crear el fitxer de destinacio.
3. Moure la classe o bloc de tests.
4. Ajustar imports.
5. Eliminar la definicio antiga del fitxer origen.
6. Fer `rg` del nom de classe per confirmar unicitat.
7. Executar la suite del fitxer nou.
8. Revisar que no hi hagi duplicacio de discovery.
9. Deixar una nota curta de quins noms de classes ha mogut.

## Riscos Principals I Mitigacions

### Risc 1. Duplicacio De Tests

Si un agent copia i no elimina, el suite es doblara.

Mitigacio:

- `rg` unicitat obligatori per classe.
- revisio del coordinador abans de merge.

### Risc 2. Solapament A `__init__.py`

Diversos agents editant-lo alhora generaran conflictes.

Mitigacio:

- nomes el coordinador edita `__init__.py`
- la resta d'agents no el toquen

### Risc 3. Tall Tematic Incorrecte

Un bloc de tests pot quedar en un fitxer equivocat i perdre cohesio.

Mitigacio:

- seguir els talls d'aquest document
- si hi ha dubte, prioritzar l'owner del helper o del fixture principal

### Risc 4. Helpers Compartits Replicats

La migracio pot dispersar helpers petits per molts fitxers.

Mitigacio:

- mantenir `base.py` com a punt compartit
- si apareixen nous helpers reals, crear un modul compartit nou nomes en una PR de coordinacio

### Risc 5. Fitxers Nous Encara Massa Grans

Es possible moure un monolit a tres fitxers i continuar malament.

Mitigacio:

- objectiu orientatiu: 200-900 linies per fitxer normal
- maxim tolerable temporal: 1200-1500 en dominis densos

## Criteri Final D'Exit

La migracio es considera completada quan es compleixen tots aquests punts:

- no existeixen `test_team_scoring.py`, `test_classificacions.py` ni `test_inscripcions_sort_groups.py`
- el paquet de tests queda organitzat per dominis
- la majoria de fitxers de tests son llegibles sense scroll massiu
- es poden assignar canvis futurs a subarbres clars sense crear nous monolits
- la suite continua verificant el mateix comportament funcional

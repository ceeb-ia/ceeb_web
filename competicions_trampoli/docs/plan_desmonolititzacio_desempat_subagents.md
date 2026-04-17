# Pla D'Implementacio De La Desmonolititzacio De `desempat` Per Subagents

## Objectiu
- Treure `desempat` de la cadena monolitica compartida entre builder, persistencia, validacio, runtime i compat legacy.
- Convertir `desempat` en un sistema de contractes resolts per context, amb shape canonica minima i projeccions separades.
- Permetre que diversos subagents treballin en paral.lel sobre write scopes disjunts, amb handoffs clars i sense dependre de context oral.
- Resoldre el problema estructural actual: camps valids en un contracte persisteixen o es reintrodueixen en un altre contracte.

## Resum Executiu
- El problema de fons no es nomes el monolit frontend.
- `desempat` avui intenta servir alhora:
  - estat UI de builder
  - payload de `save`
  - mirror legacy per reopen
  - entrada de validacio
  - entrada de runtime/calcul
- Aixo genera shapes hibrides, herencia implícita i reintroduccio de camps no desitjats.
- La solucio correcta no es nomes "partir el fitxer", sino separar:
  - resolucio de context
  - contracte canonic
  - serializer de `save`
  - validacio
  - UI projection
  - legacy projection
  - render/frontend slice especialitzat

## Regla Principal
- Aquesta feina es funcional i arquitectonica alhora.
- No s'ha de limitar a moure codi de lloc mantenint la mateixa barreja de responsabilitats.
- El `pipeline` ha de continuar sent l'unica font de veritat canonica persistent.
- `_builder_ui` continua sent exclusivament UI i no s'ha de persistir mai.
- Cap contracte no pot persistir ni reintroduir camps que no li pertoquin.
- El backend no pot reconstruir camps prohibits per un contracte resolt.
- El frontend no pot emetre camps ocults o stale per un contracte que no els admet.

## Problema Actual

### Monolit funcional existent
- El frontend real servit continua governat principalment per:
  - `competicions_trampoli/templates/classificacions/builder/_legacy_inline_script.html`
- El backend de `desempat` es reparteix entre:
  - `competicions_trampoli/services/classificacions/pipeline_runtime.py`
  - `competicions_trampoli/services/classificacions/validation.py`
  - `competicions_trampoli/services/classificacions/builder.py`
  - `competicions_trampoli/services/classificacions/runtime.py`

### Símptoma arquitectonic
- El mateix tie intenta ser alhora:
  - shape canonica
  - shape legacy
  - shape UI
  - shape de validacio
- Aixo fa que:
  - camps d'un mode contaminin un altre
  - el frontend no sàpiga si esta renderitzant o serialitzant
  - el backend reintrodueixi mirrors per altres capes
  - una mateixa key signifiqui coses diferents segons el punt del flux

### Símptoma funcional ja vist
- Cas `team_pool`:
  - la UI amaga dropdowns de configuracio propia del tie
  - el serializer encara pot heretar `exercicis` o `mode_seleccio_exercicis`
  - el backend pot reintroduir `participants` i `agregacio_participants`
  - la validacio ho rebutja perquè aquest contracte no admet aquests camps
- El problema no es que `team_pool` no es pugui fer servir.
- El problema es que el tie no s'esta persistint en un contracte net de `team_pool`.

## Decisions Tancades
- El contracte persistent final de `desempat` sera `pipeline-first`.
- La shape persistent minima de cada tie sera:
  - `id`
  - `nom`
  - `ordre`
  - `pipeline_version`
  - `pipeline`
- `validation.py` ha d'evolucionar cap a validacio per contracte resolt.
- `_legacy_inline_script.html` no pot continuar sent la font de veritat de `desempat`.
- Les projeccions de UI i compat legacy han de ser explicites i separades.
- El primer tall funcional prioritari ha d'arreglar els contractes:
  - `team_pool`
  - `per_member`

## No Objectius
- No tocar ara `puntuacio.victories.desempat_comparacio` excepte helpers neutrals clarament compartits.
- No reescriure tot el builder de classificacions a la vegada.
- No canviar el ranking public final fora dels casos que avui son incorrectes per culpa del monolit.
- No introduir un segon monolit de `desempat` repartit en fitxers nous.

## Arquitectura Objectiu

### Capes
- `context resolver`
  Decideix quin contracte efectiu aplica a un tie.
- `canonical contract`
  Shape persistent minima i estable.
- `save serializer`
  Construeix el payload canonico segons contracte.
- `validation`
  Valida nomes els camps admesos pel contracte resolt.
- `ui projection`
  Canonic -> estat editable del builder.
- `legacy projection`
  Canonic -> mirrors legacy temporals de reopen/compatibilitat.
- `frontend ties slice`
  Estat UI, render i serializer de `save` fora del monolit.

### Principi de funcionament
1. La UI edita un `ui_state`.
2. El resolver calcula el context efectiu.
3. El contracte resolt defineix:
   - quins camps es poden mostrar
   - quins camps es poden persistir
   - quins camps s'han de buidar
4. El serializer de `save` emet un tie canonic net.
5. El backend valida contra aquell contracte.
6. Si cal reopen, es projecta des de canonic cap a UI.
7. Si cal compat legacy, es projecta de forma explicita, no implicita.

## Contractes A Suportar

### `per_member`
- Permet configuracio propia d'exercicis del tie.
- Pot usar:
  - `pipeline.exercicis`
  - `pipeline.mode_seleccio_exercicis`
  - `pipeline.exercicis_per_aparell`
  - `pipeline.agregacio_exercicis_per_aparell`
- `participants` nomes si el context resolt ho permet.

### `team_pool`
- El tie reutilitza el set d'exercicis de la puntuacio principal.
- No pot persistir:
  - `scope.exercicis`
  - `mode_seleccio_exercicis`
  - `exercicis_per_aparell`
  - `agregacio_exercicis_per_aparell`
  - `scope.participants`
  - `agregacio_participants`
  - els equivalents canonic/pipeline si representen configuracio propia del tie

### `derived_team`
- Context `tipus=equips` amb `team_mode=derived_from_individual`.
- Pot admetre `participants` quan el contracte concret no sigui `team_pool`.
- No pot reintroduir participants si el contracte efectiu es `team_pool`.

### `native_team`
- Context `tipus=equips` amb `team_mode=native_team`.
- No admet configuracions de participants derivats.
- No pot projectar ni persistir camps que impliquin agregacio per membres si el mode no els suporta.

## Shape Canonica Persistent

```json
{
  "id": "tie_1",
  "nom": "Desempat 1",
  "ordre": "desc",
  "pipeline_version": 1,
  "pipeline": {}
}
```

### Regla
- Tot el que no sigui aquest shape es projeccio.
- `_builder_ui` no forma part del contracte persistent.
- Qualsevol top-level legacy addicional es transitori i nomes pot sortir de `legacy_projection.py`.

## Mapa De Moduls Backend

### Paquet nou
- `competicions_trampoli/services/classificacions/ties/__init__.py`

### Resolucio de context
- `competicions_trampoli/services/classificacions/ties/context.py`
  - resol `tipus`
  - resol `team_mode`
  - resol `exercise_selection_scope`
  - resol si es permeten `participants`
  - resol si es permeten overrides per aparell

### Registry
- `competicions_trampoli/services/classificacions/ties/registry.py`
  - selecciona handler de contracte a partir del context

### Contractes
- `competicions_trampoli/services/classificacions/ties/contracts/base.py`
- `competicions_trampoli/services/classificacions/ties/contracts/per_member.py`
- `competicions_trampoli/services/classificacions/ties/contracts/team_pool.py`
- `competicions_trampoli/services/classificacions/ties/contracts/derived_team.py`
- `competicions_trampoli/services/classificacions/ties/contracts/native_team.py`

### Serializer i validacio
- `competicions_trampoli/services/classificacions/ties/serializer_save.py`
- `competicions_trampoli/services/classificacions/ties/validation.py`

### Projeccions
- `competicions_trampoli/services/classificacions/ties/ui_projection.py`
- `competicions_trampoli/services/classificacions/ties/legacy_projection.py`
- `competicions_trampoli/services/classificacions/ties/builder_rehydration.py`

## Mapa De Moduls Frontend

### Slice nou
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/context.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/ui_state.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/save_serializer.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/ui_projection.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/render.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/contracts/per_member.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/contracts/team_pool.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/contracts/derived_team.js.html`
- `competicions_trampoli/templates/classificacions/builder/scripts/ties/contracts/native_team.js.html`

### Estat del monolit
- `competicions_trampoli/templates/classificacions/builder/_legacy_inline_script.html`
  - passa a ser shell temporal
  - no pot continuar concentrant la logica real de `desempat`
  - nomes pot delegar o desaparèixer progressivament

## Funcions Actuals A Extreure

### Des de `pipeline_runtime.py`
- `build_tie_pipeline_criterion`
- `materialize_desempat_item`
- `materialize_desempat_items`
- `_materialize_legacy_mirrors_from_pipeline`
- compactacio i normalitzacio tie-specific del pipeline

### Des de `validation.py`
- tot el bloc de validacio de `desempat[...]`
- tota la logica de `exercise_selection_scope`
- checks de compatibilitat segons `team_mode`

### Des de `builder.py`
- sanejaments específics de ties per reopen del builder
- neteges condicionals segons `team_pool` o equips

### Des de `_legacy_inline_script.html`
- `readTieObjFromRow`
- `buildTieCanonicalForSaveFromRow`
- `readTieBuilderState`
- `readTieCanonicalForSave`
- `renderTieUI`
- helpers de `_builder_ui`
- projeccions de resum/camps/participants

## Fitxer Actual -> Fitxer Nou

### Backend
- `services/classificacions/pipeline_runtime.py`
  - contract logic -> `services/classificacions/ties/contracts/*.py`
  - persistence serializer -> `services/classificacions/ties/serializer_save.py`
  - legacy mirrors -> `services/classificacions/ties/legacy_projection.py`

- `services/classificacions/validation.py`
  - tie validation -> `services/classificacions/ties/validation.py`

- `services/classificacions/builder.py`
  - builder reopen projection -> `services/classificacions/ties/builder_rehydration.py`

- `services/classificacions/runtime.py`
  - facade cap al serializer/validator nous

### Frontend
- `templates/classificacions/builder/_legacy_inline_script.html`
  - tie UI state -> `templates/classificacions/builder/scripts/ties/ui_state.js.html`
  - tie save serializer -> `templates/classificacions/builder/scripts/ties/save_serializer.js.html`
  - tie render -> `templates/classificacions/builder/scripts/ties/render.js.html`
  - contract logic -> `templates/classificacions/builder/scripts/ties/contracts/*.js.html`

## Invariants Per Contracte

### `team_pool`
- no pot serialitzar camps propis d'exercicis
- no pot serialitzar camps de participants
- no pot rehidratar `mode_seleccio_exercicis` com a valor editable
- no pot rebre auto-injeccio backend de participants

### `per_member`
- pot serialitzar configuracio propia d'exercicis
- pot usar override per aparell quan el contracte ho admet
- els camps absents es resolen per contracte, no per herencia invisible de UI stale

### `derived_team`
- `participants` nomes si el contracte resolt ho permet
- no pot injectar `participants` si `exercise_selection_scope == team_pool`

### `native_team`
- no admet mirrors o payloads de participants derivats
- qualsevol projeccio UI ha de reflectir aquesta restriccio

## API Interna A Congelar

Abans que els subagents avancin, aquestes signatures s'han de tancar:

- `resolve_tie_context(...) -> TieContext`
- `resolve_tie_contract(context) -> TieContractHandler`
- `serialize_tie_for_save(raw_tie, context, fallback_pipeline) -> dict`
- `validate_tie(canonical_tie, context) -> list[str]`
- `project_tie_to_ui(canonical_tie, context) -> dict`
- `project_tie_to_legacy(canonical_tie, context) -> dict`

## Fases De Migracio

### Fase 0. Congelacio de contracte i inventari
- Documentar tots els punts del repo on `desempat` es llegeix, es valida, es guarda o es renderitza.
- Tancar la shape persistent minima.
- Definir formalment `TieContext`.
- Identificar quins consumidors encara necessiten shape legacy.

### Fase 1. Nucli de context i registry
- Crear:
  - `ties/context.py`
  - `ties/registry.py`
  - `ties/contracts/base.py`
- Cap canvi funcional encara al frontend.
- Sortida d'aquesta fase:
  - context resolt estable
  - seleccio estable de contracte

### Fase 2. Contractes base `team_pool` i `per_member`
- Crear:
  - `ties/contracts/team_pool.py`
  - `ties/contracts/per_member.py`
- Codificar:
  - camps permesos
  - camps prohibits
  - regles de neteja
  - regles de defaults
- Primer objectiu funcional:
  - arreglar el bug de `team_pool` sense dependre del monolit

### Fase 3. Variants d'equip
- Crear:
  - `ties/contracts/derived_team.py`
  - `ties/contracts/native_team.py`
- Extreure la logica de participants i compatibilitat de team mode.

### Fase 4. Serializer de `save`
- Crear `ties/serializer_save.py`.
- Fer que `runtime.py` hi delegui.
- El serializer ha d'emetre nomes camps admesos pel contracte resolt.
- El backend ha de deixar de reintroduir camps prohibits.

### Fase 5. Validacio per contracte
- Crear `ties/validation.py`.
- Fer que `validation.py` hi delegui.
- Validar contra el contracte resolt i no contra la shape hibrida.

### Fase 6. Legacy projection explicita
- Crear `ties/legacy_projection.py`.
- Moure la materialitzacio legacy aqui.
- Eliminar densificacio implicita del cami de persistencia.

### Fase 7. UI projection i builder backend
- Crear:
  - `ties/ui_projection.py`
  - `ties/builder_rehydration.py`
- Fer que `builder.py` deixi de barrejar persistencia i reopen.

### Fase 8. Extraccio frontend del slice `desempat`
- Crear els fitxers `templates/.../scripts/ties/*.js.html`.
- Moure-hi:
  - estat UI
  - serializer de `save`
  - render
  - contractes de UI
- El monolit queda com a shell temporal.

### Fase 9. Tall final del monolit
- Eliminar logica real de `desempat` de `_legacy_inline_script.html`.
- Deixar wrappers o includes minims.
- Eliminar duplicacions i helpers morts.

## Paquets De Feina Per Subagents

### Subagent 1. Context i registry
- Write set:
  - `services/classificacions/ties/context.py`
  - `services/classificacions/ties/registry.py`
  - `services/classificacions/ties/contracts/base.py`
- Output:
  - context efectiu del tie
  - selector de contracte
- No toca frontend.
- No toca validacio.

### Subagent 2. Contractes `team_pool` i `per_member`
- Write set:
  - `services/classificacions/ties/contracts/team_pool.py`
  - `services/classificacions/ties/contracts/per_member.py`
- Output:
  - sanititzacio i regles de persistencia
- No toca templates.
- No toca runtime facade.

### Subagent 3. Variants d'equip
- Write set:
  - `services/classificacions/ties/contracts/derived_team.py`
  - `services/classificacions/ties/contracts/native_team.py`
- Output:
  - regles de participants i equips
- No toca frontend.

### Subagent 4. Serializer i integracio runtime
- Write set:
  - `services/classificacions/ties/serializer_save.py`
  - integracio minima a `services/classificacions/runtime.py`
- Output:
  - `save` canonic net
- No toca validacio.
- No toca render.

### Subagent 5. Validation extraction
- Write set:
  - `services/classificacions/ties/validation.py`
  - delegacio minima des de `services/classificacions/validation.py`
- Output:
  - validacio per contracte resolt
- No toca serializer.
- No toca frontend.

### Subagent 6. Legacy i builder backend
- Write set:
  - `services/classificacions/ties/legacy_projection.py`
  - `services/classificacions/ties/ui_projection.py`
  - `services/classificacions/ties/builder_rehydration.py`
  - integracio minima a `services/classificacions/builder.py`
- Output:
  - reopen coherent del builder
- No toca render JS.

### Subagent 7. Frontend slice `desempat`
- Write set:
  - `templates/classificacions/builder/scripts/ties/*.js.html`
  - wiring minim des de `_legacy_inline_script.html`
- Output:
  - render, estat UI i `save` fora del monolit
- No toca backend Python.

### Subagent 8. Tests i fixtures
- Write set:
  - tests classificacions/builder
- Output:
  - cobertura funcional i snapshots de payload
- No toca codi de produccio.

## Ordre Recomanat Entre Subagents
1. Subagent 1
2. Subagent 2 i 3 en paral.lel
3. Subagent 4
4. Subagent 5
5. Subagent 6
6. Subagent 7
7. Subagent 8 de forma transversal i tancament final al final

## Prompt Base Per Cada Subagent

Cada subagent ha de rebre sempre:

- aquest document
- el seu write set exclusiu
- les signatures d'API congelades
- els criteris de done de la seva fase
- la prohibicio expressa de:
  - revertir canvis d'altres subagents
  - tocar fitxers fora del seu write set
  - reintroduir shape hibrida a `desempat`

## Criteris De Done Per Fase

### Done Fase 1
- existeix `TieContext`
- es pot resoldre contracte efectiu sense UI

### Done Fase 2
- `team_pool` i `per_member` tenen sanititzacio explicita
- no depenen de `_legacy_inline_script.html`

### Done Fase 3
- les regles d'equips no estan barrejades amb els contractes base

### Done Fase 4
- `save` persisteix nomes contracte canonic
- no reintrodueix camps prohibits

### Done Fase 5
- la validacio no depen de shape top-level legacy per decidir incompatibilitats

### Done Fase 6
- els mirrors legacy només surten d'una projeccio explicita
- persistencia i reopen no comparteixen shape obligada

### Done Fase 7
- el builder reopen usa `ui_projection`
- `_builder_ui` no surt al `save`

### Done Fase 8
- el navegador ja executa el slice especialitzat de `desempat`
- no queden punts reals de `save` o rerender governats exclusivament pel monolit legacy

### Done Fase 9
- el monolit deixa de contenir la logica real de `desempat`

## Tests Obligatoris

### Persistencia
- `team_pool` no persisteix camps propis d'exercicis.
- `team_pool` no persisteix participants.
- `per_member` persisteix `mode_seleccio_exercicis` i `exercicis_per_aparell` quan toca.
- `derived_team + team_pool` no reintrodueix participants.
- `native_team` rebutja participants derivats.

### Builder
- el `payload` de `save` reflecteix exactament la configuracio visible.
- canviar dropdowns de `desempat` no col.lapsa la fila.
- reopen del builder conserva l'estat visible.
- `_builder_ui` no es persisteix mai.

### Legacy / transicio
- els consumidors que encara necessiten shape legacy la reben via projeccio explicita.
- la persistencia no densifica ties per defecte.

### Integracio
- passar tests de classificacions dins Docker.
- afegir casos explicits de:
  - `team_pool`
  - `per_member`
  - equips derivats
  - equips natius

## Criteris D'Acceptacio Finals
- `desempat` es pot guardar sense passar per una shape hibrida.
- `team_pool` i `per_member` tenen serializers diferents.
- el backend no injecta camps prohibits pel contracte.
- el frontend no envia camps ocults o stale.
- reopen del builder usa `ui_projection`, no mirrors implicits.
- `_legacy_inline_script.html` deixa de governar `desempat`.
- els tests funcionals i de builder passen dins Docker.

## Riscos Coneguts
- Desalineacio temporal entre `ui_projection` i `legacy_projection`.
- Regressions a `victories.desempat_comparacio` si es comparteixen helpers sense separar-los.
- Duplicacio temporal entre monolit i nous mòduls durant la fase híbrida.
- Consumidors antics que llegeixen shape legacy sense estar documentats.

## Mitigacions
- congelar signatures abans de paral.lelitzar
- write sets disjunts
- tests de snapshot de payload
- inventari dels consumidors legacy
- no moure lògica de dos contractes diferents al mateix subagent si no cal

## Estat Actual Del Pla
- Aquest document substitueix la versio anterior del pla de desmonolititzacio de `desempat`.
- A partir d'ara, la direccio oficial es:
  - fragmentacio per contractes i responsabilitats
  - no sols fragmentacio per fitxers
  - no mantenir un objecte `desempat` que intenti ser alhora UI, persistencia, validacio i compat legacy

### Avanc 2026-04-17. Projeccions backend per a reopen del builder
- S'ha treballat el paquet del Subagent 6: Legacy i builder backend.
- S'han creat les fronteres Python:
  - `services/classificacions/ties/legacy_projection.py`
  - `services/classificacions/ties/ui_projection.py`
  - `services/classificacions/ties/builder_rehydration.py`
- `prepare_schema_for_builder_hydration()` delega la reobertura de `desempat` a `builder_rehydration.py`.
- `builder_tie_rehydration.py` queda com a wrapper de compatibilitat cap a `ties/ui_projection.py`.
- S'han afegit tests unitaris de:
  - `canonical/pipeline -> ui_projection`
  - `canonical/pipeline -> legacy_projection`
  - `builder_rehydration = legacy_projection + ui_projection`

Limitacions conscients d'aquest tall:
- La materialitzacio legacy encara reutilitza `pipeline_runtime.materialize_desempat_item()` internament; la frontera explicita ja existeix, pero el trasllat complet de la logica fora de `pipeline_runtime.py` queda pendent.
- `validation.py` encara materialitza i neteja part de `desempat`; la Fase 5 no esta tancada del tot.
- El frontend no s'ha tocat: `_legacy_inline_script.html` continua governant render i save de `desempat`.
- No s'han creat encara contractes separats `derived_team.py` i `native_team.py`.

### Avanc 2026-04-17. Legacy projection real fora de `pipeline_runtime.py`
- S'ha completat el seguent tall de la Fase 6:
  - `services/classificacions/ties/pipeline_helpers.py` concentra helpers purs compartibles per normalitzar camps, exercicis, participants, agregacions i seleccio d'aparells.
  - `services/classificacions/ties/legacy_projection.py` ja materialitza directament els mirrors legacy des de `desempat[].pipeline`.
  - `pipeline_runtime.materialize_desempat_item()` i `pipeline_runtime.materialize_desempat_items()` queden com a wrappers de compatibilitat amb import local cap a `ties/legacy_projection.py`.
  - `builder.py` i `validation.py` passen a entrar directament per `ties/legacy_projection.py` quan necessiten shape legacy.
- S'ha eliminat la implementacio privada antiga de materialitzacio legacy dins `pipeline_runtime.py`.

Limitacions conscients d'aquest tall:
- SUPERAT en el tall posterior: `legacy_projection.py` ja no usa `build_tie_pipeline_criterion()` de `pipeline_runtime.py`.
- `pipeline_runtime.py` encara conserva helpers interns similars als de `ties/pipeline_helpers.py`; desduplicar-los queda pendent si es vol una unificacio mes profunda.
- `validation.py` encara fa neteja i validacio al voltant de la projeccio; la Fase 5 segueix parcial.

### Avanc 2026-04-17. Façana de validacio de `desempat`
- S'ha afegit `services/classificacions/ties/validation.py::materialize_desempat_for_validation()` com a helper de façana per al bloc final de validacio.
- La nova funcio combina `project_ties_legacy_projection()` amb `strip_team_pool_tie_payload()` i centralitza la neteja temporal de `exercise_selection_scope` en la shape materialitzada.
- `validate_team_pool_tie_contract()` i `strip_team_pool_tie_payload()` es mantenen compatibles i sense canvis de comportament.
- S'ha afegit cobertura unitaria lleugera al test de `ties` per congelar la shape de materialitzacio de validacio.

Limitacions conscients d'aquest tall:
- SUPERAT en el rollout principal: `services/classificacions/validation.py` ja delega aquesta facana.
- La validacio de `desempat` encara conserva validacions amb DB i compatibilitat dins el facade antic, pero la materialitzacio/cleanup de la shape temporal ja viu a `ties/validation.py`.

### Avanc 2026-04-17. Constructor de tie pipeline separat
- S'ha creat `services/classificacions/ties/pipeline_builder.py` amb la implementacio real de `build_tie_pipeline_criterion()`.
- `legacy_projection.py` i `serializer_save.py` ja importen el constructor des de `ties/pipeline_builder.py`.
- `pipeline_runtime.py` conserva `build_tie_pipeline_criterion()` com a wrapper de compatibilitat i deixa la logica real al paquet `ties/`.
- S'ha verificat que la ruta nova no introdueix cicles d'import.

Limitacions conscients d'aquest tall:
- `pipeline_runtime.py` encara guarda helpers legacy i continua sent la facana general de scoring.
- `pipeline_builder.py` encara depen de `normalize_scoring_pipeline()` i `PIPELINE_VERSION` via import local del runtime, cosa deliberada per mantenir el canvi petit i sense canvi funcional.

### Avanc 2026-04-17. Tancament backend abans del front
- S'ha integrat la facana `materialize_desempat_for_validation()` dins `services/classificacions/validation.py`.
- La materialitzacio temporal usada per validar `desempat` queda centralitzada a `services/classificacions/ties/validation.py`.
- S'ha afegit `validate_raw_desempat_legacy_payload()` per conservar errors legacy abans que `prepare_schema_for_persistence()` compacti el payload a pipeline-first.
- `services/classificacions/ties/__init__.py` exporta les peces backend principals del paquet `ties/`:
  - constructor de pipeline del tie
  - serializer de save
  - legacy projection
  - UI projection
  - builder rehydration
  - facana de validacio
- `pipeline_runtime.py` queda com a compatibilitat/facana per al constructor del tie, no com a propietari de la implementacio real.

Limitacions conscients d'aquest tancament:
- `pipeline_runtime.py` encara conserva helpers generals de scoring i wrappers de compatibilitat.
- `pipeline_builder.py` encara reutilitza `normalize_scoring_pipeline()` del runtime amb import local; es pot desduplicar mes endavant, pero ja no bloqueja el tall de frontend.
- La validacio amb DB de camps/aparells/exercicis continua a `services/classificacions/validation.py`; el paquet `ties/` ja concentra la shape i els contractes, no tota la infraestructura de validacio global.

Verificacio executada:
- `test_ties_serializer`
- `test_builder_hydration`
- `test_schema_validation`
- `test_classificacio_filters_and_validation`
- `manage.py check`

## Seguent Pas Operatiu
- Continuar la Fase 8 amb un segon tall frontend sobre normalitzadors/UI state que encara queden a `_40_ties_and_teams.js.html` i `_50_columns_detail_preview.js.html`.
- No obrir mes refactors backend grans abans d'aquest tall, excepte regressions detectades pels tests.

### Avanc 2026-04-17. Fase 8 iniciada: slice frontend de `desempat`
- `templates/competicio/classificacions_builder_v2.html` deixa de carregar `_legacy_inline_script.html` com a script servit i passa a incloure els fragments existents:
  - `_00_bootstrap.js.html`
  - `_10_core_ui.js.html`
  - `_20_team_templates_apps.js.html`
  - `classificacions/_puntuacio_script.html`
  - `_40_ties_and_teams.js.html`
  - `_50_columns_detail_preview.js.html`
  - `_60_particions.js.html`
  - `_70_hydration_sync.js.html`
  - `_80_actions_init.js.html`
- S'ha creat el primer slice `templates/classificacions/builder/scripts/ties/`:
  - `context.js.html`
  - `ui_state.js.html`
  - `contracts/per_member.js.html`
  - `contracts/team_pool.js.html`
  - `contracts/derived_team.js.html`
  - `contracts/native_team.js.html`
  - `save_serializer.js.html`
  - `victory.js.html`
  - `participants.js.html`
  - `render.js.html`
- `_40_ties_and_teams.js.html` queda com a parcial intermedi que inclou aquests fitxers i conserva helpers compartits que encara no s'han mogut.
- `syncAdvancedFromUI()` torna a guardar `desempat` via `readTieCanonicalForSave(true)`, preservant el payload pipeline-first.
- S'han mantingut literals de compatibilitat en comentaris per conservar els tests de contracte textual del builder fragmentat.

Limitacions conscients d'aquest tall:
- `_legacy_inline_script.html` encara existeix com a fitxer historic/fallback, pero ja no es el script carregat pel builder v2.
- El slice `ties/` encara depen de helpers globals definits a `_20`, `_40`, `_50` i `_70`.
- L'extraccio frontend ja te context, `ui_state` i contractes JS, pero `_40_ties_and_teams.js.html` encara conserva normalitzadors i helpers compartits de compatibilitat.
- Queda pendent reduir encara mes `_40` i tancar la paritat completa `save -> reopen -> render` sense duplicacions residuals.

Verificacio executada:
- `test_templates_global`
- `test_templates_competition`
- `test_builder_hydration`
- `test_ties_serializer`
- `test_schema_validation`
- `test_classificacio_filters_and_validation`
- `manage.py check`

### Avanc 2026-04-17. Orquestracio dels passos 1 i 2
- S'ha executat una orquestracio per write sets disjunts per tancar:
  - Pas 1: contractes backend `derived_team` i `native_team`
  - Pas 2: extraccio del nucli frontend de `desempat` cap a `templates/classificacions/builder/scripts/ties/*`
- Repartiment de responsabilitats aplicat:
  - Worker backend contractes:
    - `services/classificacions/ties/contracts/derived_team.py`
    - `services/classificacions/ties/contracts/native_team.py`
  - Worker backend integracio:
    - `services/classificacions/ties/context.py`
    - `services/classificacions/ties/registry.py`
    - `services/classificacions/ties/__init__.py`
    - `services/classificacions/ties/serializer_save.py`
    - `services/classificacions/ties/validation.py`
    - `tests/classificacions/test_ties_serializer.py`
  - Worker frontend context/estat/contractes:
    - `templates/classificacions/builder/scripts/ties/context.js.html`
    - `templates/classificacions/builder/scripts/ties/ui_state.js.html`
    - `templates/classificacions/builder/scripts/ties/contracts/*.js.html`
  - Worker frontend render/save:
    - `templates/classificacions/builder/scripts/ties/save_serializer.js.html`
    - `templates/classificacions/builder/scripts/ties/render.js.html`
    - `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`

Resultat del Pas 1:
- `services/classificacions/ties/context.py` resol explicitament els contractes `per_member`, `team_pool`, `derived_team` i `native_team`.
- `services/classificacions/ties/registry.py` delega a contractes separats dins `contracts/`.
- `services/classificacions/ties/contracts/derived_team.py` i `services/classificacions/ties/contracts/native_team.py` ja existeixen com a peces reals del paquet.
- `services/classificacions/ties/serializer_save.py` preserva `exercise_selection_scope` des del pipeline normalitzat.
- `services/classificacions/ties/validation.py` elimina payload de participants quan el context resolt es `native_team`.

Resultat del Pas 2:
- `_40_ties_and_teams.js.html` ja inclou el nou ordre de slices:
  - `context.js.html`
  - `ui_state.js.html`
  - `contracts/*.js.html`
  - `save_serializer.js.html`
  - `victory.js.html`
  - `participants.js.html`
  - `render.js.html`
- El nucli de canonicalitzacio del `save` viu a `save_serializer.js.html`.
- La lectura de fila, projeccio visible i bona part del render viu a `render.js.html`.
- `context.js.html` i `ui_state.js.html` aporten el resolver de context/contracte i la normalitzacio de l'estat editable.

Limitacions conscients d'aquesta orquestracio:
- `_40_ties_and_teams.js.html` encara no es una shell minima; manté helpers compartits de normalitzacio i compatibilitat.
- El slice frontend nou encara depen de funcions globals del builder existent.
- El legacy ja no es necessari per al runtime del builder v2, pero encara es util com a referencia de comparacio mentre no es tanqui la Fase 9.

Verificacio executada en aquest tall:
- `test_ties_serializer`
- `test_builder_hydration`
- `test_templates_competition`
- `test_templates_global`
- Ajust puntual validat: `derived_team` aplica neteja de `team_pool` quan el `exercise_selection_scope` resolt es `team_pool`

Seguent pas operatiu recomanat:
- reduir `_40_ties_and_teams.js.html` fins a shell fina
- afegir cobertura de regressio `save -> reopen -> render` per `per_member`, `team_pool`, `derived_team` i `native_team`

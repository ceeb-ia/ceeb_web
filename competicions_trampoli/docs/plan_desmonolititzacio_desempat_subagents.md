# Pla D'Implementacio De La Desmonolititzacio De `desempat` Per Subagents

## Objectiu
- Treure del flux actual de `desempat` la barreja de responsabilitats entre builder, persistencia, validacio, runtime i compat legacy.
- Permetre que el sistema guardi un contracte canonic de `desempat` sense materialitzar mirrors legacy complets al `save`.
- Mantenir reobertura robusta del builder sense fer dependre el `save` del format de rehidratacio UI.
- Deixar la feina empaquetada per subagents independents, amb context minim, write scopes disjunts i handoffs clars.

## Regla Principal
- Aquesta feina si que es funcional; no es una mera refactoritzacio cosmetica.
- Tot canvi ha de preservar el comportament public actual del ranking, la validacio i el builder, excepte la densificacio no desitjada del tie al guardar.
- El `pipeline` ha de continuar sent l'unica font de veritat canonica.
- `_builder_ui` continua sent exclusivament builder-only i no s'ha de persistir mai.
- Els mirrors legacy de `desempat` no s'han de seguir regenerant automaticament al cami de persistencia, excepte si hi ha un consumidor explicit que encara els necessiti.

## Decisions Tancades
- El contracte persistent final de `desempat` sera `pipeline-first` estricte.
- `validation.py` ha d'evolucionar cap a validacio del contracte canonic; qualsevol lectura legacy que sobrevisqui durant la transicio ha de ser temporal i explicitament encapsulada.
- Els wrappers temporals de `pipeline_runtime.py` nomes existeixen per transicio.
- La seccio frontend de `desempat` ha de deixar de dependre de `_legacy_inline_script.html` com a font de veritat.
- Els fitxers especialitzats de builder per `desempat` han de passar a ser la implementacio servida real, no nomes una branca paral.lela.
- Un wrapper temporal s'ha de poder eliminar quan:
  - no quedi cap consumidor de shape legacy cru identificat al repo
  - persistencia i validacio treballin ja sobre contracte canonic
  - builder hydration no depengui de mirrors legacy persistits

## Estat Actual Real
- El backend de persistencia de `schema.desempat` ja esta parcialment desacoblat:
  - el `save` persisteix `desempat` en format `pipeline-first`
  - la resposta del backend ja no reintrodueix mirrors top-level densificats per defecte a `desempat`
  - la compactacio sparse del `pipeline` de `desempat` ja existeix
- La rehidratacio backend del builder amb `_builder_ui` tambe existeix.
- El bloqueig principal actual es frontend:
  - el template servit continua injectant `_legacy_inline_script.html`
  - els fitxers modulars de `builder/scripts/` no son avui la font de veritat efectiva del navegador
  - dins del monolit legacy encara hi ha call sites que fan `renderTieUI(readTieUI(true))`
  - aixo reconstrueix tota la seccio `desempat` des de shape canonic/legacy i destrueix l'estat UI row-local
- Consequencia observable:
  - no es corromp nomes `camp` o `camps`
  - col.lapsen tots els dropdowns de la fila o de la seccio
  - valors com `mode_seleccio_exercicis`, `exercise_selection_scope`, `participants`, agregacions i overrides per aparell tornen a defaults o derivacions no desitjades
- Implicacio per al pla:
  - la desmonolititzacio backend ja no es suficient per si sola
  - cal una onada explicita de desmonolititzacio frontend servida per `desempat`

## Problema Actual
- El flux actual reutilitza la mateixa cadena per:
  - construir `pipeline` des d'un tie minim
  - projectar mirrors legacy
  - rehidratar el builder
  - validar el schema
  - preparar el payload de persistencia
- El punt critic es `materialize_desempat_item()` a `services/classificacions/pipeline_runtime.py`.
- Aquest helper acaba cridant `_materialize_legacy_mirrors_from_pipeline()`, que regenera:
  - `camps`
  - `camp`
  - `aparell_id`
  - `scope`
  - `exercise_selection_scope`
  - `mode_seleccio_exercicis`
  - `exercicis_per_aparell`
  - `agregacio_exercicis_per_aparell`
  - agregacions legacy
- Despres `validate_schema_for_competicio_detailed()` substitueix `schema_local["desempat"]` per la versio materialitzada.
- Finalment `prepare_schema_for_persistence()` persisteix aquesta shape ja densificada.
- Consequencia:
  - el tie minim editat des del builder no sobreviu al `save`
  - el `save` queda acoblat a decisions de reobertura builder i compat legacy
  - qualsevol canvi a la materialitzacio compartida es converteix en regressio potencial de builder o persistencia
- A mes, avui hi ha un segon problema independent i ja confirmat:
  - el frontend real servit continua sent el monolit legacy
  - aquest monolit continua refent `desempat` des de `readTieUI(true)` en diversos punts de rerender
  - per tant, encara que persistencia i hydration backend millorin, la UI pot seguir destruint l'estat seleccionat abans del `save`

## Arquitectura Objectiu

### Contractes finals
- Contracte canonic persistit:
  - `desempat[i]` amb metadades minimes i `pipeline` complet
  - sense `_builder_ui`
  - sense necessitat de mirrors legacy densificats
- Contracte de rehidratacio builder:
  - `desempat[i]` canonic + `_builder_ui`
- Contracte de compat legacy runtime:
  - projeccio opcional i explicita des de `pipeline`
  - no aplicada per defecte al `save`

### Arquitectura frontend objectiu per `desempat`
- La seccio `desempat` ha de tenir un slice propi end-to-end:
  - markup especialitzat de seccio
  - estat UI especialitzat
  - render especialitzat
  - lectura canonic/serialitzacio especialitzada
  - hydration especialitzada
- El monolit legacy no ha de ser la font de veritat de `desempat`.
- El template actiu ha de muntar els fitxers especialitzats de `builder/scripts/` o un bundle equivalent que els agregui.
- `_legacy_inline_script.html` nomes pot sobreviure com a adapter temporal mentre es completa el tall, pero no ha de continuar governant `desempat`.

### Responsabilitats separades
- Canonicalitzacio de ties:
  - input minim o mixed
  - output canonic amb `pipeline`
- Projeccio legacy:
  - input canonic
  - output mirrors legacy per consumidors antics
- Projeccio builder:
  - input canonic
  - output `_builder_ui`
- Validacio:
  - valida contracte canonic
  - no ha de convertir el payload persistit a una shape legacy densa
- Persistencia:
  - desa contracte canonic
  - no materialitza mirrors si no son estrictament necessaris
- Frontend `desempat`:
  - mante estat UI row-local
  - rerenderitza des d'aquest estat UI i no des de `readTieUI(true)`
  - compila al contracte canonic nomes al cami de serialitzacio

## Estrategia De Compatibilitat

### Principi De Transicio
- La transicio s'ha de fer amb:
  - lectura compatible
  - escriptura canonica
- Aixo vol dir:
  - el `save` passa progressivament a `pipeline-first`
  - els consumidors antics no poden continuar depenent del shape legacy cru guardat a DB
  - mentre existeixin consumidors antics, han de rebre una projeccio legacy explicita des del contracte canonic

### Regla Operativa
- La base de dades ha d'acabar persistint `desempat` en format canonic:
  - metadades minimes
  - `pipeline`
- Els mirrors legacy no s'han de considerar part del contracte persistent.
- Si un consumidor antic necessita `scope`, `camps`, `aparell_id` o similars:
  - no els ha de llegir directament del shape guardat
  - els ha d'obtenir via `tie_legacy_projection.py`
- No s'han d'afegir nous consumidors del shape legacy guardat.

### Consumidors Legacy A Adaptar Abans Del Tall Estricte
- `services/classificacions/classificacio_templates.py`
  - encara llegeix camps top-level legacy com `aparell_id`, `scope`, `exercicis_per_aparell` i agregacions derivades
  - aquest subsistema ha de passar a consumir una projeccio legacy explicita
- `services/classificacions/validation.py`
  - encara te validacions que llegeixen shape top-level legacy de `desempat`
  - s'ha d'acostar al contracte canonic o, si cal temporalment, consumir una projeccio legacy controlada

### Inventari Concret De Consumidors Legacy Detectats
- `services/classificacions/pipeline_runtime.py`
  - `_normalize_legacy_tie_pipeline()`
  - `build_tie_pipeline_criterion()`
  - `materialize_desempat_item()`
  - `materialize_desempat_items()`
  - rol durant la transicio: pont de migracio i materialitzacio legacy sota demanda
- `services/classificacions/classificacio_templates.py`
  - `template_schema_to_global_ui_schema()`
  - `global_ui_schema_to_template_schema()`
  - `collect_required_app_codes_from_template()`
  - `validate_template_schema_global()`
  - `normalize_tie_camps_for_validation()`
  - risc: export/import i roundtrip de plantilles
- `services/classificacions/validation.py`
  - `_resolve_tie_target_app_ids()`
  - `_validate_desempat_mode_compatibility()`
  - `_validate_tie_exercicis_selection()`
  - `validate_schema_for_competicio_detailed()`
  - risc: validacio/save i neteges transitòries
- `services/classificacions/builder.py`
  - `_normalize_tie_camps_for_validation()`
  - `_effective_tie_exercise_selection_scope()`
  - `prepare_schema_for_builder_hydration()`
  - `sanitize_schema_for_builder()`
  - risc: reobertura backend del builder
- `templates/classificacions/builder/scripts/_50_columns_detail_preview.js.html`
  - `sanitizeTieItemForUI()`
  - risc: reobertura i resum de UI
- `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
  - `getTieVisibleCamps()`
  - `getTieVisibleAggCamps()`
  - `getTieVisibleParticipants()`
  - `getTieVisibleSummary()`
  - `readTieUI()`
  - `renderTieUI()`
  - risc: rerender de fila i estat visible
- `templates/classificacions/builder/_legacy_inline_script.html`
  - implementacio legacy realment servida avui per `templates/competicio/classificacions_builder_v2.html`
  - continua contenint call sites que fan `renderTieUI(readTieUI(true))`
  - risc principal actual: qualsevol canvi parcial als fitxers modulars no te efecte si no es talla aquest punt de muntatge
- `templates/competicio/classificacions_builder_v2.html`
  - avui inclou directament `_legacy_inline_script.html`
  - risc: el builder productiu segueix governat pel monolit, no pels fitxers modulars de `builder/scripts/`
- `services/legacy/services_classificacions_2.py`
  - `_tie_key()`
  - `calc_metric_value_for_ins()`
  - `calc_metric_value_for_group()`
  - `calc_metric_value_for_native_team()`
  - `_rank_v2()`
  - risc: motor legacy de ranking encara operatiu

### Criteri De Migracio
- Les classificacions legacy ja presents a DB s'han de continuar llegint.
- Quan s'obren:
  - es canonicalitzen en memoria
  - el builder i el runtime treballen sobre aquesta versio canonica
- Quan es tornen a guardar:
  - s'han de desar en el contracte nou `pipeline-first`
- Aquesta migracio ha de ser lazy:
  - compatibilitat de lectura per legacy
  - persistencia neta per noves escriptures

## Moduls Objectiu

### Nous moduls recomanats
- `competicions_trampoli/services/classificacions/tie_canonicalization.py`
  - entrada: tie raw o minim
  - sortida: tie canonic amb `pipeline`
  - ownership:
    - normalitzacio de `exercicis`
    - normalitzacio de `candidate_source_cfg`
    - normalitzacio de `participants`
    - construccio de `pipeline`
- `competicions_trampoli/services/classificacions/tie_legacy_projection.py`
  - entrada: tie canonic
  - sortida: tie amb mirrors legacy
  - ownership:
    - `scope`
    - `camps`
    - `aparell_id`
    - claus legacy derivades del `pipeline`
- `competicions_trampoli/services/classificacions/tie_builder_projection.py`
  - entrada: tie canonic
  - sortida: tie + `_builder_ui`
  - ownership:
    - estat builder-only de reobertura
    - resum i sentinels `hereta`

### Moduls existents a simplificar
- `pipeline_runtime.py`
  - ha de deixar de ser el lloc on es barregen canonicalitzacio i projeccio legacy
- `validation.py`
  - ha de deixar de substituir `schema_local["desempat"]` per la shape legacy materialitzada
- `runtime.py`
  - ha de persistir el contracte canonic, no el resultat d'una projeccio legacy
- `builder.py`
  - hydration del builder ha de projectar `_builder_ui` a partir del contracte canonic
- `templates/competicio/classificacions_builder_v2.html`
  - ha de deixar de muntar `desempat` exclusivament via `_legacy_inline_script.html`
- builder JS de `desempat`
  - ha de continuar treballant amb estat UI propi, pero serialitzant sempre al contracte canonic
  - ha de tenir un punt de muntatge real i servit

### Slice frontend objectiu de `desempat`
- Template de muntatge:
  - `templates/competicio/classificacions_builder_v2.html`
- Seccio HTML:
  - `templates/classificacions/builder/sections/_desempat.html`
- Scripts especialitzats:
  - `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
  - `templates/classificacions/builder/scripts/_50_columns_detail_preview.js.html`
  - `templates/classificacions/builder/scripts/_70_hydration_sync.js.html`
  - `templates/classificacions/builder/scripts/_80_actions_init.js.html`
- Adapter legacy temporal:
  - `templates/classificacions/builder/_legacy_inline_script.html`
- Regla:
  - qualsevol logica nova de `desempat` s'ha de concentrar al slice especialitzat
  - el monolit legacy nomes pot delegar o deixar de tocar aquesta seccio

## Guardrails De No Regressio

### Invariants
- El ranking final de `desempat` no canvia.
- `prepare_schema_for_builder_hydration()` continua reobrint ties antics i nous.
- `exercise_selection_scope` per `native_team` continua eliminant-se al cami canonic on avui ja s'elimina.
- `advancedJson` i `tDesempat` continuen sense `_builder_ui`.
- Els templates i vistes d'entrada no canvien.
- El builder servit al navegador ha d'acabar executant la logica especialitzada de `desempat`, no una copia legacy divergent.

### Canvis explicitament permesos
- Que el schema persistit de `desempat` deixi de contenir mirrors legacy densificats quan no siguin part del contracte canonic definit.
- Que la validacio i persistencia usin helpers nous en comptes del runtime compartit actual.

### Canvis explicitament no permesos
- No tocar `puntuacio.victories.desempat_comparacio` en aquesta fase.
- No reescriure el builder sencer.
- No moure tota la logica del builder a `static/`.
- No canviar el contracte public dels endpoints de `classificacio_save`.

## Carrils Per Subagents

### Agent 1: Canonicalitzacio De Ties
- Objectiu:
  - extreure la logica `raw/minim -> canonic`
  - fer que aquesta logica no projecti mirrors legacy
- Fitxers propis:
  - nou `tie_canonicalization.py`
  - `pipeline_runtime.py` només per adaptar imports i facades
- Treball concret:
  - moure `build_tie_pipeline_criterion()` i les normalitzacions estrictament canonitzadores al nou modul
  - deixar una facade a `pipeline_runtime.py` per compatibilitat temporal
  - no tocar builder ni validacio
- Resultat esperat:
  - existeix una API clara de canonicalitzacio sense side effects de compat

### Agent 2: Projeccio Legacy
- Objectiu:
  - extreure `pipeline -> legacy mirrors`
  - convertir-ho en pas explicit, no implicit
- Fitxers propis:
  - nou `tie_legacy_projection.py`
  - `pipeline_runtime.py` per redirigir `_materialize_legacy_mirrors_from_pipeline()`
- Treball concret:
  - moure la logica de mirrors legacy al nou modul
  - deixar `pipeline_runtime.py` com a wrapper fi mentre hi hagi consumidors antics
  - inventariar quins consumidors continuen llegint `desempat` en shape legacy i documentar el seu estat de migracio
  - no tocar persistencia ni builder
- Resultat esperat:
  - hi ha una API clara per projectar legacy sobre demanda
  - els consumidors antics queden identificats i encapsulats

### Agent 3: Persistencia I Validacio
- Objectiu:
  - fer que el `save` usi contracte canonic
  - eliminar la densificacio automatica del `desempat` al persistir
- Fitxers propis:
  - `validation.py`
  - `runtime.py`
  - opcionalment `builder_shared.py` si cal una facade comuna
- Treball concret:
  - deixar de substituir `schema_local["desempat"]` per la shape materialitzada legacy dins `validate_schema_for_competicio_detailed()`
  - fer que la validacio treballi amb ties canonics
  - fer que `prepare_schema_for_persistence()` persisteixi la versio canonica
  - mantenir neteja de casos incompatibles com `native_team`
  - aplicar la regla de transicio:
    - lectura compatible
    - escriptura canonica
- Resultat esperat:
  - editar i guardar un tie no l'expandeix a mirrors legacy complets
  - el `save` deixa de dependre del shape legacy persistit

### Agent 4: Builder Hydration Backend
- Objectiu:
  - acoblar la nova canonicalitzacio al builder sense perdre reobertura robusta
- Fitxers propis:
  - `builder.py`
  - `builder_tie_rehydration.py`
- Treball concret:
  - fer que la hidratacio del builder parteixi del tie canonic
  - aplicar `_builder_ui` com a projeccio separada
  - no dependre de mirrors legacy de persistencia per reobrir la UI
- Resultat esperat:
  - la UI es reobre identica encara que la persistencia guardi tie canonic minim

### Agent 5: Builder JS
- Objectiu:
  - assegurar equivalencia entre estat UI row-local i contracte canonic serialitzat
- Fitxers propis:
  - `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
  - `templates/classificacions/builder/scripts/_50_columns_detail_preview.js.html`
  - `templates/classificacions/builder/scripts/_70_hydration_sync.js.html`
  - `templates/classificacions/builder/scripts/_80_actions_init.js.html`
- Treball concret:
  - mantenir el nou `__tieBuilderState`
  - garantir que el cami de guardat construeix el tie canonic i no depen de mirrors legacy
  - garantir que cap rerender de `desempat` surti de `readTieUI(true)` quan l'objectiu es preservar estat visible
  - no tocar `victories`
- Resultat esperat:
  - la UI pot editar ties canonics minsos i seguir reobrint-se correctament

### Agent 5B: Frontend Desmonolititzacio De `desempat`
- Objectiu:
  - tallar el domini efectiu de `_legacy_inline_script.html` sobre la seccio `desempat`
  - fer que el builder servit executi la implementacio especialitzada real d'aquesta seccio
- Fitxers propis:
  - `templates/competicio/classificacions_builder_v2.html`
  - `templates/classificacions/builder/_legacy_inline_script.html`
  - `templates/classificacions/builder/sections/_desempat.html`
  - si cal, fitxer agregador o inclusions dels scripts modulars
- Treball concret:
  - decidir el mecanisme de muntatge definitiu:
    - o servir els fitxers modulars directament
    - o fer que el monolit legacy delegui la seccio `desempat` a les funcions modulars
  - eliminar els call sites legacy que avui fan `renderTieUI(readTieUI(true))` en el flux servit
  - garantir que el template actiu ja no executa una copia divergent del comportament de `desempat`
- Resultat esperat:
  - els canvis al slice modular de `desempat` tenen efecte real al navegador
  - la seccio deixa de col.lapsar dropdowns per rerenders legacy

### Agent 6: Tests I Guards
- Objectiu:
  - cobrir contracte canonic, regressions builder i no regressions `native_team`
- Fitxers propis:
  - `tests/classificacions/test_builder_hydration.py`
  - `tests/classificacions/test_compute_core.py`
  - `tests/scoring/team/test_classificacio_filters_and_validation.py`
- Treball concret:
  - afegir proves que el `save` no densifica `desempat`
  - afegir proves que el builder continua reobrint ties canonics minsos
  - mantenir guards existents de neteja per `native_team`
- Resultat esperat:
  - el comportament objectiu queda blindat

### Agent 7: Integracio Final
- Objectiu:
  - ajuntar els carrils sense reintroduir acoblaments
- Fitxers propis:
  - qualsevol fitxer de cola estrictament necessari
  - no ha de reimplementar el treball dels altres
- Treball concret:
  - triar les noves APIs definitives
  - eliminar wrappers temporals que ja no calguin
  - confirmar que cada consumidor usa el modul correcte:
    - persistencia -> canonicalitzacio
    - builder hydration -> canonicalitzacio + builder projection
    - compat antiga -> legacy projection
- Resultat esperat:
  - el sistema deixa de tenir una cadena monolitica compartida per tots els usos
  - el frontend servit de `desempat` coincideix amb el slice especialitzat i no amb una copia legacy divergent

## Contractes Entre Carrils

### API canonica
- `canonicalize_tie_item(raw_tie, *, tipus, team_mode, selected_app_ids, fallback_pipeline, allow_participants) -> dict`
- `canonicalize_tie_items(raw_ties, **kwargs) -> list[dict]`
- La sortida ha de contenir:
  - `id`
  - `nom`
  - `ordre`
  - `pipeline_version`
  - `pipeline`
- No ha de contenir mirrors legacy si no se li demanen explicitament.

### API de projeccio legacy
- `project_legacy_tie_mirrors(tie, *, allow_participants) -> dict`
- `project_legacy_tie_mirrors_many(ties, *, allow_participants) -> list[dict]`
- Aquesta API pot afegir:
  - `camps`
  - `camp`
  - `aparell_id`
  - `scope`
  - claus legacy derivades

### API de projeccio builder
- `project_builder_tie_rehydration(tie, *, main_pipeline, tipus, team_mode) -> dict`
- Aquesta API pot afegir:
  - `_builder_ui`
- No ha de tocar el `pipeline`.

### API frontend de `desempat`
- `renderTieUI(list) -> void`
- `readTieUI(includeInvalid) -> list[dict]`
- `readTieBuilderState(includeInvalid) -> list[dict]`
- `buildTieBuilderStateFromRow(tr, includeParticipants, selectedMainIds, fallbackPuntuacio) -> dict`
- Regla de contracte:
  - `readTieUI()` retorna contracte canonic serialitzable
  - `readTieBuilderState()` retorna estat de sessio amb `_builder_ui`
  - cap rerender de `desempat` pot usar `readTieUI(true)` si l'objectiu es preservar l'estat visible de la fila

## Ordre D'Implementacio Recomanat
1. Agent 1 extreu canonicalitzacio.
2. Agent 2 extreu projeccio legacy.
3. Agent 6 afegeix primers tests de contracte per blindar el canvi abans de moure persistencia.
4. Agent 3 refa validacio i persistencia perque usin canonic.
5. Agent 4 adapta hydration backend del builder al nou contracte.
6. Agent 5 ajusta builder JS per serialitzar i reobrir amb el nou shape persistit.
7. Agent 5B talla el monolit frontend servit i fa que `desempat` passi a slice especialitzat real.
8. Agent 6 completa cobertura final.
9. Agent 7 integra, elimina wrappers temporals i fa pass final de regressions.

## Orquestracio D'Execucio

### Onada 1: Separacio D'APIs
- Agent 1 ha de deixar disponible `canonicalize_tie_item()` sense projeccio legacy.
- Agent 2 ha de deixar disponible `project_legacy_tie_mirrors()` i inventari de consumidors.
- Gate de sortida:
  - existeixen API canonica i API legacy separades
  - `pipeline_runtime.py` encara pot tenir facades, pero ja no concentra la logica real

### Onada 2: Blindatge De Contracte
- Agent 6 ha d'afegir asserts que defineixin:
  - que el `save` no densifica `desempat`
  - que els casos `native_team` continuen nets
  - que el builder continua reobrint ties canonics minsos
- Gate de sortida:
  - hi ha proves vermelles si es reintrodueix densificacio o si es trenca la reobertura

### Onada 3: Tall De Persistencia
- Agent 3 ha de moure `save` i validacio cap a contracte canonic.
- Nomes es permet projeccio legacy explicita per compatibilitat de lectura.
- Gate de sortida:
  - `prepare_schema_for_persistence()` ja no persisteix mirrors legacy per defecte
  - `validate_schema_for_competicio_detailed()` no substitueix `desempat` per una shape legacy densa

### Onada 4: Rehidratacio Builder
- Agents 4 i 5 han de garantir que builder backend i builder JS reobren ties canonics sense dependre del shape persistit legacy.
- Gate de sortida:
  - reobertura UI robusta sobre persistencia `pipeline-first`
  - `_builder_ui` continua fora del contracte persistent

### Onada 4B: Tall Del Monolit Frontend Servit
- Agent 5B ha de garantir que el template actiu deixa de fer servir el flux legacy divergent per `desempat`.
- Gate de sortida:
  - `classificacions_builder_v2.html` ja no governa `desempat` exclusivament via `_legacy_inline_script.html`
  - no queden call sites servits que facin `renderTieUI(readTieUI(true))` per preservacio d'estat de `desempat`
  - els scripts especialitzats de `desempat` son la implementacio efectiva al navegador

### Onada 5: Compatibilitat I Neteja Final
- Agent 7 integra els carrils i elimina wrappers temporals que ja no calguin.
- Nomes poden quedar adapters legacy a consumidors antics encara no migrats, mai al cami generic de persistencia.
- Gate de sortida:
  - els consumidors legacy coneguts estan adaptats o encapsulats
  - el cami generic de `save` i runtime principal ja no depen de legacy projection

## Handoffs Obligatoris
- Agent 1 ha de documentar quines funcions extretes segueixen sent wrappers temporals a `pipeline_runtime.py`.
- Agent 2 ha de deixar clar quins consumidors continuen necessitant projeccio legacy.
- Agent 2 ha de marcar explicitament quins consumidors poden deixar de dependre de legacy en aquesta fase i quins no.
- Agent 3 no pot assumir cap shape builder-only; ha de treballar exclusivament amb contracte canonic.
- Agent 4 no pot tornar a fer que el builder depengui de la shape persistida legacy.
- Agent 5 no pot canviar el contracte persistent; només l'adapta al builder.
- Agent 6 ha de convertir els requisits de contracte en asserts concrets abans que Agent 7 tanqui la integracio.

- Agent 5B no pot limitar-se a duplicar logica del monolit; ha de tallar o delegar el punt de muntatge real del builder servit.

## Pla De Proves

### Persistencia canonica
- Guardar un `desempat` minim i verificar que:
  - es persisteix `pipeline`
  - no apareixen mirrors legacy densificats si no formen part del contracte canonic final triat
- Guardar un tie amb `per_aparell_override` i verificar que no s'omplen claus no demanades fora del `pipeline`.

### Compatibilitat De Lectura
- Obrir classificacions legacy ja presents a DB i verificar que:
  - es poden canonicalitzar sense perdre semantica funcional
  - es poden reobrir al builder sense requerir mirrors persistits
- Tornar a guardar aquestes classificacions i verificar que:
  - queden en format `pipeline-first`
  - no es trenca la lectura posterior
- Verificar que els consumidors antics identificats continuen funcionant:
  - via projeccio legacy explicita
  - no via lectura directa del shape persistent legacy

### Builder hydration
- Obrir una config guardada amb ties canonics minsos i verificar que:
  - el builder reobre `scope`, `mode_seleccio_exercicis`, `exercise_selection_scope`, overrides per aparell i participants
  - no cal cap shape legacy persistida per reobrir correctament

### Frontend servit de `desempat`
- Verificar que el template actiu executa el slice especialitzat de `desempat`.
- Verificar que canviar qualsevol dropdown de `desempat`:
  - no col.lapsa la resta de dropdowns de la fila
  - no reverteix `camp`, `camps`, overrides o agregacions a valors stale
  - no reconstrueix la fila des de `readTieUI(true)` durant rerenders de preservacio d'estat
- Verificar que el payload abans del `save` no contingui divergencies entre:
  - `camps`
  - `_builder_ui.camps`
  - `pipeline.camps_per_aparell`

### Guards existents
- `native_team` continua eliminant `exercise_selection_scope` on pertoqui.
- El ranking i el compute no canvien.
- `advancedJson` i `tDesempat` continuen sense `_builder_ui`.

### Execucions recomanades
- `competicions_trampoli.tests.classificacions.test_builder_hydration`
- `competicions_trampoli.tests.classificacions.test_compute_core`
- `competicions_trampoli.tests.scoring.team.test_classificacio_filters_and_validation`

## Criteris D'Acceptacio Finals
- El tie editat pel builder deixa de densificar-se automaticament al guardar.
- El builder continua reobrint ties antics i nous sense regressions de UX.
- Persistencia, validacio i builder deixen de dependre del mateix helper monolitic per objectius diferents.
- La seccio `desempat` servida al navegador deixa de dependre del monolit legacy com a font de veritat.
- La transicio queda definida i aplicada amb la regla:
  - lectura compatible
  - escriptura canonica
- Els consumidors antics coneguts de shape legacy queden:
  - adaptats
  - o explicitament encapsulats darrere d'una projeccio legacy
- Existeixen moduls separats i localitzables per:
  - canonicalitzacio
  - projeccio legacy
  - projeccio builder
- Existeix un slice frontend especialitzat i realment servit per `desempat`.
- Un agent extern pot identificar on tocar cada responsabilitat sense haver d'entendre tot el builder ni tot `pipeline_runtime.py`.

## No Fer
- No moure aquesta refactoritzacio dins d'un unic fitxer gegant de `desempat`.
- No mantenir el comportament antic a base de seguir cridant una materialitzacio legacy i netejar-la despres.
- No acoblar el nou modul canonic a `_builder_ui`.
- No tocar `puntuacio.victories.desempat_comparacio` en aquesta fase.
- No deixar els fitxers modulars de `desempat` com a codi mort mentre el template actiu continua servint el monolit legacy.

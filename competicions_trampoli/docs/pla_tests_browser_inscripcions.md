# Pla D'Implementacio Dels Tests Browser D'Inscripcions Per Subagents Paral.lels

## Objectiu
- Afegir una bateria de tests de navegador real per al modul d'inscripcions de `competicions_trampoli`.
- Detectar regressions silencioses de frontend:
  - errors de JS a consola
  - botons que deixen de funcionar
  - panells lazy que no carreguen
  - refresh parcials que trenquen l'estat
  - fluxos que semblen renderitzar be pero fallen en executar-se
- Deixar el treball prou paquetitzat perque subagents independents, amb context minim, puguin implementar fases concretes en paral.lel i amb alta probabilitat d'exit.

## No Objectius
- No reescriure el frontend d'inscripcions.
- No migrar el frontend a una SPA o a JS modular extern.
- No substituir els tests backend existents.
- No cobrir exhaustivament tota la logica de negoci via browser si ja esta protegida per tests Django.
- No introduir una segona stack de test JS basada en Node si no es estrictament necessari.

## Decisio Tecnica Base
- Stack objectiu inicial:
  - `playwright` amb Python
  - `chromium` com a navegador principal
  - base de test sobre Django `StaticLiveServerTestCase` o equivalent del projecte
- Runner objectiu inicial:
  - execucio integrada des de Python/Django
  - sense dependre de `pytest` a la primera iteracio
- `pytest` i `pytest-django` queden com a millora futura possible, no com a requisit inicial.

## Context Minim Per A Qualsevol Agent

### Punt d'entrada principal
- Pagina principal:
  - `competicions_trampoli/templates/competicio/inscripcions/inscripcions_page.html`
- Shell principal:
  - `id="inscripcions-page-shell"`
- Boot JSON:
  - `json_script` amb id `inscripcions-page-boot-data`

### Frontend modular actual
- Sidebar i navegacio de panells:
  - `competicions_trampoli/templates/competicio/inscripcions/_sidebar.html`
- Scripts principals:
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_core.html`
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_table.html`
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_sorting.html`
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_groups.html`
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_teams.html`
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_series.html`
  - `competicions_trampoli/templates/competicio/inscripcions/scripts/_media.html`

### API frontend rellevant ja existent
- Helpers del core:
  - `getJson`
  - `postJson`
  - `refreshHtmlFragments`
  - `ensurePanelLoaded`
  - `navigateWithUiState`
  - `reloadWithUiState`

### Rutes principals d'inscripcions
- Definides a:
  - `competicions_trampoli/urls/inscripcions.py`
- Families de rutes que els tests browser han de tocar:
  - pagina principal `inscripcions_list`
  - fragments de pagina
  - sorting
  - history undo/redo
  - grups
  - equips
  - series
  - media

### Tests actuals que ja cobreixen backend i contracte HTML
- `competicions_trampoli/tests/inscripcions/test_backend_smoke.py`
- `competicions_trampoli/tests/equips/test_workspace_ui.py`
- `competicions_trampoli/tests/inscripcions/test_media_flow.py`
- `competicions_trampoli/tests/inscripcions/groups/*`

### Conclusio Arquitectonica
- Els tests browser no han de duplicar tota la cobertura backend actual.
- El seu focus ha de ser:
  - execucio real del JS
  - interaccio d'usuari
  - refresc del DOM
  - estat de panells i botons
  - absencia d'errors de consola i `requestfailed`

## Resultat Final Esperat

```text
competicions_trampoli/tests/
  browser/
    __init__.py
    base.py
    fixtures.py
    helpers.py

    inscripcions/
      __init__.py
      test_smoke.py
      test_panels_lazy.py
      test_table_and_navigation.py
      test_sorting_and_history.py
      test_groups_workspace.py
      test_teams_workspace.py
      test_series_workspace.py
      test_media_workspace.py
```

## Principis Del Pla
- Cada fase ha de ser implementable i mergejable per separat.
- Cap fase ha de requerir que l'agent entengui tot el modul.
- Els subagents han de tenir write scopes disjunts tant com sigui possible.
- La base comuna s'ha de tancar aviat per evitar divergencies.
- La suite inicial ha de prioritzar smoke i estabilitat abans que cobertura exhaustiva.
- Les proves han de ser llegibles, orientades a comportament, i basades en selectors estables ja existents.
- Qualsevol canvi a codi productiu necessari per fer els tests mes robustos ha de ser minim, explicit i justificat.

## Regles Globals Per A Tots Els Agents

### Regla 1. No duplicar cobertura backend
- Si una accio ja queda demostrada per tests de model, servei o endpoint, el browser test nomes ha de validar:
  - que l'usuari pot activar-la
  - que el JS no falla
  - que la UI reacciona i reflecteix l'estat esperat

### Regla 2. Els browser tests han de fallar davant errors silenciosos
- Cada test o base comuna ha de recollir:
  - `console.error`
  - `pageerror`
  - `requestfailed`
- Qualsevol d'aquests errors no esperats ha de fer fallar el test.

### Regla 3. Seleccionar per ids i `data-*` existents
- Preferir selectors robustos ja presents:
  - `id=...`
  - `data-panel-key`
  - `data-panel-target`
- No introduir selectors CSS fragils si hi ha alternatives mes estables.

### Regla 4. No barrejar infraestructura i cobertura funcional a la mateixa PR si es pot evitar
- Primer base comuna i fixtures.
- Despres suites funcionals.

### Regla 5. Les dades de test han de ser petites i deterministes
- No fer servir datasets massius per defecte.
- Nomes crear el minim necessari per reproduir el flux.

### Regla 6. Un agent integrador controla el runner i la documentacio final
- Per evitar conflictes, el coordinador es l'unic que hauria de tocar:
  - la documentacio principal del pla
  - un eventual fitxer de runner agregat o comandament oficial
  - ajustos finals de naming i organitzacio

## Convencions De Paquet

### `browser/base.py`
- Ha de contenir:
  - classe base comuna browser
  - setup i teardown de Playwright
  - creacio de context i pagina
  - listeners per errors JS
  - helpers de login
  - helper per obrir `inscripcions_list`
  - helper per obrir panells lazy
  - helper `assert_no_browser_errors()`

### `browser/fixtures.py`
- Ha de contenir factories o mixins per:
  - competicio minima
  - usuari autenticat amb permisos
  - inscripcions de base
  - fixture opcional per grups
  - fixture opcional per equips/contextos
  - fixture opcional per series
  - fixture opcional per media

### `browser/helpers.py`
- Ha de contenir helpers purs de suport:
  - selectors de panells
  - asserts de badges o comptadors
  - espera de fragments carregats
  - lectura de textos de resum

### Tests per domini
- Cada fitxer sota `browser/inscripcions/` ha de tenir un scope clar i unic.
- Si una suite creix massa, s'ha de partir abans de superar les 500-700 linies.

## Fases

## Fase 0. Contracte Base I Esquelet Del Paquet

### Prioritat
- P0

### Responsable
- 1 agent coordinador

### Objectiu
- Crear el paquet nou i fixar la base tecnica comuna abans d'obrir carrils en paral.lel.

### Scope
- Crear l'arbre inicial sota `competicions_trampoli/tests/browser/`.
- Decidir la classe base i el patró de setup/teardown.
- Deixar documentat el contracte dels helpers compartits.

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/__init__.py`
- `competicions_trampoli/tests/browser/base.py`
- `competicions_trampoli/tests/browser/helpers.py`
- `competicions_trampoli/tests/browser/fixtures.py`
- aquest document

### Tasques
- Crear els directoris i `__init__.py` minims.
- Definir la base comuna de navegador.
- Definir com es capturen errors de consola i requests fallides.
- Definir helpers per login i obertura de la pagina.
- Deixar clar el comandament objectiu d'execucio.

### Criteri De Done
- El paquet es pot importar.
- Existeix base comuna usable per qualsevol suite.
- Els agents posteriors no necessiten reinventar setup de Playwright.

### Dependencia
- Cap

## Fase 1. Fixtures Compartides I Dades Minimes De Navegacio

### Prioritat
- P0

### Responsable
- 1 agent

### Objectiu
- Tenir dades petites, repetibles i enfocades a UI, no a benchmark.

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/fixtures.py`
- qualsevol helper petit estrictament necessari a `helpers.py`

### Scope
- Crear mixins o helpers per:
  - competicio base
  - usuari owner/editor autenticat
  - 6-12 inscripcions representatives
  - una combinacio minima de categoria, subcategoria i entitat
  - fixture per equips/contextos
  - fixture per media bàsica
  - fixture per series d'equip quan sigui necessari

### Restriccions
- No escriure encara suites grans de tests funcionals.
- No posar assertions de navegacio dins les fixtures.

### Criteri De Done
- Qualsevol suite funcional pot heretar o compondre fixtures sense duplicar creacio de dades.

### Dependencia
- Fase 0

## Fase 2. Smoke Suite Minima Obligatoria

### Prioritat
- P0

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_smoke.py`

### Objectiu
- Crear la suite curta que s'executara gairebe a cada canvi de frontend.

### Fluxos A Cobrir
- la pagina principal carrega amb el shell correcte
- el boot JSON hidrata la pagina sense errors JS
- no hi ha `console.error`, `pageerror` ni `requestfailed`
- la toolbar principal respon
- els controls globals basics no trenquen la pagina
- `undo` i `redo` son accessibles i no trenquen el JS encara que no hi hagi historial profund

### Tests Esperats
- `test_inscripcions_page_loads_without_browser_errors`
- `test_global_shell_controls_are_interactive`
- `test_history_controls_do_not_break_frontend_state`

### Criteri De Done
- Existeix una suite smoke curta i fiable.
- El temps d'execucio es manté baix.
- Aquesta suite es pot usar com a gate de canvi rapid.

### Dependencia
- Fase 0
- Fase 1

## Fase 3. Panells Lazy I Hidratacio Per Seccions

### Prioritat
- P0

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_panels_lazy.py`

### Objectiu
- Blindar el comportament que avui te mes risc de fallada silenciosa: panells que es carreguen al primer clic.

### Fluxos A Cobrir
- obrir panell `grups`
- obrir panell `equips`
- obrir panell `series-equips`
- obrir panell `media`
- comprovar que surten de l'estat "Carregant..."
- comprovar que el DOM final inclou elements reals del workspace
- reobrir panells i verificar que no queden en estat inconsistent

### Tests Esperats
- `test_groups_panel_lazy_loads_real_workspace_content`
- `test_teams_panel_lazy_loads_real_workspace_content`
- `test_series_panel_lazy_loads_real_workspace_content`
- `test_media_panel_lazy_loads_real_workspace_content`
- `test_switching_between_lazy_panels_preserves_stable_state`

### Criteri De Done
- Tota regressio de panell lazy trenca una suite dedicada.

### Dependencia
- Fase 0
- Fase 1

## Fase 4. Taula Principal, Navegacio I Estat De Pagina

### Prioritat
- P1

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_table_and_navigation.py`

### Objectiu
- Blindar refresh parcials i navegacio amb conservacio d'estat.

### Fluxos A Cobrir
- la taula principal renderitza i continua visible despres d'una accio lleugera
- canvi de panell actiu i retorn a la taula
- persistencia raonable de l'estat UI en refresh/navigate
- drawer d'accions i boto de back-to-top
- recarrega parcial de fragments sense trencar la pagina

### Tests Esperats
- `test_table_remains_usable_after_partial_refresh`
- `test_active_panel_state_survives_supported_navigation`
- `test_drawer_toggle_and_back_to_top_controls_work`

### Criteri De Done
- Els canvis a `reloadWithUiState` i `navigateWithUiState` queden protegits per navegador real.

### Dependencia
- Fase 0
- Fase 1
- idealment Fase 2

## Fase 5. Sorting, Columnes I History

### Prioritat
- P0

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_sorting_and_history.py`

### Objectiu
- Cobrir les accions lleugeres i frequents que sovint trenquen estat i refresh.

### Fluxos A Cobrir
- aplicar sorting
- treure un criteri de sorting
- netejar sorting
- obrir modal de custom sort i interactuar-hi minimament
- fer `undo`
- fer `redo`
- desar columnes si la fixture i la UX ho permeten de forma estable

### Tests Esperats
- `test_apply_sort_updates_ui_without_browser_errors`
- `test_remove_sort_updates_ui_without_browser_errors`
- `test_clear_sort_updates_ui_without_browser_errors`
- `test_custom_sort_dialog_opens_and_closes_cleanly`
- `test_undo_and_redo_restore_stable_ui_state`
- `test_save_columns_keeps_table_usable`

### Criteri De Done
- Els canvis a sorting/history trenquen aquesta suite abans d'arribar a produccio.

### Dependencia
- Fase 0
- Fase 1
- Fase 2

## Fase 6. Workspace De Grups

### Prioritat
- P0

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_groups_workspace.py`

### Objectiu
- Cobrir el workspace de grups com a superficie funcional independent.

### Fluxos A Cobrir
- carregar workspace de grups
- filtrar candidates
- seleccionar visibles
- previsualitzar creacio de grups per comptador o mida
- crear grups a partir de seleccio
- assignar a grup existent
- desactivar buits

### Restriccions
- No reproduir tota la combinatoria de backend del workspace.
- Nomes provar 2 o 3 camins principals d'usuari.

### Tests Esperats
- `test_groups_workspace_filters_and_selection_work`
- `test_groups_preview_by_count_renders_without_frontend_errors`
- `test_groups_create_from_preview_updates_board_state`
- `test_groups_assign_to_existing_group_updates_ui`
- `test_groups_delete_empty_keeps_workspace_stable`

### Criteri De Done
- Les regressions mes probables del workspace de grups ja queden visibles al browser.

### Dependencia
- Fase 0
- Fase 1
- Fase 3

## Fase 7. Workspace D'Equips

### Prioritat
- P0

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_teams_workspace.py`

### Objectiu
- Cobrir el workspace d'equips, que es una de les zones mes denses i mes faciles de trencar.

### Fluxos A Cobrir
- carregar workspace d'equips
- canviar context
- preview
- crear equip manual
- assignar o desassignar membres
- esborrar equips buits

### Tests Esperats
- `test_teams_workspace_loads_and_shows_summary`
- `test_team_context_switch_updates_workspace_without_errors`
- `test_team_preview_flow_is_interactive`
- `test_create_manual_team_updates_workspace`
- `test_unassign_or_delete_empty_keeps_workspace_stable`

### Criteri De Done
- Els canvis al workspace d'equips queden protegits per navegacio real.

### Dependencia
- Fase 0
- Fase 1
- Fase 3

## Fase 8. Workspace De Series D'Equip

### Prioritat
- P1

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_series_workspace.py`

### Objectiu
- Cobrir la UX basica del workspace de series, amb especial focus en refresh i seleccio d'aparell/context.

### Fluxos A Cobrir
- obrir panell i carregar workspace
- seleccionar aparell
- refrescar
- previsualitzar creacio o assignacio
- export start list de forma superficial

### Tests Esperats
- `test_series_workspace_loads_for_selected_app`
- `test_series_preview_create_does_not_break_ui`
- `test_series_preview_assign_does_not_break_ui`
- `test_series_refresh_keeps_workspace_usable`

### Criteri De Done
- Les regressions basiques de series ja no passen silenciosament.

### Dependencia
- Fase 0
- Fase 1
- Fase 3

## Fase 9. Workspace De Multimedia

### Prioritat
- P1

### Responsable
- 1 agent

### Fitxers D'Ownership
- `competicions_trampoli/tests/browser/inscripcions/test_media_workspace.py`

### Objectiu
- Cobrir els camins UI principals de multimedia sense convertir el browser test en una copia dels tests de backend.

### Fluxos A Cobrir
- carregar panell multimedia
- refrescar workspace
- editar i desar configuracio de matching
- executar preview
- aplicar matching en cas minim
- set primary o delete si la fixture ho permet de forma fiable

### Tests Esperats
- `test_media_workspace_loads_and_refreshes`
- `test_media_matching_config_can_be_saved_from_ui`
- `test_media_preview_runs_without_browser_errors`
- `test_media_apply_updates_workspace_state`
- `test_media_primary_or_delete_actions_keep_ui_stable`

### Criteri De Done
- Les regressions de multimedia a nivell de navegador ja es veuen abans de prod.

### Dependencia
- Fase 0
- Fase 1
- Fase 3

## Fase 10. Agregacio, Runner I Hardening Final

### Prioritat
- P1

### Responsable
- 1 agent coordinador

### Fitxers D'Ownership
- runner o documentacio final de comandaments
- ajustos menors a `base.py`
- aquest document si cal

### Objectiu
- Tancar la suite amb dos modes d'execucio:
  - smoke
  - full

### Tasques
- Decidir i documentar el comandament smoke.
- Decidir i documentar el comandament full.
- Revisar noms incoherents de tests i helpers.
- Detectar duplicacio entre suites.
- Revisar que la suite falla correctament davant d'errors JS.

### Criteri De Done
- Hi ha una manera clara i repetible d'executar:
  - una smoke suite curta
  - la suite browser completa

### Dependencia
- Fases 2 a 9

## Carrils Paral.lelitzables

### Carril A
- Infraestructura comunament compartida
- Fase 0
- Fase 1

### Carril B
- Smoke i shell general
- Fase 2

### Carril C
- Panells lazy
- Fase 3

### Carril D
- Taula i navegacio
- Fase 4

### Carril E
- Sorting i history
- Fase 5

### Carril F
- Workspace de grups
- Fase 6

### Carril G
- Workspace d'equips
- Fase 7

### Carril H
- Workspace de series
- Fase 8

### Carril I
- Workspace de media
- Fase 9

### Carril J
- Integracio final i runner
- Fase 10

## Ordre Recomanat D'Execucio
- Fase 0
- Fase 1
- En paral.lel:
  - Fase 2
  - Fase 3
  - Fase 4
  - Fase 5
  - Fase 6
  - Fase 7
  - Fase 8
  - Fase 9
- Fase 10

## Write Scope Recomanat Per Subagent

### Agent Coordinador
- `competicions_trampoli/tests/browser/base.py`
- `competicions_trampoli/tests/browser/helpers.py`
- `competicions_trampoli/tests/browser/fixtures.py`
- `competicions_trampoli/docs/pla_tests_browser_inscripcions.md`

### Agent Smoke
- `competicions_trampoli/tests/browser/inscripcions/test_smoke.py`

### Agent Lazy Panels
- `competicions_trampoli/tests/browser/inscripcions/test_panels_lazy.py`

### Agent Table Navigation
- `competicions_trampoli/tests/browser/inscripcions/test_table_and_navigation.py`

### Agent Sorting History
- `competicions_trampoli/tests/browser/inscripcions/test_sorting_and_history.py`

### Agent Groups
- `competicions_trampoli/tests/browser/inscripcions/test_groups_workspace.py`

### Agent Teams
- `competicions_trampoli/tests/browser/inscripcions/test_teams_workspace.py`

### Agent Series
- `competicions_trampoli/tests/browser/inscripcions/test_series_workspace.py`

### Agent Media
- `competicions_trampoli/tests/browser/inscripcions/test_media_workspace.py`

### Agent Integrador Final
- qualsevol ajust final minim
- runner/documentacio final

## Riscos Principals I Mitigacions

### Risc 1. Flakiness Per Esperes Incorrectes
- Mitigacio:
  - usar esperes de Playwright basades en UI real
  - no usar `sleep` arbitrari
  - esperar elements finals del panell, no textos intermedis poc fiables

### Risc 2. Duplicitat Amb Tests Backend
- Mitigacio:
  - cada suite browser ha de declarar quin flux UI cobreix
  - no revalidar tota la logica del servei

### Risc 3. Fixtures Massa Grosses
- Mitigacio:
  - fixtures petites i orientades a cas
  - crear helpers modulars i no un superescenari unic

### Risc 4. Conflictes Entre Agents A La Base Comuna
- Mitigacio:
  - Fase 0 i Fase 1 es tanquen abans d'obrir la resta
  - un sol coordinador toca la base comuna

### Risc 5. Tests Massa Ambiciosos
- Mitigacio:
  - separar smoke de full
  - preferir 2-5 assertions d'alt valor per test abans que tests llargs i fragils

## Checklists Operatius Per Cada Agent

### Abans De Comencar
1. Llegir aquest document.
2. Confirmar el write scope assignat.
3. Revisar els ids i selectors del panell o flux que tocaras.
4. Reutilitzar base comuna i fixtures existents abans de crear-ne de noves.

### Durant La Implementacio
1. Escriure primer el test nomes per al flux objectiu.
2. Mantenir el nom del fitxer alineat amb el seu scope.
3. Fer asserts curtes, orientades a comportament visible.
4. Verificar que el test falla si hi ha error de browser.

### Abans De Tancar
1. Executar la suite del fitxer nou.
2. Revisar que no s'han duplicat helpers compartits.
3. Revisar que no s'ha trencat naming o estructura del paquet.
4. Deixar nota curta del que cobreix i del que no cobreix.

## Definition Of Done Global
- Existeix el paquet `competicions_trampoli/tests/browser/`.
- La base comuna captura errors de navegador i requests fallides.
- Existeix una smoke suite curta i fiable.
- Existeixen suites funcionals separades per:
  - panells lazy
  - taula i navegacio
  - sorting/history
  - grups
  - equips
  - series
  - media
- Es poden executar de forma separada o agregada.
- La suite detecta regressions de frontend que avui escapen als tests Django backend.

## Criteri Final D'Exit
- Quan es toqui frontend d'inscripcions, es podra executar una suite browser curta abans de donar el canvi per bo.
- Quan es toqui una zona concreta, es podra executar la suite funcional del seu domini.
- Les regressions de botons morts, panells que no carreguen, refresh trencat i errors de JS silenciosos quedaran cobertes abans d'arribar a produccio.

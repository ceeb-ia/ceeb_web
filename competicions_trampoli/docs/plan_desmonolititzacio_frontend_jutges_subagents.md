# Pla De Desmonolititzacio Del Frontend De Jutges Per Subagents

## Objectiu
- Desmonolititzar el frontend del portal de jutges sense tocar backend.
- Limitar l'abast a `competicions_trampoli/templates/judge/portal.html`.
- Deixar la feina preparada per a execucio en paral.lel per diversos subagents amb write scopes disjunts.
- No canviar funcionalitat, contractes de context, ids DOM, ni endpoints.

## Decisio D'Abast
- **En scope**
  - `competicions_trampoli/templates/judge/portal.html`
  - nous parcials sota `competicions_trampoli/templates/judge/portal/`
- **Fora d'scope**
  - qualsevol vista Python
  - qualsevol servei
  - `judge_messages_hub.html`
  - `video.py`, `admin.py` i la resta de fitxers backend
- **Motiu**
  - el monolit critic del frontend de jutges es avui `portal.html` amb aproximadament 2601 linies.
  - la resta de fitxers de `judge/` no obliguen ara a una intervencio estructural si la prioritat es evitar tocar backend.

## Conclusio De Viabilitat
- **Si, es viable sense tocar backend.**
- El tall es pot fer nomes amb:
  - `{% include %}` de Django templates
  - un fitxer facade que continuara sent `templates/judge/portal.html`
  - scripts inline fragmentats en parcials carregats en ordre estricte
- No cal:
  - afegir noves variables de context
  - canviar URLs
  - canviar `json_script`
  - moure JS a `static/`

## Regles Dures De No Regressio
- No canviar cap `id`.
- No canviar cap `data-*` que avui consumeixi JS.
- No canviar cap nom de funcio global inline.
- No canviar cap text de botons o etiquetes llevat d'espais/indentacio neutra.
- No canviar l'ordre d'execucio dels scripts.
- No canviar l'ordre dels `json_script`.
- No canviar la logica dels modes `compact` i `competition_order`.
- No reordenar els blocs de render si aixo altera focus, navegacio o selectors.
- No deduplicar JS en aquesta fase si implica risc semantic.

## Problema Actual

### Monolit principal
- `competicions_trampoli/templates/judge/portal.html`
- Mida actual:
  - ~2601 linies
  - ~119 KB

### Responsabilitats avui barrejades
- CSS inline del portal
- shell de pagina i capcalera
- selector de `view_mode`
- navegacio de grups
- render de grups en dos modes
- render de targetes i panells per exercici
- suport/missatgeria lateral
- navegacio lateral d'inscripcions
- editor de puntuacio
- drafts i dirty state
- navegacio de teclat
- polling d'updates
- video local i upload/delete/status
- init global del portal

### Consequencia
- qualsevol canvi petit obliga a tocar un fitxer amb massa dominis.
- els conflictes de merge son gairebe inevitables.
- la regressio es dificil de detectar perque markup, estat i runtime conviuen sense fronteres clares.

## Arquitectura Objectiu

### Entrada principal que es mante
- `competicions_trampoli/templates/judge/portal.html`

### Rol del fitxer principal despres del refactor
- `extends "base.html"`
- `block title`
- inclusio de parcials HTML
- `json_script`
- un unic bloc `<script>` final que inclou parcials JS en ordre estricte

### Arbre Objectiu

```text
competicions_trampoli/templates/judge/
  portal.html

  portal/
    _styles.html
    _header.html
    _group_tabs.html
    _group_panes.html
    _nav_drawer.html
    _support_drawer.html
    _json_contract.html

    modes/
      _group_compact.html
      _group_competition_order.html
      _entry_card_compact.html
      _entry_card_competition_order.html
      _exercise_panel.html
      _video_panel.html

    scripts/
      _00_bootstrap.js.html
      _10_store.js.html
      _20_permissions.js.html
      _30_support.js.html
      _40_video.js.html
      _50_exercises.js.html
      _60_navigation.js.html
      _70_editor_render.js.html
      _80_save_updates.js.html
      _90_init.js.html
```

## Regles D'Arquitectura

### Regla 1. El backend no es toca
- Cap canvi a:
  - `views/judge/portal.py`
  - cap helper
  - cap servei
- El contracte de context actual s'ha de consumir tal com arriba avui.

### Regla 2. El JS continua sent inline en aquesta fase
- El portal actual depen de funcions globals i de l'ordre de declaracio.
- Moure JS a `static/` ara afegeix risc i no aporta res al tall inicial.
- El wrapper final ha de tenir un unic `<script>` amb `{% include %}` interns.

### Regla 3. El wrapper final el toca un sol integrador
- Per evitar conflictes de merge, nomes l'agent integrador ha d'editar:
  - `competicions_trampoli/templates/judge/portal.html`
- La resta d'agents creen i omplen nomes fitxers nous sota `templates/judge/portal/`.

### Regla 4. Primer fragmentar, despres netejar
- En aquesta fase no es fan:
  - renoms massius
  - deduplicacions agressives
  - reordenacio funcional
  - abstraccions noves
- Primer objectiu: mateixa sortida, fitxers mes petits.

### Regla 5. Els parcials han de seguir dominis reals
- No fragmentar "per mida".
- Fragmentar per domini:
  - layout
  - modes de render
  - suport
  - video
  - estat i drafts
  - navegacio
  - editor
  - save/polling/init

## Tall Natural Del HTML

### `portal/_styles.html`
- Tot el bloc `<style>` inline actual.
- No convertir-lo encara en asset static.
- No reordenar classes.

### `portal/_header.html`
- Capcalera superior del portal.
- Informacio de competicio/aparell/jutge.
- Selector de mode `Compacte / Ordre competicio`.
- Botons/toggles fixos del portal si formen part de la shell superior.

### `portal/_group_tabs.html`
- Pestanyes de grups i la seva activacio visual.
- Sense tocar la logica JS; nomes markup.

### `portal/_group_panes.html`
- Contenidor principal dels blocs de grup.
- Delegacio cap als parcials de `modes/`.

### `portal/_nav_drawer.html`
- Backdrop i drawer lateral de navegacio d'inscripcions.
- Cerca i contenidor de la llista lateral.

### `portal/_support_drawer.html`
- Backdrop i drawer lateral de suport.
- Thread, botons i input de missatge.

### `portal/_json_contract.html`
- Bloc dels `json_script`.
- Ha de mantenir exactament els ids actuals i el mateix ordre.

## Tall Natural Del Render Per Modes

### `portal/modes/_group_compact.html`
- Render d'un grup quan `portal_display_mode != "competition_order"`.
- Inclou el loop de targetes base del mode compacte.

### `portal/modes/_group_competition_order.html`
- Render d'un grup quan `portal_display_mode == "competition_order"`.
- Inclou les bandes per exercici i l'ordre seqencial per exercici.

### `portal/modes/_entry_card_compact.html`
- Shell de targeta individual/equip en mode compacte.
- Xips d'exercici.
- Host del panell d'exercicis.

### `portal/modes/_entry_card_competition_order.html`
- Shell de targeta individual/equip en mode ordre competicio.
- Cada targeta representa una entrada concreta `inscripcio + exercici`.

### `portal/modes/_exercise_panel.html`
- Panell de puntuacio d'un exercici.
- Head del panell.
- Contenidor de `status`, editor i accions.

### `portal/modes/_video_panel.html`
- Bloc de video dins d'un panell d'exercici.
- Nomes markup; cap canvi de logica.

## Tall Natural Del JS

### `portal/scripts/_00_bootstrap.js.html`
- Constants inicials del portal.
- Parse dels `json_script`.
- Helpers basics:
  - `schemaField`
  - `entryKey`
  - `exerciseKey`
  - `allExerciseKeys`
  - sanitize/persistencia de `view_mode`

### `portal/scripts/_10_store.js.html`
- Estat local en memoria:
  - drafts
  - dirty maps
  - `SCORES`
  - `VIDEO_STATE`
- Helpers de lectura/escriptura:
  - `getEntry`
  - `setEntry`
  - `getDraft`
  - `clearDraft`
  - `markDirty`
  - `clearDirty`
  - `hasDirty`

### `portal/scripts/_20_permissions.js.html`
- Resolucio de permisos i camps:
  - `normalizePerm`
  - `permKey`
  - `resolvedPermsForIns`
  - `permittedFieldCodesForIns`
  - helpers de presencia i puntuacio desada

### `portal/scripts/_30_support.js.html`
- Domini complet de suport:
  - `supportEls`
  - open/close/toggle drawer
  - unread badge
  - thread render
  - `requestQuickSupport`
  - `sendSupportMessage`
  - `pollSupportMessages`
  - `initSupportUi`

### `portal/scripts/_40_video.js.html`
- Domini complet de video:
  - `canRecordVideo`
  - `getVideoEls`
  - `setVideoStatus`
  - `applyVideoUiState`
  - `fetchVideoStatus`
  - `toggleRecord`
  - `uploadRecorded`
  - `deleteVideo`
  - `initVideoUI`

### `portal/scripts/_50_exercises.js.html`
- Domini d'exercicis:
  - obertura/tancament de panells
  - estat visual dels xips
  - exercici inicial
  - `copyPrev`
  - `loadVisibleExerciseVideos`

### `portal/scripts/_60_navigation.js.html`
- Domini de navegacio:
  - tabs de grup
  - URL del grup actiu
  - drawer lateral d'inscripcions
  - `collectInsNavRows`
  - `renderInsNavList`
  - `refreshInsNavStatuses`
  - focus de targeta i marques actives

### `portal/scripts/_70_editor_render.js.html`
- Render de l'editor de puntuacio:
  - navegacio de teclat
  - `renderPermNumber`
  - `renderPermList`
  - `renderPermMatrix`
  - `renderPermissionBlock`
  - `renderEditor`
  - `renderAllEditors`

### `portal/scripts/_80_save_updates.js.html`
- Persistencia i sync:
  - `buildPatchFromCard`
  - `saveNow`
  - `applyIncomingUpdate`
  - `pollUpdates`
  - `setStatus`

### `portal/scripts/_90_init.js.html`
- `buildPermText`
- `initPortalViewModeControl`
- `initGroupTabs`
- `initInsNavigation`
- `initSupportUi`
- `initVideoUI`
- `initExercisePanels`
- `loadVisibleExerciseVideos`
- `pollUpdates`

## Contractes Que No Es Poden Tocar

### Contracte DOM
- Qualsevol selector que avui consumeix el JS inline:
  - `data-exercise-panel`
  - `data-exercise-chip`
  - `data-group-pane`
  - `data-group-target`
  - `data-ins-id`
  - `data-exercici`
  - ids de drawers i botons

### Contracte De Runtime
- Funcions globals cridades des de markup inline:
  - `toggleRecord`
  - `uploadRecorded`
  - `deleteVideo`
  - `copyPrev`
  - `saveNow`

### Contracte De Context
- Mateixos ids per `json_script`:
  - `schema-data`
  - `judge-item-labels-data`
  - `perms-data`
  - `subjects-data`
  - `scores-data`
  - `updates-cursor-init`

## Estrategia D'Execucio Per Fases

### Fase 0. Inventari I Baseline
- Mesurar `portal.html`.
- Llistar parcials objectiu.
- Identificar selectors i funcions globals no negociables.
- No es fan canvis funcionals.

### Fase 1. Crear carcassa buida
- Crear l'arbre `templates/judge/portal/`.
- Crear tots els fitxers nous buits o amb comentari de capcalera.
- Encara sense tocar el wrapper principal.

### Fase 2. Extreure HTML sense tocar JS
- Moure markup a parcials HTML.
- El wrapper principal encara renderitza igual.
- Els includes han de ser estructurals, sense cap simplificacio logica.

### Fase 3. Extreure JS en ordre estricte
- Convertir el script inline gegant en un unic `<script>` amb includes interns.
- Mateix ordre de funcions i init.

### Fase 4. Smoke de no regressio
- Verificar que la sortida renderitzada i els fluxos manuals segueixen igual.
- No fer neteja extra encara.

## Repartiment En Paral.lel Per Subagents

## Agent 1. Layout i Shell
- **Write scope exclusiu**
  - `templates/judge/portal/_styles.html`
  - `templates/judge/portal/_header.html`
  - `templates/judge/portal/_group_tabs.html`
  - `templates/judge/portal/_nav_drawer.html`
  - `templates/judge/portal/_support_drawer.html`
  - `templates/judge/portal/_json_contract.html`
- **Responsabilitat**
  - extreure shell i estructures transversals
- **No toca**
  - `portal.html`
  - cap fitxer sota `scripts/`
  - cap fitxer sota `modes/`

## Agent 2. Render compacte
- **Write scope exclusiu**
  - `templates/judge/portal/modes/_group_compact.html`
  - `templates/judge/portal/modes/_entry_card_compact.html`
  - `templates/judge/portal/modes/_exercise_panel.html`
  - `templates/judge/portal/modes/_video_panel.html`
- **Responsabilitat**
  - extreure markup del mode compacte
- **No toca**
  - competicio order
  - scripts
  - wrapper principal

## Agent 3. Render ordre competicio
- **Write scope exclusiu**
  - `templates/judge/portal/modes/_group_competition_order.html`
  - `templates/judge/portal/modes/_entry_card_competition_order.html`
- **Responsabilitat**
  - extreure markup del mode `competition_order`
- **No toca**
  - compacte
  - scripts
  - wrapper principal

## Agent 4. Estat, permisos i editor
- **Write scope exclusiu**
  - `templates/judge/portal/scripts/_00_bootstrap.js.html`
  - `templates/judge/portal/scripts/_10_store.js.html`
  - `templates/judge/portal/scripts/_20_permissions.js.html`
  - `templates/judge/portal/scripts/_70_editor_render.js.html`
- **Responsabilitat**
  - base de dades client, permisos i render de l'editor

## Agent 5. Suport i video
- **Write scope exclusiu**
  - `templates/judge/portal/scripts/_30_support.js.html`
  - `templates/judge/portal/scripts/_40_video.js.html`
- **Responsabilitat**
  - aillar els dominis laterals amb estat propi

## Agent 6. Exercicis, navegacio i sync
- **Write scope exclusiu**
  - `templates/judge/portal/scripts/_50_exercises.js.html`
  - `templates/judge/portal/scripts/_60_navigation.js.html`
  - `templates/judge/portal/scripts/_80_save_updates.js.html`
  - `templates/judge/portal/scripts/_90_init.js.html`
- **Responsabilitat**
  - domini de navegacio, accions per exercici, save i polling

## Agent Integrador
- **Write scope exclusiu**
  - `competicions_trampoli/templates/judge/portal.html`
  - `templates/judge/portal/_group_panes.html`
- **Responsabilitat**
  - convertir `portal.html` en facade
  - enganxar parcials HTML
  - construir l'unic bloc `<script>` amb includes en ordre correcte
  - resoldre petits ajustos d'include/context
- **Regla**
  - no reescriu parcials aliens excepte si hi ha blocker real i explicit.

## Handoffs Obligatoris Entre Agents
- Cada agent ha de documentar:
  - quins selectors DOM ha preservat
  - quines funcions globals segueixen existint
  - si ha detectat dependencies amb un altre domini
- Si un agent necessita una variable no disponible al seu parcial:
  - no la crea al backend
  - eleva el blocker a l'integrador

## Ordre D'Integracio Recomanat
1. Agent 1 crea shell i parcials base.
2. Agents 2 i 3 extreuen markup dels dos modes en paral.lel.
3. Agents 4, 5 i 6 extreuen JS en paral.lel.
4. Integrador converteix `portal.html` en facade final.
5. Verificacio manual i tests existents.

## Criteris D'Acceptacio
- `portal.html` queda com a facade petita i llegible.
- Cap canvi de comportament visible per jutges.
- `compact` i `competition_order` continuen funcionant.
- Navegacio lateral continua funcionant.
- Suport lateral continua funcionant.
- Video continua funcionant.
- Save, polling i `copyPrev` continuen funcionant.
- No hi ha canvis de backend.

## Verificacio Recomanada Despres De La Integracio

### Smoke funcional manual
- Mode compacte:
  - obrir grup
  - obrir exercicis
  - editar camps
  - desar
  - comprovar estat lateral
- Mode ordre competicio:
  - navegar entrada per entrada
  - usar `copyPrev`
  - desar
- Suport:
  - obrir drawer
  - enviar missatge
  - veure unread badge
- Video:
  - gravar
  - pujar
  - esborrar

### Regressio de render
- Verificar que els ids de drawers, panells, xips i grups es mantenen.
- Verificar que el portal continua renderitzant amb el mateix context.

## No Objectius D'Aquesta Iteracio
- No moure JS a assets estatics.
- No convertir el portal a components JS.
- No separar encara `judge_messages_hub.html`.
- No tocar backend per "aprofitar" la refactoritzacio.
- No fer simplificacions semantiques aprofitant el tall.

## Recomanacio Final
- Aquesta desmonolititzacio s'ha de plantejar com un **refactor estructural de frontend pur**.
- El tall es pot fer amb risc controlat si es respecten tres coses:
  - wrapper unic
  - ordre estricte del JS
  - write scopes disjunts per agent
- Si durant l'execucio apareix la temptacio d'introduir nous helpers backend, s'ha de considerar fora d'abast i posposar.

## Estat Actual Despres De La Fase 1

### Wrapper principal
- `competicions_trampoli/templates/judge/portal.html`
- Rol actual:
  - facade
  - inclou layout HTML
  - inclou `json_script`
  - inclou un unic `<script>` amb els parcials JS en ordre

### Parcials HTML actuals
- `competicions_trampoli/templates/judge/portal/_styles.html`
- `competicions_trampoli/templates/judge/portal/_header.html`
- `competicions_trampoli/templates/judge/portal/_group_tabs.html`
- `competicions_trampoli/templates/judge/portal/_group_panes.html`
- `competicions_trampoli/templates/judge/portal/_nav_drawer.html`
- `competicions_trampoli/templates/judge/portal/_support_drawer.html`
- `competicions_trampoli/templates/judge/portal/_json_contract.html`

### Parcials de render per modes actuals
- `competicions_trampoli/templates/judge/portal/modes/_group_compact.html`
- `competicions_trampoli/templates/judge/portal/modes/_entry_card_compact.html`
- `competicions_trampoli/templates/judge/portal/modes/_group_competition_order.html`
- `competicions_trampoli/templates/judge/portal/modes/_entry_card_competition_order.html`
- `competicions_trampoli/templates/judge/portal/modes/_exercise_panel.html`
- `competicions_trampoli/templates/judge/portal/modes/_video_panel.html`

## Fase 2 Aplicada

### Objectiu de la fase 2
- No partir mes fitxers.
- Fer que les fronteres entre els parcials nous siguin coherents de veritat.
- Reubicar funcions que havien quedat en un fitxer incorrecte durant l'extraccio mecanica inicial.
- Mantenir exactament el contracte runtime i el comportament del portal.

### Moviments fets
- La logica de video ja no viu a `scripts/_90_init.js.html`; ara viu a:
  - `scripts/_40_video.js.html`
- La logica de navegacio de grups (`initGroupTabs`) ja no viu a `scripts/_90_init.js.html`; ara viu a:
  - `scripts/_60_navigation.js.html`
- La clau de navegacio lateral:
  - `NAV_LINKS_BY_INS`
  - `NAV_LINKS_BY_ENTRY`
  - `navEntryKey(...)`
  ara viu a `scripts/_60_navigation.js.html`
- L'estat i els helpers de video per entrada:
  - `getVideoState(...)`
  ara viu a `scripts/_40_video.js.html`
- La logica de `copyPrev(...)` ara viu amb el domini d'exercicis a:
  - `scripts/_50_exercises.js.html`
- El text de permisos renderitzat a la capcalera:
  - `buildPermText(...)`
  ara viu a `scripts/_20_permissions.js.html`
- L'estat visual de missatge de guardat:
  - `setStatus(...)`
  ara viu a `scripts/_80_save_updates.js.html`
- `scripts/_90_init.js.html` ara es nomes bootstrap final d'arrencada.

## Mapa Real Del Codi

### Layout i shell
- `competicions_trampoli/templates/judge/portal.html`
  - facade principal
- `competicions_trampoli/templates/judge/portal/_styles.html`
  - CSS inline del portal
- `competicions_trampoli/templates/judge/portal/_header.html`
  - capcalera, selector de mode, botons globals
- `competicions_trampoli/templates/judge/portal/_group_tabs.html`
  - tabs de grups
- `competicions_trampoli/templates/judge/portal/_group_panes.html`
  - delegacio cap als dos modes de render
- `competicions_trampoli/templates/judge/portal/_nav_drawer.html`
  - drawer lateral de navegacio
- `competicions_trampoli/templates/judge/portal/_support_drawer.html`
  - drawer lateral de suport
- `competicions_trampoli/templates/judge/portal/_json_contract.html`
  - `json_script` i contracte de dades cap al frontend

### Render compacte
- `competicions_trampoli/templates/judge/portal/modes/_group_compact.html`
  - wrapper d'un grup en mode compacte
- `competicions_trampoli/templates/judge/portal/modes/_entry_card_compact.html`
  - targeta base per inscripcio/equip en compacte

### Render ordre competicio
- `competicions_trampoli/templates/judge/portal/modes/_group_competition_order.html`
  - bandes per exercici dins d'un grup
- `competicions_trampoli/templates/judge/portal/modes/_entry_card_competition_order.html`
  - targeta individual `inscripcio + exercici`

### Components compartits de render
- `competicions_trampoli/templates/judge/portal/modes/_exercise_panel.html`
  - shell del panell d'exercici
  - suporta compacte i `competition_order`
- `competicions_trampoli/templates/judge/portal/modes/_video_panel.html`
  - markup del bloc de video i estat desactivat

### Bootstrap i estat base
- `competicions_trampoli/templates/judge/portal/scripts/_00_bootstrap.js.html`
  - parse de `json_script`
  - constants d'URL
  - claus de `localStorage`
  - estat global base (`SCORES`, drafts, cursors, etc.)

### Store i helpers base
- `competicions_trampoli/templates/judge/portal/scripts/_10_store.js.html`
  - `schemaField(...)`
  - `entryKey(...)`
  - `exerciseKey(...)`
  - `allExerciseKeys(...)`
  - `sanitizePortalDisplayMode(...)`
  - `persistPortalDisplayMode(...)`
  - `updatePortalDisplayMode(...)`
  - `initPortalViewModeControl(...)`
  - `getEntry(...)`, `setEntry(...)`
  - drafts / dirty helpers
  - navegacio de teclat d'inputs base

### Permisos
- `competicions_trampoli/templates/judge/portal/scripts/_20_permissions.js.html`
  - `normalizePerm(...)`
  - `permKey(...)`
  - `resolvedPermsForIns(...)`
  - `permittedFieldCodesForIns(...)`
  - `permissionTargetText(...)`
  - `buildPermText(...)`
  - `updateDraftValue(...)`
  - `decimalsStep(...)`

### Suport
- `competicions_trampoli/templates/judge/portal/scripts/_30_support.js.html`
  - tot el domini de missatgeria i suport
  - drawer
  - polling
  - unread badge
  - requesta rapida
  - enviament de missatge

### Video
- `competicions_trampoli/templates/judge/portal/scripts/_40_video.js.html`
  - `getVideoState(...)`
  - `canRecordVideo(...)`
  - `getVideoEls(...)`
  - `setVideoStatus(...)`
  - `chooseRecorderMimeType(...)`
  - `applyVideoUiState(...)`
  - `fetchVideoStatus(...)`
  - `toggleRecord(...)`
  - `uploadRecorded(...)`
  - `deleteVideo(...)`
  - `initVideoUI(...)`

### Exercicis
- `competicions_trampoli/templates/judge/portal/scripts/_50_exercises.js.html`
  - estat visual dels exercicis
  - `openExercisePanel(...)`
  - `refreshExerciseChipStates(...)`
  - `selectInitialExerciseForIns(...)`
  - `initExercisePanels(...)`
  - `loadVisibleExerciseVideos(...)`
  - `copyPrev(...)`

### Navegacio
- `competicions_trampoli/templates/judge/portal/scripts/_60_navigation.js.html`
  - `NAV_LINKS_BY_INS`
  - `NAV_LINKS_BY_ENTRY`
  - `navEntryKey(...)`
  - `setActiveGroup(...)`
  - `markActiveNav(...)`
  - `focusEntryCard(...)`
  - `collectInsNavRows(...)`
  - `renderInsNavList(...)`
  - `refreshInsNavStatuses(...)`
  - `openMobileInsNav(...)`
  - `closeMobileInsNav(...)`
  - `initInsNavigation(...)`
  - `initGroupTabs(...)`

### Render de l'editor
- `competicions_trampoli/templates/judge/portal/scripts/_70_editor_render.js.html`
  - `renderPermNumber(...)`
  - `renderPermList(...)`
  - `renderPermMatrix(...)`
  - `renderPermissionBlock(...)`
  - `renderEditor(...)`
  - `renderAllEditors(...)`

### Save i updates remots
- `competicions_trampoli/templates/judge/portal/scripts/_80_save_updates.js.html`
  - `setStatus(...)`
  - `buildPatchFromCard(...)`
  - `saveNow(...)`
  - `applyIncomingUpdate(...)`
  - `pollUpdates(...)`

### Init final
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`
  - wiring final d'arrencada
  - no hi ha logica de domini

## Residus Acceptats Despres De La Fase 2
- Encara hi ha dependencies globals entre parcials JS perque continuem dins un unic `<script>`.
- Això es acceptable en aquesta etapa per dues raons:
  - evita tocar backend
  - evita moure el portal a assets o mòduls JS encara

## Seguent Fase Recomanada
- Si es vol continuar, la fase seguent ja no hauria de ser "moure funcions", sino:
  - reforcar tests de contracte del portal fragmentat
  - reduir context implicit entre parcials de `modes/`
  - revisar si algunes utilitats de `_10_store.js.html` i `_70_editor_render.js.html` mereixen una frontera encara mes fina

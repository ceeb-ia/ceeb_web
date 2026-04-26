# Pla Per Fer El Portal De Jutges Mes Lleuger Per Fases

## Estatus Del Document
- Document operatiu per subagents.
- Objectiu: millorar el portal de jutges en competicions grans sense perdre informacio ni trencar front/back.
- Branca de referencia inicial: `visualitzacio_mode`.
- Aquest pla assumeix el portal desmonolititzat en partials:
  - `competicions_trampoli/templates/judge/portal/`
  - `competicions_trampoli/templates/judge/portal/scripts/`
- Cada fase ha de ser desplegable i verificable per separat.

## Resum Executiu
El portal actual fa massa feina abans de mostrar-se:
- construeix tots els grups i subjectes al backend
- envia `subjects-data` i `scores-data` complets
- renderitza targetes per tots els grups
- en mode `competition_order`, multiplica targetes per `inscripcions x exercicis`
- al carregar, el JS executa `renderAllEditors()` i construeix inputs per tots els panells presents al DOM
- el video status es pot demanar per massa panells quan la pantalla es gran

La estrategia segura es anar de menys risc a mes risc:
1. Mesurar.
2. Evitar renderitzar editors fins que calgui.
3. Evitar consultes de video fins que calgui.
4. Aprimar payload inicial sense canviar endpoints critics.
5. Nomes despres, carregar grups de manera asincrona.

## Objectius
- Fer que la primera carrega del portal sigui manejable en competicions grans.
- Mantenir intactes:
  - guardat parcial de notes
  - permisos de jutge
  - rehidratacio de puntuacions existents
  - polling d'updates
  - gravacio, pujada, estat i esborrat de videos
  - mode compacte
  - mode ordre competicio
  - context individual i context equip
- Evitar canvis massius en una sola PR.
- Deixar tests coherents en cada fase.

## No Objectius
- No redissenyar visualment el portal.
- No canviar la semantica de puntuacio.
- No canviar el model de dades.
- No substituir el sistema actual de polling.
- No passar a SPA completa.
- No introduir WebSockets o SSE en aquesta iteracio.
- No fer carregues asincrones de grup fins que el lazy local estigui validat.

## Mapa Del Portal Actual

### Backend principal
- `competicions_trampoli/views/judge/portal.py`
  - construeix `group_blocks`
  - construeix `out_of_program_group_blocks`
  - construeix `subjects_payload_json`
  - construeix `scores_payload_json`
  - resol `portal_display_mode`
- `competicions_trampoli/views/judge/save.py`
  - guarda un subjecte i exercici concret
- `competicions_trampoli/views/judge/updates.py`
  - retorna updates incrementals per exercici
- `competicions_trampoli/views/judge/video.py`
  - estat, fitxer, upload i delete de videos
- `competicions_trampoli/views/judge/messages.py`
  - suport i missatgeria

### Templates
- Shell:
  - `competicions_trampoli/templates/judge/portal.html`
- Contracte JSON:
  - `competicions_trampoli/templates/judge/portal/_json_contract.html`
- Pestanyes:
  - `competicions_trampoli/templates/judge/portal/_group_tabs.html`
- Panells:
  - `competicions_trampoli/templates/judge/portal/_group_panes.html`
- Modes:
  - `competicions_trampoli/templates/judge/portal/modes/_group_compact.html`
  - `competicions_trampoli/templates/judge/portal/modes/_group_competition_order.html`
  - `competicions_trampoli/templates/judge/portal/modes/_entry_card_compact.html`
  - `competicions_trampoli/templates/judge/portal/modes/_entry_card_competition_order.html`
  - `competicions_trampoli/templates/judge/portal/modes/_exercise_panel.html`
  - `competicions_trampoli/templates/judge/portal/modes/_video_panel.html`

### Scripts
- Bootstrap:
  - `competicions_trampoli/templates/judge/portal/scripts/_00_bootstrap.js.html`
- Store local:
  - `competicions_trampoli/templates/judge/portal/scripts/_10_store.js.html`
- Permisos:
  - `competicions_trampoli/templates/judge/portal/scripts/_20_permissions.js.html`
- Suport:
  - `competicions_trampoli/templates/judge/portal/scripts/_30_support.js.html`
- Video:
  - `competicions_trampoli/templates/judge/portal/scripts/_40_video.js.html`
- Exercicis i copy-prev:
  - `competicions_trampoli/templates/judge/portal/scripts/_50_exercises.js.html`
- Navegacio:
  - `competicions_trampoli/templates/judge/portal/scripts/_60_navigation.js.html`
- Render editors:
  - `competicions_trampoli/templates/judge/portal/scripts/_70_editor_render.js.html`
- Save i updates:
  - `competicions_trampoli/templates/judge/portal/scripts/_80_save_updates.js.html`
- Init:
  - `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`

## Principis D'Implementacio
- Primer reduir feina client-side, despres backend.
- No eliminar informacio; nomes retardar quan es construeix o consulta.
- `SCORES`, `SUBJECTS`, `DRAFTS` i la DB continuen sent fonts de veritat.
- El DOM es una projeccio reconstruible.
- Si una entrada te canvis pendents, no s'ha de destruir ni substituir sense avisar.
- Qualsevol endpoint nou ha de validar token, competicio i aparell igual que els endpoints actuals.
- Cada fase ha de tenir tests abans de continuar.

## Riscos Globals
- Perdre canvis pendents si es descarrega o substitueix DOM d'un grup.
- Marcar malament estats de navegacio si un subjecte encara no esta al DOM.
- Fer polling d'updates sense tenir carregat el subjecte i perdre update visual.
- Duplicar IDs DOM en recarregar grups.
- Trencar focus i navegacio amb Enter/Tab.
- Carregar videos massa tard i confondre el jutge.
- Trencar context team per falta de dades de `members` o `subject_kind`.

## Contractes Que No Es Poden Trencar

### Guardat
`judge_save_partial` ha de continuar rebent:
```json
{
  "subject_kind": "inscripcio",
  "subject_id": 123,
  "inscripcio_id": 123,
  "exercici": 1,
  "inputs_patch": {}
}
```
Per team:
```json
{
  "subject_kind": "team_unit",
  "subject_id": 456,
  "exercici": 1,
  "inputs_patch": {}
}
```

### Store Client
- `SUBJECTS_BY_ID` ha de poder resoldre `subjectForId(insId)`.
- `SCORES[domId].exercises[ex]` ha de contenir `inputs`, `outputs`, `total`, `updated_at`.
- `DRAFTS[entryKey(insId, exercici)]` no es pot sobreescriure amb dades del servidor.
- `DIRTY_BY_ENTRY[entryKey(insId, exercici)]` indica canvis pendents locals.

### Updates
- `judge_updates` pot retornar updates d'entrades que no estan visibles.
- Si el DOM no existeix, el client ha d'actualitzar `SCORES` i deixar el render per mes tard.

## Fase 0. Baseline I Instrumentacio Minima

### Prioritat
- P0

### Objectiu
Mesurar abans de canviar. Separar cost backend, mida de resposta i cost client inicial.

### Ownership Recomanat
- Agent A

### Fitxers Candidats
- `competicions_trampoli/views/judge/portal.py`
- `competicions_trampoli/tests/scoring/judge/`
- opcionalment un command o helper de benchmark nou si ja existeix patro local

### Tasques
- Mesurar temps del `GET judge_portal` en:
  - mode `compact`
  - mode `competition_order`
  - 1 exercici
  - diversos exercicis
  - volum mitja
  - volum gran
- Registrar:
  - temps total de request
  - mida de resposta HTML
  - mida de `subjects-data`
  - mida de `scores-data`
  - nombre de `group_blocks`
  - nombre total de subjectes
  - nombre de panells `[data-exercise-panel]`
- Afegir, si cal, instrumentacio temporal apagable per settings o flag local.
- No optimitzar res en aquesta fase.

### Tests
- No cal test funcional nou si nomes hi ha instrumentacio no productiva.
- Si s'afegeix command/helper, afegir smoke test senzill.

### Definition Of Done
- Hi ha dades abans/despres per comparar cada fase.
- Es coneix quin pes te HTML vs JSON vs render client inicial.

### Handoff Per Subagent
- No canviis UX.
- No canviis cap contracte.
- Entrega una nota curta amb nombres i observacions.

## Fase 1. Lazy Render D'Editors Sense Canviar Backend

### Prioritat
- P0

### Objectiu
Evitar que el navegador construeixi tots els inputs de puntuacio al carregar.

### Idea
Ara `renderAllEditors()` recorre tots els panells i crida `renderEditor()`. Aquesta fase ha de fer que nomes es renderitzin:
- el panell obert inicial de cada targeta en mode compacte, o millor nomes el grup actiu
- els panells visibles en mode ordre competicio
- qualsevol panell quan l'usuari l'obre

### Ownership Recomanat
- Agent B

### Fitxers Principals
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_70_editor_render.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_50_exercises.js.html`

### Tasques
- Substituir `renderAllEditors()` en init per una funcio mes selectiva:
  - `renderInitialVisibleEditors()`
  - o `renderVisibleEditorsInActiveGroup()`
- Fer `renderEditor()` idempotent:
  - si ja esta renderitzat i no hi ha peticio explicita de rerender, no fer res
  - si hi ha update remot i no hi ha dirty/focus, permetre rerender
- Afegir marca DOM:
  - `data-editor-rendered="1"` al contenidor `editor-inner-*`
- En `openExercisePanel()`, renderitzar l'editor de l'exercici obert si encara no existeix.
- En mode `competition_order`, renderitzar nomes els panells visibles del grup actiu.
- Garantir que `saveNow()` continua funcionant si l'editor s'ha renderitzat tard.
- Garantir que `copyPrev()` continua funcionant encara que el panell anterior no hagi estat renderitzat.

### Restriccions
- No canviar `portal.py`.
- No canviar payload JSON.
- No canviar `judge_save_partial`.
- No fer async encara.

### Tests Automatitzats Recomanats
- Ampliar tests existents del portal de jutge:
  - comprovar que el template inclou la funcio de lazy render
  - comprovar que no depen de `renderAllEditors()` massiu en init
- Test de contracte JS per text, similar als existents:
  - `renderEditor(insId, exercici)`
  - `data-editor-rendered`
  - `openExercisePanel` crida render lazy

### Smoke Manual
- Obrir portal compacte.
- Obrir Ex1 i Ex2 d'una inscripcio.
- Escriure nota, desar.
- Canviar de pestanya de grup i tornar.
- Mode ordre competicio:
  - desar una entrada
  - copy anterior
  - navegacio drawer

### Definition Of Done
- La primera carrega no renderitza editors de tot el portal.
- Cap canvi funcional visible per al jutge excepte millora de velocitat.
- Els tests de jutge existents continuen passant.

### Handoff Per Subagent
- El teu canvi es nomes front local.
- Si necessites saber si un editor esta renderitzat, fes-ho amb atribut DOM, no amb estat global fragil.
- No descarreguis ni eliminis DOM encara.

## Fase 2. Lazy Video Status Sense Amagar Videos

### Prioritat
- P0

### Objectiu
No consultar l'estat de video per entrades que el jutge encara no ha obert o vist.

### Aclariment Funcional
No es tracta de no mostrar videos. Es tracta de consultar-los tard:
- si el jutge obre l'exercici, es consulta video status
- si hi ha video, es mostra igual
- si grava o esborra, l'estat local s'actualitza igual

### Ownership Recomanat
- Agent C

### Fitxers Principals
- `competicions_trampoli/templates/judge/portal/scripts/_40_video.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_50_exercises.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`

### Tasques
- Auditar `loadVisibleExerciseVideos()`.
- Fer que nomes carregui video status per:
  - panell obert en mode compacte
  - panells visibles del grup actiu en mode ordre competicio, pero amb limit o observador si cal
- Afegir estat `loaded` per entrada/exercici si no existeix o reforcar-lo.
- Evitar peticions repetides quan el video status ja s'ha carregat.
- Despres d'upload/delete, actualitzar `recordedVideoByEntry` sense forcar reload global.
- En canvi de pestanya, carregar status nomes del que queda visible.

### Restriccions
- No treure botons de video.
- No canviar endpoints de video.
- No canviar validacio de video.

### Tests Automatitzats Recomanats
- Test template/JS:
  - `loadVisibleExerciseVideos`
  - `fetchVideoStatus`
  - `loaded`
- Tests backend existents de video han de seguir passant:
  - `competicions_trampoli.tests.scoring.judge.test_video_api`
  - `competicions_trampoli.tests.scoring.judge.test_media_context`

### Smoke Manual
- Obrir portal amb video activat.
- Confirmar que el boto gravar es visible.
- Obrir una entrada amb video existent i veure que apareix.
- Gravar, pujar, regravar i esborrar.
- Canviar de grup i tornar.

### Definition Of Done
- Videos continuen funcionant.
- El portal no dispara consultes de video per tot el DOM inicial.
- No hi ha regressio en upload/delete/status.

### Handoff Per Subagent
- No confonguis "lazy video status" amb "amagar videos".
- La UX final ha de continuar mostrant el video quan el jutge arriba a aquella entrada.

## Fase 3. Aprimar El Payload Inicial Sense Carrega Per Grup

### Prioritat
- P1

### Objectiu
Reduir mida de `subjects-data` i `scores-data` sense canviar encara a grups asincrons.

### Ownership Recomanat
- Agent D

### Fitxers Principals
- `competicions_trampoli/views/judge/portal.py`
- `competicions_trampoli/templates/judge/portal/_json_contract.html`
- `competicions_trampoli/templates/judge/portal/scripts/_00_bootstrap.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_10_store.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_80_save_updates.js.html`

### Tasques
- Revisar camps de `subject_list` realment consumits pel JS.
- Eliminar camps duplicats si son redundants:
  - `name` vs `nom_i_cognoms`
  - `order` vs `rotation_base_order_display` si no calen tots dos
- Revisar `scores_payload_json`:
  - no enviar `outputs` si el portal no els mostra
  - no enviar `total` si no s'usa visualment
  - mantenir `inputs` i `updated_at` si son necessaris per rehidratacio/status
- Validar que `applyIncomingUpdate()` pot omplir dades que no venien inicialment.
- Separar metadata de grups de subjects si ajuda a reduir duplicacio.

### Restriccions
- No canviar semantica del portal.
- No trencar `subjectForId()`.
- No trencar team context.
- No treure dades necessaries per permisos member slots.

### Tests Automatitzats Recomanats
- Test de context:
  - `subjects_payload_json` conte camps minims necessaris
  - `scores_payload_json` conte inputs per exercici
- Tests de save i updates:
  - save partial retorna i mergeja inputs
  - update remot continua aplicant-se
- Tests team:
  - subject team mante `members`, `subject_kind`, `subject_id`, `allowed_app_ids` si calen

### Smoke Manual
- Portal individual compacte.
- Portal individual ordre competicio.
- Portal team compacte.
- Portal team ordre competicio.
- Guardat, update remot i navegacio.

### Definition Of Done
- Mida del HTML/JSON baixa de manera mesurable.
- Cap regressio funcional.

### Handoff Per Subagent
- Fes canvis petits i justificats.
- Si un camp no saps si s'usa, busca al JS abans d'eliminar-lo.
- Documenta qualsevol camp eliminat i per que era redundant.

## Fase 4. Indexos I Consultes De Scores Per Feed/Carrega

### Prioritat
- P1

### Objectiu
Assegurar que les consultes de scores i updates escalen be.

### Ownership Recomanat
- Agent E

### Fitxers Principals
- `competicions_trampoli/models/scoring.py`
- migracio nova si cal
- `competicions_trampoli/views/judge/updates.py`
- `competicions_trampoli/views/judge/portal.py`

### Diagnosi Inicial
- `TeamScoreEntry` ja te index:
  - `competicio`, `comp_aparell`, `exercici`
- `ScoreEntry` te constraint unica:
  - `competicio`, `inscripcio`, `exercici`, `comp_aparell`
- `judge_updates` filtra per:
  - `competicio`
  - `comp_aparell`
  - `exercici__in`
  - cursor per `updated_at`, `id`
  - ordena per `updated_at`, `id`

### Tasques
- Amb baseline real, revisar query plans.
- Valorar index compost per `ScoreEntry`:
  - `competicio`, `comp_aparell`, `exercici`, `updated_at`, `id`
- Valorar index equivalent per `TeamScoreEntry` si el cursor ho necessita:
  - `competicio`, `comp_aparell`, `exercici`, `updated_at`, `id`
- No afegir indexos sense justificacio de consulta real.
- Afegir migracio separada si es decideix.

### Tests
- Test de migracio/arquitectura si el repo en te patro.
- Tests de `judge_updates` existents.

### Definition Of Done
- Qualsevol index nou esta justificat per query concreta.
- No hi ha regressio de migracions.

### Handoff Per Subagent
- No facis indexos per intuicio.
- Adjunta query plan o explicacio curta del motiu.

## Fase 5. Carrega Per Grup Amb Reload Segur

### Prioritat
- P1

### Objectiu
Reduir cost sense fer encara injeccio asincrona complexa: carregar nomes el grup actiu via request normal.

### Idea
Abans d'un endpoint async, es pot fer una versio conservadora:
- `GET /judge/<token>/?group=<id>`
- backend construeix tots els tabs, pero nomes renderitza cards/scores del grup actiu
- canviar pestanya fa navegacio normal a `?group=<id>`

### Ownership Recomanat
- Agent F

### Fitxers Principals
- `competicions_trampoli/views/judge/portal.py`
- `competicions_trampoli/templates/judge/portal/_group_tabs.html`
- `competicions_trampoli/templates/judge/portal/_group_panes.html`
- `competicions_trampoli/templates/judge/portal/scripts/_60_navigation.js.html`

### Tasques
- Separar metadata de grups:
  - key
  - label
  - count
  - out_of_program
- Construir `subject_list` nomes del grup actiu.
- Construir `scores_payload_json` nomes del grup actiu.
- Mantenir tabs de tots els grups.
- Quan es fa click a pestanya:
  - si hi ha canvis pendents, avisar abans de sortir
  - si no hi ha canvis pendents, navegar a `?group=<key>`
- Preservar `view_mode`, `franja`, `ex`.

### Restriccions
- Aquesta fase pot fer reload de pagina.
- No injectar HTML via fetch encara.
- No perdre drafts locals sense avis.

### Tests Automatitzats Recomanats
- `judge_portal` amb `group=<id>`:
  - `active_group_key` correcte
  - nomes subjects del grup actiu al payload
  - tabs continuen incloent altres grups
- Invalid group:
  - fallback a primer grup visible
- `view_mode=competition_order` + group:
  - render correcte nomes del grup actiu

### Smoke Manual
- Obrir grup 1.
- Canviar a grup 2.
- Tornar a grup 1.
- Provar amb canvi pendent i confirmar avis.
- Guardar despres de reload.

### Definition Of Done
- Primera carrega baixa molt en competicions amb molts grups.
- UX acceptable encara que canvi de grup recarregui.
- No es perden dades sense avis.

### Handoff Per Subagent
- Aquesta fase es deliberadament conservadora.
- No implementis fetch async encara.
- Mantingues el contracte de save/update igual.

## Fase 6. Endpoint Async Per Grup

### Prioritat
- P2

### Objectiu
Substituir el reload de Fase 5 per carrega asincrona de grups.

### Ownership Recomanat
- Agent G

### Endpoint Proposat
- `GET /judge/<uuid:token>/api/group/`

### Query Params
- `group=<key>`
- `view_mode=compact|competition_order`
- `franja=<id>` opcional
- `ex=<num>` opcional

### Resposta Proposada
```json
{
  "ok": true,
  "group": {
    "key": "12",
    "label": "Grup 12",
    "out_of_program": false
  },
  "html": "<div class=\"group-pane\" ...>",
  "subjects": [],
  "scores": {},
  "active_group_key": "12"
}
```

### Fitxers Principals
- `competicions_trampoli/urls/judge.py`
- `competicions_trampoli/views/judge/portal.py` o modul nou `views/judge/group_payload.py`
- `competicions_trampoli/templates/judge/portal/_group_panes.html`
- `competicions_trampoli/templates/judge/portal/scripts/_60_navigation.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_10_store.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`

### Tasques Backend
- Extreure helper compartit:
  - resoldre token i config
  - construir metadata de grups
  - construir payload d'un grup
  - renderitzar partial de grup
- Endpoint valida:
  - token valid
  - grup visible per aquell aparell
  - view mode valid
- Retornar HTML i payload parcial.

### Tasques Frontend
- En click de pestanya:
  - si grup ja carregat, activar-lo
  - si no carregat, fetch
  - injectar HTML
  - mergejar `subjects` dins `SUBJECTS_BY_ID`
  - mergejar `scores` dins `SCORES`
  - inicialitzar handlers del grup nou
  - renderitzar editors visibles del grup nou
  - carregar video status lazy del grup nou
- Afegir estat:
  - `LOADED_GROUPS`
  - `LOADING_GROUPS`
- Protegir canvis pendents:
  - si hi ha dirty en grup actual, confirmar abans de canviar

### Restriccions
- No destruir grups carregats si tenen dirty.
- No duplicar DOM.
- No canviar endpoints save/update/video.

### Tests Automatitzats Recomanats
- Endpoint group:
  - token invalid retorna 403
  - grup invalid retorna 400 o fallback documentat
  - grup valid retorna `html`, `subjects`, `scores`
  - respecta `view_mode`
  - respecta exclusions d'aparell
- Tests template:
  - HTML parcial conte IDs esperats
- Tests JS per contracte textual:
  - `LOADED_GROUPS`
  - merge de scores
  - proteccio dirty

### Smoke Manual
- Obrir portal gran.
- Canviar entre 3 grups sense reload.
- Guardar en un grup carregat async.
- Rebre update remot en grup no actiu i veure que apareix quan s'obre.
- Provar videos en grup carregat async.
- Provar suport SOS.

### Definition Of Done
- Canvi de pestanya no recarrega tota la pagina.
- No hi ha perdua de drafts.
- Save/update/video funcionen en grups carregats async.

### Handoff Per Subagent
- Aquesta fase depen conceptualment de Fase 5 o dels seus helpers.
- No facis virtual scroll encara.
- Prioritza robustesa sobre elegancia.

## Fase 7. Prefetch Suau Del Proper Grup

### Prioritat
- P2

### Objectiu
Fer que el canvi de pestanya sembli instantani sense tornar a carregar-ho tot al principi.

### Ownership Recomanat
- Agent H

### Tasques
- Despres de carregar el grup actiu, prefetch del grup seguent quan el navegador estigui idle.
- Usar `requestIdleCallback` amb fallback a `setTimeout`.
- Cancel.lar o ignorar prefetch si el jutge canvia abans.
- No prefetch si hi ha xarxa lenta o payload massa gran, si es pot detectar.

### Tests
- Test JS textual per existencia de mecanisme idle.
- Smoke manual en competicio gran.

### Definition Of Done
- El primer paint continua lleuger.
- El segon grup sovint ja esta preparat.
- No hi ha allau de requests.

## Fase 8. Virtualitzacio Opcional

### Prioritat
- P3

### Objectiu
Renderitzar nomes targetes que entren en pantalla, per competicions enormes.

### Per Que Es Ultima
Es la fase mes delicada:
- focus
- scroll
- navegacio
- copy-prev
- videos
- dirty state
- IDs DOM

### Ownership Recomanat
- Agent I, nomes si Fases 1-7 no son suficients.

### Restriccions
- No fer sense tests browser.
- No aplicar si el portal ja es prou rapid.

### Tests Recomanats
- Playwright o tests browser existents.
- Scroll llarg.
- Focus amb teclat.
- Guardat despres de scroll.
- Video despres de scroll.

## Repartiment Recomanat Per Subagents
- Agent A: Fase 0, baseline i instrumentacio.
- Agent B: Fase 1, lazy render d'editors.
- Agent C: Fase 2, lazy video status.
- Agent D: Fase 3, aprimar payload inicial.
- Agent E: Fase 4, indexos i query plans.
- Agent F: Fase 5, carrega per grup amb reload segur.
- Agent G: Fase 6, endpoint async per grup.
- Agent H: Fase 7, prefetch suau.
- Agent I: Fase 8, virtualitzacio opcional.

## Ordre Recomanat D'Execucio
1. Fase 0.
2. Fase 1.
3. Fase 2.
4. Re-mesura.
5. Fase 3 si encara pesa massa el JSON.
6. Fase 4 si query plans ho justifiquen.
7. Fase 5 si competicions grans encara carreguen massa lent.
8. Fase 6 quan Fase 5 estigui estable.
9. Fase 7 per polir UX.
10. Fase 8 nomes si cal.

## Matriu De Tests Per Fase

### Sempre Executar
- `python manage.py test competicions_trampoli.tests.scoring.judge --verbosity 1`
- `python manage.py test competicions_trampoli.tests.rotacions.test_ordering_display --verbosity 1`

### Si Es Toca Video
- `python manage.py test competicions_trampoli.tests.scoring.judge.test_video_api --verbosity 1`
- `python manage.py test competicions_trampoli.tests.scoring.judge.test_media_context --verbosity 1`

### Si Es Toca Team
- `python manage.py test competicions_trampoli.tests.scoring.team --verbosity 1`

### Si Es Toca Migracio/Indexos
- `python manage.py test competicions_trampoli.tests.architecture.test_migrations --verbosity 1`

### Smoke Manual Minim
- Portal compacte individual.
- Portal ordre competicio individual.
- Portal compacte team si hi ha dataset.
- Portal ordre competicio team si hi ha dataset.
- Guardar nota.
- Rebre update remot.
- Canviar grup.
- Gravar/pujar/esborrar video si QR ho permet.
- Obrir SOS i enviar missatge.

## Criteris De Qualitat Transversals
- Cada fase ha de poder revertir-se sola.
- No barrejar lazy render, async group loading i indexos en la mateixa PR.
- Qualsevol canvi de payload s'ha de documentar.
- Qualsevol nou endpoint ha de tenir test de token invalid.
- Qualsevol canvi que pugui perdre drafts ha de tenir confirmacio o guard rail.
- El mode `compact` i `competition_order` s'han de provar sempre junts.
- Individual i team s'han de considerar sempre, encara que una fase nomes toqui un mode.

## Checklist Per Cada PR/Fase
- [ ] Explica quin problema de performance resol.
- [ ] Enumera fitxers tocats.
- [ ] Indica contractes canviats o confirma que no n'hi ha.
- [ ] Tests automatitzats executats.
- [ ] Smoke manual fet.
- [ ] Baseline abans/despres si la fase impacta performance.
- [ ] Cap canvi pendent es pot perdre sense avis.
- [ ] No hi ha endpoints save/update/video trencats.

## Notes Per Als Subagents
- Si no tens context, comenca llegint aquest document i nomes els fitxers de la fase assignada.
- No intentis implementar fases posteriors "de passada".
- Si descobreixes que una fase necessita una altra, deixa-ho documentat i atura't abans de fer una refactoritzacio gran.
- Quan dubtis entre una solucio mes petita i una mes ambiciosa, tria la mes petita si preserva funcionalitat.
- El portal del jutge es una pantalla de competicio en directe: la prioritat es no perdre dades ni bloquejar el flux del jutge.

# Pla De Replantejament Del Panell De Notes Amb Franges, Cerca I Carrega Lazy

## Estatus Del Document
- Document operatiu per subagents sense context previ.
- Objectiu: replantejar el panell central de notes per competicions grans.
- Abast:
  - millora clara de navegacio i UI
  - franges com a eix de seguiment de competicio
  - unitats de rotacio compartides, incloent cel-les multi-grup
  - cerca directa de participants/equips
  - carrega lazy real de taules i scores
  - avisos de valors incoherents amb la configuracio de l'aparell
- Aquest document no implementa canvis; defineix una estrategia executable per fases.

## Resum Executiu
El panell actual de notes funciona, pero en competicions grans deixa de ser practic:
- La navegacio principal son pestanyes de grup. Si hi ha molts grups, ocupen massa pantalla.
- El flux real de competicio no es veu clarament. Encara que existeixi `franja`, l'usuari ha de buscar grups dins del panell.
- El DOM inicial crea contenidors per moltes combinacions `grup x aparell x exercici`.
- El JS executa `renderAll()` i pinta totes les taules en carregar, incloses les no visibles.
- El payload inicial inclou moltes dades globals: schemas, scores, inscripcions, media counts, videos de jutge i rotacions.
- No hi ha cerca directa d'inscripcio.
- No hi ha un sistema d'avisos centralitzat per valors sospitosos o fora de rang.

La nova direccio ha de convertir notes en un centre de control:
1. Seleccionar franja i aparell.
2. Veure immediatament que competeix ara.
3. Carregar nomes la taula necessaria.
4. Poder trobar qualsevol participant/equip en segons.
5. Mostrar avisos accionables abans que errors humans arribin a classificacions.

## Objectius
- Reduir drastricament el temps de primera carrega.
- Evitar que les pestanyes de grup siguin la navegacio principal.
- Fer evident quins grups/unitats competeixen a cada franja i aparell.
- Tractar una cel-la multi-grup com una sola unitat competitiva quan toca.
- Permetre cerca global de participant/equip.
- Mantenir el guardat parcial actual i el polling incremental.
- Fer que les taules es construeixin nomes quan l'usuari les obre.
- Afegir avisos no bloquejants per incoherencies de puntuacio.
- Fer cada fase desplegable i testejable independentment.

## No Objectius
- No canviar la semantica de calcul de puntuacions.
- No modificar el model de dades de `ScoreEntry` o `TeamScoreEntry`.
- No substituir el sistema actual de polling per WebSockets.
- No crear una SPA completa.
- No eliminar encara el mode sense franja; ha de quedar com a fallback.
- No bloquejar el desat per avisos de rang en una primera fase.
- No redissenyar el builder de schemas, excepte si cal exposar millor metadades ja existents.

## Mapa Actual

### Backend Principal
- `competicions_trampoli/views/scoring/notes.py`
  - vista `ScoringNotesHome`
  - construeix `groups_render`
  - construeix `out_of_program_groups_render`
  - construeix `schemas`
  - construeix `logical_schemas`
  - construeix `scores`
  - construeix `inscripcions`
  - construeix `media_counts_by_inscripcio`
  - construeix `judge_video_presence_by_key`
  - construeix `rotation_rank_map`
  - construeix `rotation_groups_by_app`
- `competicions_trampoli/views/scoring/save.py`
  - endpoints `scoring_save` i `scoring_save_partial`
  - resol subjecte individual o team
  - recalcula amb `ScoringEngine`
- `competicions_trampoli/views/scoring/updates.py`
  - endpoint `scoring_updates`
  - polling incremental per scores individuals i team
- `competicions_trampoli/views/scoring/media.py`
  - context multimedia de participant/equip
- `competicions_trampoli/views/scoring/helpers.py`
  - sanititzacio de inputs i serialitzacio de updates

### Template Actual
- `competicions_trampoli/templates/scoring/scoring_notes_home.html`
  - CSS inline duplicat en `content` i `extra_scripts`
  - pestanyes de grup
  - subpestanyes d'aparell
  - subpestanyes d'exercici
  - taules buides que despres omple JS
  - JSON complet via `json_script`
  - JS monolitic amb render, save, polling, multimedia i navegacio

### Funcions Client Critiques
- `renderAll()`
  - pinta totes les taules `data-scoring-table`.
- `buildHeader(table, schema)` i `buildBody(table, schema, exercici, appId, group)`
  - construeixen cada taula.
- `visibleRowsForAppGroup(group, appId, schema)`
  - filtra files locals a partir de `INS`.
- `saveEntry(insId, ex, appId, inputsPatch)`
  - envia `scoring_save_partial`.
- `pollUpdates()`
  - actualitza `SCORES` i re-renderitza taules afectades.
- `loadPlaybackContext(...)`
  - carrega multimedia sota demanda.

## Problemes A Resoldre

### 1. Navegacio Per Grups
Amb molts grups, les pestanyes consumeixen massa espai i no ajuden a seguir la competicio. El grup no hauria de ser l'eix principal quan existeix programa de rotacions.

### 2. Franja Poc Accionable
El backend ja accepta `?franja=...` i calcula `rotation_groups_by_app`, pero el selector esta retirat visualment i el resultat no explica be "que competeix ara".

### 3. Cel-les Multi-Grup
Quan una cel-la de rotacio conte diversos grups, la unitat real es la cel-la. El panell de notes ha d'alinear-se amb el portal de jutges:
- etiqueta `Grup A + Grup B`
- ordre combinat
- carrega i avisos per unitat
- no fusionar grups globalment fora d'aquella cel-la

### 4. Carrega Inicial Massa Gran
La primera carrega fa massa feina:
- DB: scores de tots els visibles
- HTML: contenidors per totes les combinacions
- JS: render de totes les taules
- client: molts inputs, listeners i calculs de headers

### 5. Sense Cerca Directa
L'organitzador ha de poder escriure el nom d'una gimnasta/equip i anar directament al context correcte.

### 6. Sense Avisos De Coherencia
El schema pot tenir `min`, `max`, `decimals`, `judges.count`, `items.count`, crash i presencia de jutges, pero el panell no fa una lectura d'aquests valors per avisar d'errors humans probables.

## Principis D'Implementacio
- Primer canvis client-side locals, despres endpoints nous.
- Cap fase ha de trencar el guardat actual.
- El DOM no ha de ser la font de veritat.
- `SCORES`, `INS`, schemas i dades carregades lazy han de poder rehidratar una taula.
- Si hi ha inputs pendents de desar, no destruir la taula sense flush o avís.
- Els avisos han de ser informatius en primera fase; no bloquejants.
- El mode franja ha de ser prioritari, pero el mode global ha de continuar existint.
- El polling ha de poder funcionar encara que una taula afectada no sigui al DOM.
- Els endpoints nous han de validar competicio, aparell, exercici i abast.

## Contractes Que No Es Poden Trencar

### Guardat Parcial
Endpoint existent:
```json
{
  "subject_kind": "inscripcio",
  "subject_id": 123,
  "inscripcio_id": 123,
  "exercici": 1,
  "comp_aparell_id": 45,
  "inputs_patch": {}
}
```

Per team:
```json
{
  "subject_kind": "team_unit",
  "subject_id": 456,
  "exercici": 1,
  "comp_aparell_id": 45,
  "inputs_patch": {}
}
```

### Store Client
- `SCORES[key]` conserva:
  - `inputs`
  - `outputs`
  - `total`
- `INS` o el nou store de subjectes ha de poder resoldre:
  - `id`
  - `subject_id`
  - `subject_kind`
  - `name`
  - `group`
  - `allowed_app_ids`
  - `meta`
- Les claus existents `inscripcio:<id>|<ex>|<app>` i `team_unit:<id>|<ex>|<app>` no s'han de canviar.

### Updates
`scoring_updates` ha de poder continuar retornant:
```json
{
  "ok": true,
  "updates": [
    {
      "subject_kind": "inscripcio",
      "subject_id": 123,
      "exercici": 1,
      "comp_aparell_id": 45,
      "inputs": {},
      "outputs": {},
      "total": 0
    }
  ],
  "next_since": "...",
  "next_after_id": "...",
  "has_more": false
}
```
Si la taula no esta carregada, el client ha d'actualitzar store i marcar el context com a "te updates pendents de render".

## Nou Model Mental De Pantalla

### Shell Principal
La pantalla hauria de tenir:
- Barra superior compacta:
  - Franja
  - Aparell
  - Exercici
  - Cerca
  - Estat d'updates
  - Botons de configuracio i QRs
- Columna o banda de "Programa actual":
  - per aparell
  - unitat competitiva
  - comptador de participants
  - avisos
  - progres de puntuacio
- Area central:
  - una sola taula activa
  - estat buit si no hi ha seleccio
  - loading skeleton mentre carrega
- Drawer o panell lateral:
  - resultats de cerca
  - avisos agrupats
  - fora de programa

### Mode Franja
Quan hi ha `franja` seleccionada:
- Mostrar les estacions/aparells d'aquella franja.
- Per cada aparell, mostrar la unitat de rotacio assignada.
- Si una cel-la te diversos grups, etiqueta combinada.
- L'usuari clica una unitat i es carrega la taula.

### Mode Global
Quan no hi ha franja:
- Mostrar una vista compacta per aparell i grup/unitat programada.
- Mantenir accés a fora de programa.
- La cerca ha de poder saltar a qualsevol participant.

## Contracte Nou Proposat: Unitats De Notes
Crear un concepte backend compartit amb rotacions:

```json
{
  "key": "unit:12+13",
  "kind": "rotation_cell",
  "label": "Grup 1 + Grup 2",
  "franja_id": 99,
  "franja_label": "Franja 2",
  "comp_aparell_id": 45,
  "app_label": "DMT",
  "member_keys": [12, 13],
  "subject_kind": "inscripcio",
  "count": 17,
  "order_mode": "rotate",
  "is_out_of_program": false
}
```

Per cel-la d'un sol grup, es pot conservar `key=12` o migrar gradualment a `unit:12`; recomanacio:
- Fase inicial: conservar clau antiga quan nomes hi ha un grup.
- Multi-grup: usar `unit:12+13`.

Per team:
```json
{
  "key": "unit:app-45-serie-7+app-45-serie-8",
  "kind": "team_rotation_cell",
  "label": "Serie 1 + Serie 2",
  "member_keys": ["app-45-serie-7", "app-45-serie-8"]
}
```

## Endpoints Nous Proposats

### 1. Manifest Del Panell
`GET /competicio/<pk>/scoring/notes/manifest/`

Retorna metadata lleugera:
```json
{
  "ok": true,
  "competition": {"id": 1, "name": "Comp"},
  "franges": [],
  "apps": [],
  "units": [],
  "out_of_program_units": [],
  "schema_summaries": {},
  "initial_context": {
    "franja_id": 99,
    "comp_aparell_id": 45,
    "exercici": 1,
    "unit_key": "unit:12+13"
  }
}
```

### 2. Carrega De Taula
`GET /competicio/<pk>/scoring/notes/table/`

Query:
- `franja_id`
- `comp_aparell_id`
- `exercici`
- `unit_key`
- `group` com a compat fallback

Retorna:
```json
{
  "ok": true,
  "context": {
    "franja_id": 99,
    "comp_aparell_id": 45,
    "exercici": 1,
    "unit_key": "unit:12+13"
  },
  "schema": {},
  "logical_schema": {},
  "subjects": [],
  "scores": {},
  "media_counts": {},
  "judge_video_presence": {},
  "rotation_rank": {},
  "warnings": []
}
```

### 3. Cerca
`GET /competicio/<pk>/scoring/notes/search/?q=...`

Retorna resultats accionables:
```json
{
  "ok": true,
  "results": [
    {
      "subject_kind": "inscripcio",
      "subject_id": 123,
      "name": "Participant",
      "meta": "Club - Categoria",
      "matches": ["nom"],
      "contexts": [
        {
          "franja_id": 99,
          "comp_aparell_id": 45,
          "exercici": 1,
          "unit_key": "unit:12+13",
          "label": "Franja 2 - DMT - Grup 1 + Grup 2"
        }
      ]
    }
  ]
}
```

### 4. Avisos Del Context
Opcional en fases posteriors:
`GET /competicio/<pk>/scoring/notes/warnings/?comp_aparell_id=...&franja_id=...`

Pot retornar avisos agregats sense carregar tota la taula.

## Sistema D'Avisos

### Tipus D'Avisos Recomanats
- `range_low`: valor menor que `field.min`
- `range_high`: valor major que `field.max`
- `decimal_precision`: mes decimals que `field.decimals`
- `missing_counting_judge`: jutge marcat com a present pero sense valor
- `value_without_presence`: valor introduit en jutge marcat com absent
- `judge_spread`: diferencia gran entre jutges del mateix camp
- `crash_inconsistent`: crash activat pero valors posteriors no buits
- `blocked_subject_has_score`: subjecte no elegible amb puntuacio
- `empty_required_like_field`: camp configurat com critic sense valor

### Contracte D'Avís
```json
{
  "id": "range_high:inscripcio:123:45:1:E:2:5",
  "severity": "warning",
  "code": "range_high",
  "message": "E J2 S5 supera el maxim 10",
  "subject_kind": "inscripcio",
  "subject_id": 123,
  "comp_aparell_id": 45,
  "exercici": 1,
  "field_code": "E",
  "judge": 2,
  "item": 5,
  "value": 12,
  "expected": {"min": 0, "max": 10}
}
```

### Visualitzacio
- Cel-la amb vora groga per warning i vermella per error.
- Icona petita dins la cel-la amb tooltip.
- Badge a la fila: `2 avisos`.
- Resum superior de la taula:
  - `3 avisos`
  - `1 valor fora de rang`
  - `2 jutges sense valor`
- Drawer lateral amb llista d'avisos clicables que enfoquen la cel-la.

### Validacio Client Vs Servidor
Fase inicial:
- Client calcula avisos a partir de schema i inputs locals.
- No bloqueja desat.

Fase posterior:
- Backend exposa utilitat compartida per recalcular avisos.
- Endpoints de table i warnings retornen avisos servidor.
- Tests garanteixen mateixa semantica.

## Pla Per Fases

## Fase 0. Preparacio I Mesura
Objectiu: entendre costos sense canviar comportament.

Tasques:
- Afegir instrumentacio lleugera opcional al panell:
  - temps de resposta backend
  - mida aproximada dels JSON
  - nombre de taules al DOM
  - temps de `renderAll()`
- Crear tests base que capturin el comportament actual.
- Documentar un dataset gran de prova o reutilitzar benchmark existent.

Fitxers probables:
- `competicions_trampoli/views/scoring/notes.py`
- `competicions_trampoli/templates/scoring/scoring_notes_home.html`
- tests a `competicions_trampoli/tests/rotacions/test_ordering_display.py` o nou paquet `tests/scoring/notes/`

Sortida esperada:
- Cap canvi UX significatiu.
- Metriques visibles en consola o en mode debug.

## Fase 1. Lazy Render Local Sense Endpoints Nous
Objectiu: guany rapid sense canviar backend.

Tasques:
- Substituir `renderAll()` per `renderActiveTableOnly()`.
- Renderitzar una taula quan:
  - es mostra per primera vegada
  - rep update i esta visible
  - l'usuari canvia columnes visibles
- Marcar cada taula amb `data-rendered="1"`.
- Evitar construir headers/bodies de taules ocultes.
- Al canviar pestanya, renderitzar nomes el nou context.
- Mantenir `SCORES` global inicial igual que ara.

Riscos:
- Focus perdut en canviar pestanyes.
- Updates d'una taula no renderitzada.
- Scrollbar superior no inicialitzada fins render.

Tests:
- Primera carrega no omple totes les taules.
- En activar una pestanya, la taula es renderitza.
- Un update remot d'una taula oculta actualitza store i no falla.
- Guardat continua funcionant.

## Fase 2. Nova Navegacio Compacta Sense Backend Lazy
Objectiu: resoldre el problema visual de pestanyes.

Tasques:
- Substituir la llista visible de pestanyes de grup per:
  - selector de franja
  - selector d'aparell
  - selector d'unitat/grup
  - cerca local sobre `INS`
- Mantenir les pestanyes antigues amagades o no renderitzades darrere una flag temporal.
- Mostrar un resum `Programa de la franja`:
  - aparell
  - unitat
  - nombre de subjectes
  - estat de puntuacio
- Si no hi ha franja, mostrar mode global compacte.

Fitxers:
- `scoring_notes_home.html`
- pot ser recomanable fragmentar en partials:
  - `templates/scoring/notes/_layout.html`
  - `templates/scoring/notes/_toolbar.html`
  - `templates/scoring/notes/_program.html`
  - `templates/scoring/notes/_table_shell.html`
  - `templates/scoring/notes/_scripts.html`

Tests:
- Amb molts grups, no hi ha `nav-tabs` massiu de grups.
- Selector de franja conserva query string.
- Seleccionar aparell/unitat activa la taula correcta.
- Fora de programa continua accessible.

## Fase 3. Unitats De Rotacio Al Panell De Notes
Objectiu: alinear notes amb rotacions i portal de jutges.

Tasques:
- Crear helper compartit per construir unitats de rotacio per notes.
- Reutilitzar la semantica de:
  - `rotation_unit_key`
  - `rotation_unit_label`
  - `build_rotation_unit_step_map`
- Canviar `rotation_groups_by_app` per una estructura compatible amb unitats.
- Quan una cel-la te `Grup A + Grup B`, la taula mostra files combinades.
- L'ordre de rotacio s'aplica sobre la llista combinada.
- La cerca ha de trobar participants dins unitats multi-grup.

Fitxers:
- `competicions_trampoli/services/rotacions/rotacions_ordering.py`
- nou possible servei:
  - `competicions_trampoli/services/scoring/notes_units.py`
- `competicions_trampoli/views/scoring/notes.py`
- `scoring_notes_home.html`

Tests:
- Multi-grup en una cel-la dona una unitat `Grup A + Grup B`.
- `rotate` mou el primer participant de la llista combinada, no el primer de cada grup.
- Una mateixa parella de grups nomes es fusiona en l'aparell/franja on comparteix cel-la.
- Fora de programa no queda fusionat accidentalment.

## Fase 4. Endpoint Manifest
Objectiu: reduir el payload inicial.

Tasques:
- Crear endpoint `notes_manifest`.
- Fer que la pagina inicial carregui:
  - franges
  - aparells
  - unitats
  - comptadors
  - schemas resumits si cal
- Retirar del payload inicial:
  - `scores`
  - `media_counts`
  - `judge_video_presence`
  - possiblement `inscripcions` completes
- La UI renderitza shell i programa sense taules completes.

Fitxers:
- `competicions_trampoli/views/scoring/notes.py`
- `competicions_trampoli/urls/scoring.py` o paquet d'urls corresponent
- tests d'endpoint

Tests:
- Manifest no retorna scores.
- Manifest retorna unitats correctes per franja.
- Manifest funciona sense franges.
- Access control igual que panell actual.

## Fase 5. Endpoint De Taula Lazy
Objectiu: carregar scores i subjectes nomes pel context actiu.

Tasques:
- Crear endpoint `notes_table`.
- Reutilitzar logic de scoring actual pero filtrada per:
  - franja
  - aparell
  - exercici
  - unitat/grup
- Retornar schema, subjectes, scores i avisos del context.
- Client:
  - cacheja contexts carregats
  - mostra skeleton
  - conserva pending saves
  - renderitza taula quan arriba payload

Riscos:
- Doble update entre polling i resposta lazy.
- Context carregat mentre hi ha saves pendents.
- Search jump a context no carregat.

Tests:
- Carregar taula d'una unitat retorna nomes subjectes esperats.
- Exclusions per aparell es respecten.
- Team mode es respecta.
- Scores existents rehidraten inputs i outputs.
- Guardar despres de carrega lazy funciona.

## Fase 6. Cerca Global
Objectiu: trobar una inscripcio/equip directament.

Tasques:
- Implementar endpoint `notes_search`.
- Buscar per:
  - nom
  - entitat
  - categoria
  - subcategoria
  - grup
  - ordre de competicio
  - equip/serie quan aplica
- Retornar contexts navegables.
- Client:
  - input persistent amb debounce
  - resultats en drawer/popup
  - accio `Obrir`
  - obrir context lazy i enfocar fila

Tests:
- Cerca per nom troba inscripcio.
- Cerca retorna context de franja/aparell/unitat.
- Participant en cel-la multi-grup apunta a unitat combinada.
- Cerca de team subject funciona.

## Fase 7. Avisos Client-Side
Objectiu: donar feedback immediat sense bloquejar.

Tasques:
- Afegir motor client de warnings:
  - `validateScoreContext(schema, subjects, scores)`
  - `validateInputValue(field, value, path)`
- Pintar avisos en taula.
- Crear resum superior i drawer d'avisos.
- Recalcular avisos en input, update remot i carrega lazy.

Fitxers:
- idealment extreure JS a partials:
  - `_notes_store.js.html`
  - `_notes_render.js.html`
  - `_notes_warnings.js.html`
  - `_notes_lazy.js.html`
  - `_notes_search.js.html`

Tests:
- Unit tests browser si existeixen.
- Tests de template/HTML per contracte basic.
- Tests de JS poden ser limitats si no hi ha infraestructura; prioritzar integracio Django.

## Fase 8. Avisos Servidor
Objectiu: tenir avisos consistents, auditables i consultables.

Tasques:
- Crear servei Python:
  - `competicions_trampoli/services/scoring/score_warnings.py`
- Entrades:
  - schema
  - score inputs
  - subject metadata
  - comp_aparell
- Sortida:
  - llista d'avisos amb contracte estable
- Integrar a `notes_table`.
- Opcional: endpoint agregat `notes_warnings`.

Tests:
- Rang min/max.
- Decimals.
- Presencia de jutges.
- Matrix amb crash.
- Team shared/member fields.

## Fase 9. Neteja I Desmonolititzacio
Objectiu: fer mantenible el panell.

Tasques:
- Fragmentar template monolitic.
- Separar CSS de JS quan sigui raonable.
- Eliminar CSS duplicat.
- Eliminar codi mort de pestanyes antigues.
- Documentar contractes finals.

## Paquets De Treball Per Subagents

### Subagent A. Backend Manifest I Unitats
Ownership:
- `competicions_trampoli/services/scoring/notes_units.py`
- `competicions_trampoli/views/scoring/notes.py`
- urls de scoring
- tests backend d'unitats i manifest

Tasques:
- Construir unitats de rotacio per franja/aparell.
- Incloure multi-grup com una sola unitat.
- Preparar contracte manifest.
- No tocar render de taules.

### Subagent B. Frontend Shell I Navegacio
Ownership:
- `competicions_trampoli/templates/scoring/scoring_notes_home.html`
- nous partials de `templates/scoring/notes/`

Tasques:
- Crear toolbar compacta.
- Substituir pestanyes massives.
- Afegir selector de franja/aparell/unitat.
- Preservar fallback sense franja.

### Subagent C. Lazy Table Client
Ownership:
- JS de notes dins template o partials nous.

Tasques:
- Renderitzar nomes taula activa.
- Cache de contexts.
- Integrar endpoint `notes_table`.
- Gestionar pending saves i updates.

### Subagent D. Search
Ownership:
- endpoint `notes_search`
- UI de cerca
- tests de cerca

Tasques:
- Cerca backend amb contexts.
- Drawer/popup de resultats.
- Obrir context i enfocar fila.

### Subagent E. Warnings
Ownership:
- `services/scoring/score_warnings.py`
- JS warnings
- tests de warning

Tasques:
- Definir contracte d'avisos.
- Implementar validacio client-side inicial.
- Implementar validacio servidor posterior.
- Integrar resum i focus a cel-la.

### Subagent F. Tests I Regressio
Ownership:
- `competicions_trampoli/tests/scoring/notes/`
- tests existents que calgui ajustar

Tasques:
- Crear fixtures grans controlades.
- Cobrir individual, team, multi-grup i fora de programa.
- Cobrir access control.
- Cobrir lazy loading i updates.

## Ordre Recomanat De Treball
1. Fase 1: lazy render local.
2. Fase 3 parcial: unitats de rotacio en servei, sense UI nova.
3. Fase 2: nova navegacio compacta.
4. Fase 4: manifest.
5. Fase 5: table lazy.
6. Fase 6: cerca.
7. Fases 7 i 8: avisos.
8. Fase 9: neteja.

## Estrategia De Migracio Segura
- Mantenir la vista actual darrere una flag o fallback durant les primeres fases.
- Si el manifest falla, carregar mode antic.
- Si `notes_table` falla, mostrar error accionable i no perdre dades locals.
- No destruir una taula amb inputs pendents sense:
  - flush de saves pendents, o
  - confirmacio de l'usuari.
- Mantenir `scoring_save_partial` com a endpoint unic de guardat.

## Tests Minims Abans De Considerar-ho Fet
- `python manage.py check`
- tests de rotacions existents
- tests de scoring judge/save existents
- tests nous:
  - manifest basic
  - table lazy individual
  - table lazy team
  - multi-grup en franja
  - cerca per participant
  - warning range high/low
  - update remot en context no carregat

## Criteris D'Acceptacio UX
- En una competicio gran, la primera pantalla mostra controls i programa sense esperar render massiu.
- L'usuari pot seleccionar una franja i veure immediatament que competeix a cada aparell.
- Una cel-la `Grup A + Grup B` es veu com una unitat.
- Es pot trobar una gimnasta pel nom i obrir la seva taula en menys de dos clics.
- Les taules amagades no existeixen o no estan renderitzades fins que calen.
- Els avisos son visibles, concrets i clicables.
- El guardat parcial continua igual de fiable.

## Preguntes Obertes
- El selector de franja ha de recordar l'ultima franja usada per usuari/session?
- En mode global, la unitat principal ha de ser aparell o grup?
- Els avisos de rang han de bloquejar mai el desat o nomes alertar?
- Quin llindar defineix `judge_spread` per cada aparell/camp?
- Cal un mode "taula completa" per administradors que vulguin veure-ho tot com abans?
- La cerca ha de trobar tambe registres fora de programa per defecte?

## Notes Per A Agents
- No revertir canvis aliens.
- Separar canvis funcionals i refactors.
- No fer una PR massiva amb manifest, lazy, search i warnings alhora.
- Qualsevol endpoint nou ha de tenir tests de permisos/accessos.
- Qualsevol canvi de contracte JSON ha d'estar documentat en aquest fitxer o en un successor.

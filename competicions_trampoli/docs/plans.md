# Pla d'acció: estabilitzar el gestor de grups V1

## Resum
Corregir el gestor de grups sense tocar models ni migracions. L’objectiu és que totes les accions manuals visibles funcionin de manera consistent, que els errors de backend siguin visibles a l’usuari i que el mode compacte treballi sobre la selecció real del llistat principal.

## Canvis d’implementació
### 1. Cablejat correcte del `rename`
- A [`_groups_panel.html`](/c:/Users/Extra/Desktop/ceeb_web/competicions_trampoli/templates/competicio/_groups_panel.html) afegir l’editor inline del detall del grup, perquè el JS ja espera aquests nodes.
- El detall ha d’incloure:
  - `#groups-detail-name-editor`
  - `#groups-detail-name-input`
  - botó `.js-save-group-name`
  - botó `.js-cancel-group-name`
- Unificar el flux de rename perquè tant:
  - `Renombrar` de les targetes de grup
  - `Editar nom` del panell de detall
  acabin al mateix handler.
- Decisió: el botó del detall deixarà de dependre de `data-group-action="rename"` i s’alinearà amb el mateix patró que les targetes (`data-group-rename` o selector equivalent únic).
- El rename continuarà reutilitzant l’endpoint existent `inscripcions_set_group_name`; no s’afegeix cap endpoint nou.

### 2. Gestió d’errors visible per a totes les accions manuals
- A [`_groups_workspace_script.html`](/c:/Users/Extra/Desktop/ceeb_web/competicions_trampoli/templates/competicio/_groups_workspace_script.html) embolcallar amb `try/catch`:
  - `previewAction()`
  - `runAction()`
  - `fetchWorkspace()`
  - `fetchDetail()`
- Qualsevol resposta `400` o error de xarxa s’ha de mostrar amb `showAlert(err.message || err)`.
- Mantenir el text retornat pel backend com a font principal del missatge, especialment per:
  - bloquejos de rotacions
  - `group invalid`
  - `group not empty`
- Decisió: no es canvia la semàntica dels endpoints; només es fa visible el feedback que ja existeix.

### 3. Sincronitzar la selecció real del llistat amb el gestor
- El gestor no pot continuar depenent només de la selecció inicial o del botó `Importar seleccio`.
- A [`_groups_workspace_script.html`](/c:/Users/Extra/Desktop/ceeb_web/competicions_trampoli/templates/competicio/_groups_workspace_script.html) exposar `window.__groupsWorkspaceApi.setExternalSelection(ids)`.
- Aquest mètode ha de:
  - reemplaçar `state.selectedIds`
  - refrescar resum de selecció
  - rerenderitzar candidates visibles si el workspace ja està carregat
  - no fer cap `POST` automàtic
- Al listener existent del llistat principal de `.js-team-row-select`, cridar `setExternalSelection(getSelectedInscripcioIds())`.
- El botó `Importar seleccio del llistat` es manté, però passa a ser redundància útil, no dependència funcional.
- Decisió: la selecció “selected” del gestor és sempre live respecte al llistat principal.

### 4. Tancar el contracte frontend/backend del resum
- Mantenir com a claus canòniques del backend les actuals de servei:
  - `groups_total`
  - `groups_with_members`
  - `empty_groups`
  - `assigned_count`
  - `unassigned_count`
  - `programmed_groups`
  - `out_of_program_groups`
- Adaptar el frontend perquè deixi de llegir:
  - `groups_without_members`
  - `programmed_groups_count`
  - `out_of_program_count`
- Decisió: no afegir aliases nous al backend; la correcció serà al frontend per reduir dispersió.
- Revisar també els badges del resum compacte perquè consumeixin les mateixes claus canòniques.

### 5. Endurir el flux de botons i estats
- Revisar els handlers dels botons del detall perquè tots facin una de dues coses:
  - o tenen selector propi explícit
  - o passen per `data-group-action` amb branca implementada
- Evitar botons “ornamentals” sense handler real.
- Mantenir la lògica actual de bloqueig per rotacions i desactivació de grups buits sense canviar regles de negoci.

## APIs i interfícies
- No es creen endpoints nous.
- No es modifiquen models ni migracions.
- S’afegeix una interfície JS pública nova:
  - `window.__groupsWorkspaceApi.setExternalSelection(ids: string[] | number[])`
- Es manté `inscripcions_set_group_name` com a únic punt de desat del nom del grup.
- Es manté la política actual dels endpoints `groups_*`; només millora el consum al frontend.

## Pla de proves
- `Editar nom` des del detall obre editor, desa i refresca l’estat.
- `Renombrar` des d’una targeta de grup obre el mateix editor i desa correctament.
- `Crear grup nou amb seleccio` al mode compacte funciona després de marcar checkboxes al llistat principal sense haver de prémer `Importar seleccio`.
- `Assignar seleccio` i `Treure seleccio` treballen sobre la selecció viva del llistat.
- Si el backend bloqueja una acció per rotacions, l’usuari veu un missatge explícit.
- Si s’intenta `Desactivar grup buit` sobre un grup no buit, es veu error explícit.
- Els comptadors del workspace mostren valors reals per:
  - buits
  - programats
  - fora de programa
- Regressió:
  - ordre de competició del grup continua obrint-se des de targeta i detall
  - historial `undo/redo` continua arribant via payload i actualitzant la UI

## Millores futures
- Unificar el patró del gestor de grups amb el d’equips en un helper JS compartit per evitar divergències de wiring i d’error handling.
- Afegir testos frontend o testos Django amb assertions de payload per blindar el contracte de claus del workspace.
- Fer que el backend retorni un camp `error_code` estable, a més del missatge humà, per permetre UX més rica sense parsejar textos.
- Afegir un estat visual de “loading/disabled” mentre s’executa cada acció manual per evitar dobles clics i donar feedback immediat.
- Consolidar els selectors de botons en convencions úniques (`data-group-*`) i eliminar dependències de selectors mixtos (`data-*` + classes JS) que ara fan més fàcil trencar el wiring.

## Assumptions i defaults
- No es toca l’esquema de base de dades.
- No es canvia cap regla funcional de rotacions, eliminació o assignació.
- El backend actual és vàlid en lògica de negoci; el problema principal és de integració frontend i de feedback d’errors.
- Les claus canòniques del resum queden fixades al backend actual, i el frontend s’hi adapta.



PLAN 2

# Pla d'acció per alinear `team_unit` sense trencar el flux de notes

## Resum
Fer un tall net del model nou d’aparells globals `team` perquè tots els fluxos de notes treballin amb el mateix contracte i el mateix subjecte canònic.

Objectiu operatiu:
- el panell d’organització i el portal de jutges han de guardar exactament el mateix model de dades a DB
- el polling de les dues vistes ha de tornar exactament el mateix contracte lògic
- les classificacions actuals han de continuar igual, sense començar a dependre de `TeamScoreEntry`
- s’elimina la dependència funcional de payloads legacy `subject_kind=equip` i claus runtime `__mN`

Decisió tancada:
- fer `tall net`, sense compatibilitat temporal amb `subject_kind=equip`
- el contracte nou únic per aparells globals `team` és `subject_kind=team_unit`

## Canvis d’implementació
### 1. Contracte únic de scoring per aparells globals `team`
- Fixar `team_unit` com a subjecte únic per a tots els endpoints de team:
  - `scoring_save`
  - `scoring_save_partial`
  - `scoring_updates`
  - `judge_save_partial`
  - `judge_updates`
  - `judge_video_status`
  - `judge_video_upload`
  - `judge_video_delete`
- Rebutjar explícitament qualsevol payload team amb:
  - `subject_kind=equip`
  - `inscripcio_id` sense `team_unit`
  - claus runtime com `E__m1`, `E__m2`, etc.
- Mantenir el contracte individual intacte:
  - `subject_kind=inscripcio`
  - inputs plans actuals

### 2. Contracte lògic d’inputs per a `team_unit`
- Definir com a contracte únic d’entrada i sortida per aparells `team`:
  - camp `shared`: valor directe actual
  - camp `member`: mapa per membre real, amb clau `member_id`
- Exemple canònic:
```json
{
  "subject_kind": "team_unit",
  "subject_id": 123,
  "inputs_patch": {
    "SYNC": 7.5,
    "E": {
      "41": 8.1,
      "44": 8.2
    }
  }
}
```
- Si hi ha crash per camps individuals, usar també mapa per `member_id`, no arrays ni `__mN`
- `__mN` queda restringit exclusivament a representació runtime interna del motor

### 3. Backend compartit entre panell d’organització i jutges
- Extreure a un helper comú la preparació de scoring team:
  - resolució de subjecte
  - càlcul de `member_count`
  - construcció de runtime schema
  - conversió `logical -> runtime`
  - càlcul del motor
  - conversió `runtime -> logical`
- Fer que `views_scoring.py` i `views_judge.py` passin pel mateix helper
- `judge_portal` ha de carregar l’schema runtime amb `member_count` real del `team_subject`
- `judge_save_partial` ha de seguir exactament el mateix pipeline que `scoring_save_partial`
- `judge_updates` ha de retornar inputs lògics, no inputs runtime
- `scores_payload_json` inicial del portal ha de seguir el mateix contracte lògic que retorna el polling

### 4. Permisos de jutge adaptats al model nou
- Mantenir l’admin de permisos amb:
  - `field_code`
  - `scope`
  - `judge_index`
  - `item_start`
  - `item_count`
- Eliminar `runtime_field_code` com a concepte funcional per a team
- Semàntica final:
  - `scope=shared`: el jutge edita el valor compartit únic
  - `scope=member`: el jutge edita el mateix camp per tots els membres visibles de la unitat competitiva
- La sanitització de patch s’ha de fer contra la shape lògica del camp, no contra codis expandits runtime
- Si el camp és `matrix` o `list`, `judge_index/item_start/item_count` continuen aplicant-se dins del valor de cada membre

### 5. Frontend del panell d’organització
- La UI de `scoring_notes_home` ha de continuar treballant amb inputs lògics
- Per aparells `team`:
  - renderitzar una fila per `team_unit`
  - `shared` una sola vegada
  - `member` com a bloc per membre real
- El save al backend ha d’enviar només payload lògic
- El polling ha d’actualitzar el store local amb payload lògic
- No s’ha d’introduir cap dependència UI de `member_slot` o codis `__mN`

### 6. Frontend del portal de jutges
- Re-renderitzar el portal perquè treballi amb camps base, no amb `runtime_field_code`
- La UI ha de mostrar:
  - context
  - equip
  - participants
- Per cada permís `member`, el bloc visible ha de repetir-se per cada membre real del `team_unit`
- Drafts, autosave, `copy previous` i refresc per polling han d’operar sobre el contracte lògic
- El portal no ha de fer `schemaField("E__m2")`; ha de resoldre sempre el camp base `E`

### 7. DB i invariants
- La persistència final de `TeamScoreEntry.inputs` ha de quedar en format lògic
- El runtime expandit només existeix durant el càlcul del motor
- No tocar `ScoreEntry` ni el flux individual
- No tocar classificacions perquè encara no consumeixen aparells globals `team`
- No afegir dependència del live de classificacions a `TeamScoreEntry.updated_at`
  - les classificacions actuals exclouen aparells globals `team`
  - el polling/live de classificacions ha de quedar igual

## Fluxos que s’han de conservar
- Panell d’organització:
  - escriure input
  - guardar a DB
  - polling remot
  - playback/video per `team_unit`
- Portal de jutges:
  - escriure input
  - draft local
  - guardar a DB
  - polling remot
  - video sobre `team_unit`
- Classificacions:
  - `classificacions_live_data` i `public_classificacions_live_data` sense canvis funcionals
  - no han de refrescar per canvis en notes `team` si l’aparell està exclòs de classificacions actuals

## Pla de tests
- `scoring_save_partial` en team accepta només `subject_kind=team_unit`
- `scoring_save_partial` en team rebutja `subject_kind=equip`
- `scoring_save_partial` en team rebutja claus `__mN`
- `TeamScoreEntry.inputs` queda guardat en format lògic per `member_id`
- `judge_save_partial` usa exactament el mateix contracte i mateix resultat que `scoring_save_partial`
- `judge_updates` retorna inputs lògics per `team_unit`
- `scoring_updates` retorna inputs lògics per `team_unit`
- `judge_portal` renderitza 2, 3 i 4 membres sense dependència de slots fixos
- `copy previous` al portal no introdueix claus runtime
- `scoring_notes_home` rep polling remot i actualitza correctament camps `shared` i `member`
- video status/upload/delete funciona sobre `team_unit`
- classificacions live no canvien de comportament per notes team
- regressió individual:
  - `inscripcio` continua guardant igual
  - polling individual continua igual
  - classificacions actuals individuals i d’equip agregat per membres continuen igual

## Assumptions i defaults
- No s’implementa encara classificació nova basada en `team_unit`
- El live de classificacions actual continua depenent només de `ScoreEntry` i configuració de classificacions
- El model final de permisos de jutge per team és semàntic per camp, no per slot runtime
- El format persistent de `TeamScoreEntry.inputs` serà lògic i estable
- El tall net implica actualitzar tests i qualsevol JS/client intern que encara emeti `equip` o `__mN`




JA IMPLEMENTED: per revisio

# Pla de canvis per afegir `member_treatment` als aparells globals d’equip

## Resum
Afegir una nova capa de càlcul només per aparells globals `team`: `member_treatment(...)`. Aquesta funció treballarà sobre una sèrie de valors escalaritzats per membre i permetrà aplicar selecció i agregació entre membres. El model queda així:

- tractament dins de cada membre: `row_compute`, `column_compute`, `select_sum`, etc.
- tractament entre membres: `member_treatment(...)`
- els helpers actuals `members_sum/avg/min/max/count` es mantenen com a sugar del nou model

La decisió funcional queda tancada així:
- API pública nova: `member_treatment(...)`
- inputs permesos: camps `member` escalars i `computed` derivats que produeixin un escalar per membre
- `members_sum/avg/min/max/count` continuen existint, però conceptualment passen a ser casos simples del nou mecanisme

## Canvis principals
### 1. Contracte funcional nou
- Afegir `member_treatment(source, select='all', n=None, agg='sum')` al llenguatge de fórmules.
- `source` només pot ser una sèrie per membre amb valor escalar per membre.
- `select` ha de suportar com a mínim:
  - `all`
  - `best_n`
  - `worst_n`
- `agg` ha de suportar com a mínim:
  - `sum`
  - `avg`
  - `min`
  - `max`
  - `count`
- `members_sum(X)`, `members_avg(X)`, `members_min(X)`, `members_max(X)`, `members_count(X)` es mantenen i es documenten com sucre sintàctic sobre `member_treatment`.

### 2. Regles de tipus i escalarització
- Només s’activa en aparells globals `competition_unit='team'`.
- Un camp `member` base de tipus `number` és directament vàlid per `member_treatment`.
- També és vàlid qualsevol `computed` derivat d’un camp `member` si el resultat per membre és escalar.
- Es considera “escalar per membre”:
  - `number`
  - `list` d’1 element reduïda explícitament a escalar
  - `matrix` 1x1 reduïda explícitament a escalar
  - qualsevol computed que el motor/validator marqui com a `member_scalar`
- No és vàlid aplicar `member_treatment` directament sobre:
  - `list` o `matrix` per membre no reduïts
  - cap objecte que segueixi sent `member_vector` o `member_matrix`
- `row_compute` sobre un camp `member` passa a produir explícitament un resultat “per membre”. Si la seva sortida és escalar, ja és admissible per `member_treatment`.

### 3. Motor i validador
- Estendre el motor perquè, a més de “scalar/list/matrix”, conegui metadades de nivell membre:
  - `member_scalar`
  - `member_list`
  - `member_matrix`
  - `shared_scalar`
  - `shared_list`
  - `shared_matrix`
- `member_treatment` només accepta `member_scalar` i retorna un `shared_scalar`.
- El validator ha de rebutjar:
  - `member_treatment` en aparells `individual`
  - `member_treatment` sobre `shared`
  - `member_treatment` sobre `member_list` o `member_matrix`
  - fórmules amb `__mN`, que continuen prohibits
- El validator ha de permetre:
  - `member_treatment(E)` si `E` és `member` escalar
  - `member_treatment(e_member)` si `e_member` és un computed `member_scalar`
- Els helpers actuals `members_*` es validen amb la mateixa regla interna que `member_treatment`.

### 4. Builder i ajuda d’usuari
- En aparells globals `team`, el builder ha d’afegir `member_treatment` a l’autocomplet i a les fórmules guiades.
- El text d’ajuda ha de canviar de “usa `members_sum(E)` o `members_avg(E)`” a una explicació en dues capes:
  - primer redueix cada membre si cal
  - després agrega entre membres amb `member_treatment(...)` o amb els sugars `members_*`
- Afegir validació visual clara:
  - si el camp encara és `nxm`, no es pot aplicar `member_treatment`
  - si primer fas `row_compute(...)` i el resultat és escalar, sí
- Mantenir etiquetes UI:
  - `Individual`
  - `Compartit`

### 5. Compatibilitat i comportament existent
- No es toca el model públic del schema guardat: continua sent global, amb `scope` lògic.
- No es reintrodueix cap model de slots `__mN`.
- Els schemata existents amb `members_sum/avg/min/max/count` continuen funcionant sense migració.
- El motor intern pot implementar `members_*` com wrappers de `member_treatment` per reduir duplicació.

## Casos de prova
- Acceptar `member_treatment(E)` quan `E` és un camp `member` de tipus `number`.
- Acceptar `member_treatment(row_compute(E,...))` quan `E` és `matrix` per membre i `row_compute` el redueix a escalar.
- Rebutjar `member_treatment(E)` si `E` és `matrix` o `list` per membre no reduït.
- Rebutjar `member_treatment(S)` si `S` és `shared`.
- Rebutjar qualsevol ús de `member_treatment` en aparell global `individual`.
- Verificar equivalència funcional:
  - `members_sum(E)` == `member_treatment(E, select='all', agg='sum')`
  - `members_avg(E)` == `member_treatment(E, select='all', agg='avg')`
- Verificar selecció:
  - `best_n` i `worst_n` sobre camps `member_scalar`
- Verificar que el builder mostra ajuda/autocomplet coherents i errors de validació correctes.

## Assumptions i defaults
- Signatura inicial recomanada: `member_treatment(source, select='all', n=None, agg='sum')`.
- El primer v1 només necessita `all`, `best_n`, `worst_n` i agregacions `sum/avg/min/max/count`.
- “Escalaritzable” no vol dir “escalar automàticament”: la reducció de `list/matrix` ha de ser explícita amb un computed previ.
- `members_sum/avg/min/max/count` es mantenen com a API estable i sugar del nou model, no es deprequen.

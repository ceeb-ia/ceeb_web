

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




PLAN 3: Revision


# Permisos QR per membre en aparells d’equip

## Resum
- Corregir el cas actual en què un permís `scope=member` acaba mostrant `Camp no disponible al schema: E` al portal de jutges.
- Estendre els permisos del QR perquè, en aparells d’equip, un camp individual pugui apuntar a `un`, `varis` o `tots` els membres del subjecte.
- Fer servir sempre slots estables `M1`, `M2`, `M3`, ... com a model de targeting, no persones concretes.
- Mantenir el model actual per camps `shared` i per aparells no d’equip.

## Canvis clau
### Model lògic dels permisos
- Mantenir els camps existents del permís: `field_code`, `scope`, `judge_index`, `item_start`, `item_count`.
- Afegir als permisos de tipus `member`:
  - `member_mode`: `"single" | "subset" | "all"`
  - `member_slots`: llista d’enters 1-based, ex. `[1]`, `[1,2]`; buida o absent quan `member_mode="all"`.
- Regla de compatibilitat:
  - permisos antics amb `scope="member"` i sense `member_mode` es tracten com `member_mode="all"` mentre no es regravin.
- No fer migracions de BD; el camp `permissions` ja és JSON i pot absorbir l’extensió.

### Admin de QRs
- A la UI de creació/edició de permisos:
  - mantenir `scope = Compartit / Individual`
  - si `scope="Individual"` i l’aparell és d’equip, mostrar controls de targeting:
    - `Tots els membres`
    - `Només un membre`
    - `Diversos membres`
  - per `Només un membre`, selector simple `M1/M2/M3/M4`
  - per `Diversos membres`, multi-select de slots
- Validació de backend:
  - `shared` no pot portar `member_mode` ni `member_slots`
  - `member` en aparell no d’equip continua invalid
  - `member_mode="single"` exigeix exactament un slot
  - `member_mode="subset"` exigeix almenys un slot i sense duplicats
  - `member_mode="all"` no necessita slots
  - no validar contra nombre real de membres en crear el QR; això es resol en temps d’execució per subjecte

### Resolució runtime al portal
- Introduir una capa de resolució de permisos abans de renderitzar inputs:
  - `shared` continua resolent a un únic `runtime_field_code = field_code`
  - `member + single/subset/all` es resol a una o més entrades runtime:
    - `E__m1`, `E__m2`, ...
- La resolució s’ha de fer per subjecte actual, perquè el nombre real de membres pot variar.
- Si un permís apunta a `M3` i el subjecte només té 2 membres:
  - aquell subpermís no es renderitza
  - no ha de provocar error global del bloc
- El missatge `Camp no disponible al schema: E` ha de desaparèixer per aquests casos perquè el portal ja no ha de buscar el codi base `E` quan és un permís individual.

### Render i captura al portal de jutges
- Per cada permís individual resolt, renderitzar un bloc separat amb capçalera clara:
  - `Execució · M1 [E] · Jutge 1`
  - `Execució · M2 [E] · Jutge 1`
- Per `member_mode="all"`, renderitzar tots els slots disponibles del subjecte en ordre.
- Per `member_mode="subset"`, renderitzar només els slots demanats i existents.
- Reutilitzar la lògica actual de camps runtime `E__m1`, `E__m2`, etc.; no inventar un format nou al frontend.
- La sanitització del patch ha de permetre els codis runtime expandits resultants, no només el codi base.
- El resum visible del QR al portal i a la pantalla d’admin/print ha de mostrar també el target:
  - `E · Individual · M1`
  - `E · Individual · M1,M2`
  - `E · Individual · Tots`

### Conversió d’inputs i scoring
- Mantenir la distinció existent entre schema lògic i schema runtime.
- Seguir usant la conversió lògica/runtime ja existent per camps de membre:
  - lògic: mapa per camp base i membre
  - runtime: codis expandits `__mN`
- No canviar el contracte de càlcul del scoring; el canvi només ha de millorar com el QR selecciona i edita quins `runtime_field_code` es poden tocar.

## Interfícies i comportament esperat
- Nou shape de permís individual en tokens:
```json
{
  "field_code": "E",
  "scope": "member",
  "judge_index": 1,
  "member_mode": "single",
  "member_slots": [1]
}
```
- Permís “tots”:
```json
{
  "field_code": "E",
  "scope": "member",
  "judge_index": 1,
  "member_mode": "all"
}
```
- La funció que avui calcula `runtime_field_code` per permisos s’ha de substituir per una resolució més rica:
  - a l’admin pot continuar generant una etiqueta resum
  - al portal ha de produir una llista de codis runtime efectius per subjecte
- No canviar rutes existents ni el flux general de QR, només el contracte intern de `permissions`.

## Pla de proves
- Validació admin:
  - camp `member` en aparell d’equip admet `single`, `subset`, `all`
  - `single` amb més d’un slot falla
  - `subset` buit falla
  - `shared` amb metadata de membre falla o es normalitza fora
- Compatibilitat:
  - un permís antic `{"field_code":"E","scope":"member"}` es tracta com `all`
- Portal:
  - un QR amb `single M1` renderitza només `E__m1`
  - un QR amb `subset M1,M2` renderitza dos blocs
  - un QR amb `all` renderitza tots els membres disponibles
  - si es demana `M3` i el subjecte només té 2 membres, no hi ha error i no es renderitza `M3`
  - desapareix el missatge `Camp no disponible al schema: E` per permisos individuals ben configurats
- Persistència:
  - editar i guardar inputs de `M1` només actualitza el codi runtime corresponent
  - `shared` continua funcionant exactament igual
- Presentació:
  - admin de tokens mostra el target de membre a la taula i a la impressió de QRs

## Assumptions i defaults
- El targeting de membre es fa per slot (`M1`, `M2`, ...) i no per identitat real de persona.
- Un permís individual pot apuntar a `un`, `varis` o `tots`.
- Els permisos antics de tipus `member` sense target explícit passen a significar `tots`.
- No es fan migracions ni canvis de models SQL; tot es resol dins del JSON `permissions`.
- No es modifica el motor de scoring, només la capa de permisos QR, resolució runtime i render del portal.

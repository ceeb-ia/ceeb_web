

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


Per implementar:


# Pla per cobrir `derived` per membre i `derived` per pool d’equip amb UX explícita

## Resum
Afegiré un segon eix de configuració per a `tipus=equips + team_mode=derived_from_individual`: **on es fa la selecció d’exercicis**. La classificació podrà funcionar en dos modes explícits:
- `per_member`: cada membre selecciona els seus exercicis i després l’equip suma els subtotals
- `team_pool`: l’equip construeix un pool comú d’exercicis i selecciona els `N` millors globals, amb `max_per_participant` aplicat de debò

Això només s’exposarà a `derived_from_individual`. `native_team` manté el comportament actual a nivell d’equip i no mostrarà aquest control. Les configuracions existents de `derived` conservaran per defecte la semàntica actual (`per_member`). També s’aplicarà el mateix model als desempats.

## Canvis de contracte i comportament
- Afegiré `puntuacio.exercise_selection_scope` amb valors:
  - `per_member`
  - `team_pool`
- Afegiré `desempat[i].exercise_selection_scope` amb valors:
  - `hereta`
  - `per_member`
  - `team_pool`
- Aquest camp només serà vàlid quan la classificació sigui `tipus=equips + team_mode=derived_from_individual`.
- En `derived` sense camp explícit, el backend normalitzarà i interpretar à `per_member` per compatibilitat.
- En `native_team` i `individual`, el camp no es mostrarà a la UI i el backend el rebutjarà si arriba amb un valor incompatible.
- `mode_seleccio_exercicis` es manté, però el seu significat quedarà subordinat al nou eix:
  - `exercise_selection_scope=per_member`: la selecció es fa dins de cada membre
  - `exercise_selection_scope=team_pool`: la selecció es fa sobre un pool agregat de l’equip
- `max_per_participant` només tindrà sentit funcional en `team_pool`; en `per_member` es considerarà irrellevant i no es mostrarà a la UI principal.

## Implementació
- **Motor**
  - Mantindré intacte el camí actual de `derived` com a `per_member`.
  - Afegiré un segon camí de càlcul per `derived + team_pool` dins [services_classificacions_2.py](/c:/Users/Guillem%20Merino/Desktop/ceeb_web/competicions_trampoli/services/services_classificacions_2.py):
    - construir pool d’exercicis individuals per equip i aparell
    - cada fila conservarà `inscripcio_id`, `app_id`, `exercici`, `value`
    - aplicar la mateixa maquinària de selecció (`tots`, `millor_n`, `pitjor_n`, `index`, `llista`, `global_pool`, `per_aparell_override`) però amb el pool d’equip com a base
    - aplicar `max_per_participant` com a límit real per membre dins del pool
    - calcular `team_by_app` directament des de les files seleccionades del pool, sense sumar subtotals per membre
  - Els desempats en `derived` heretaran el mateix eix:
    - `per_member`: es manté lògica actual
    - `team_pool`: el criteri opera sobre el pool d’equip amb les mateixes regles d’exercicis i agregació
  - `native_team` no canvia semànticament.

- **Validació i normalització**
  - A [views_classificacions.py](/c:/Users/Guillem%20Merino/Desktop/ceeb_web/competicions_trampoli/views_classificacions.py) validaré:
    - `puntuacio.exercise_selection_scope` en `{per_member, team_pool}`
    - `desempat[i].exercise_selection_scope` en `{hereta, per_member, team_pool}`
    - ús només permès a `tipus=equips + team_mode=derived_from_individual`
  - En `save`, les configs `derived` existents sense camp nou es persistiran amb `per_member`.
  - Els desempats `derived` sense override nou seguiran heretant `puntuacio.exercise_selection_scope`.
  - No hi haurà inferència automàtica cap a `team_pool`.

- **Builder i UX**
  - A [classificacions_builder_v2.html](/c:/Users/Guillem%20Merino/Desktop/ceeb_web/competicions_trampoli/templates/competicio/classificacions_builder_v2.html) afegiré un control nou dins del bloc **Puntuació**, just abans de la secció de selecció d’exercicis:
    - etiqueta: `Base de selecció`
    - opcions:
      - `Per membre i després suma`
      - `Pool d’equip amb límit per membre`
  - Només serà visible si `tipus=equips` i `team_mode=derived_from_individual`.
  - Canviaré els textos i hints de forma dinàmica:
    - `per_member`: “Millors N per membre”, “després se sumen els subtotals dels membres”
    - `team_pool`: “Millors N de l’equip”, “màxim per membre dins del pool”
  - `Max N per participant` quedarà ocult en `per_member` i visible en `team_pool`.
  - Afegiré un resum textual sempre visible sota la configuració:
    - exemple `TR: millors 2 per membre; després suma`
    - exemple `TR: millors 3 de l’equip; màxim 2 per membre`
  - El mateix eix apareixerà al builder de desempats amb `Hereta / Per membre / Pool d’equip`.
  - No exposaré aquest selector a `native_team`; allà la UI continuarà parlant sempre en termes d’equip.

## Proves
- `derived + per_member` manté exactament el comportament actual per score principal.
- `derived + team_pool` selecciona els `N` millors de l’equip en un aparell aplicant `max_per_participant`.
- `derived + team_pool + global_pool` selecciona els `N` millors globals del conjunt d’aparells de l’equip amb topall per membre.
- `per_aparell_override` funciona en tots dos scopes.
- Els desempats en `derived` hereten el scope del score si no tenen override.
- Els desempats en `derived + team_pool` calculen sobre pool d’equip i no sobre subtotals per membre.
- Les classificacions existents de `derived` sense camp nou es normalitzen a `per_member`.
- `native_team` rebutja `exercise_selection_scope` explícit i manté el comportament actual.
- La UI mostra/oculta correctament `Base de selecció` i `Max N per participant` segons el mode.
- Els resums textuals de la UI reflecteixen el comportament real del motor.

## Assumptions i defaults
- El nom intern del camp nou serà `exercise_selection_scope`.
- El valor per defecte i de compatibilitat per `derived` serà `per_member`.
- `team_pool` només s’introduirà a `derived_from_individual`; `native_team` no guanya cap bifurcació nova.
- No faré canvis al live en aquest paquet.
- No hi haurà migracions de model; el canvi és només de schema JSON, validació, motor i builder.





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




PLAN 4 :Revision



# Pla d’unificació de `Context d'equips` i partició per naixement en classificacions

## Resum
- Moure `Context d'equips` i `Mode d'equips` a **Metadades**.
- Deixar d’usar `equips.particio_edat` com a mecanisme actiu i substituir-lo per una única partició `any_naixement_forquilla`.
- Fer que `any_naixement_forquilla` sigui vàlida tant per `tipus=individual` com per `tipus=equips`.
- En equips, la forquilla es resol a nivell d’equip amb la **data de naixement del membre més gran** i una regla de compliment configurable.
- Mantenir les **particions manuals d’equip** com a bloc especial en aquesta iteració.

## Canvis de contracte
- `schema.particions_config.any_naixement_forquilla` passa a admetre també configuració d’equip:
  ```json
  {
    "ranges": [],
    "sense_data_label": "Sense data",
    "fora_rang_label": "Fora de forquilla",
    "team_rules": {
      "reference_mode": "oldest_member_birthdate",
      "compliance_mode": "strict",
      "max_members_outside_range": 0,
      "missing_birthdate_policy": "outside_range"
    }
  }
  ```
- Semàntica:
  - `reference_mode` queda fixat a `oldest_member_birthdate` en aquesta iteració.
  - `compliance_mode`:
    - `strict`: cap membre pot quedar fora de la forquilla candidata.
    - `allow_outside_n`: es permeten fins a `max_members_outside_range` membres fora.
  - `missing_birthdate_policy=outside_range`: membres sense `data_naixement` compten com a fora de forquilla.
- `equips.particio_edat` deixa de ser configuració nova admesa.
- `equips.combinar_manual_i_edat` es manté només per compatibilitat transitòria si cal preservar hidrata/lectura legacy; el builder nou ja no l’ha de presentar com a configuració principal.

## Implementació
- **Motor i càlcul**
  - Fer que `any_naixement_forquilla` es pugui resoldre a nivell d’equip en `derived_from_individual` i `native_team`.
  - En equips, calcular primer la forquilla candidata a partir de la data més antiga dels integrants.
  - Si no hi ha cap data vàlida coneguda, l’equip entra a `sense_data_label`.
  - Avaluar compliment:
    - `strict`: `outside_count` ha de ser `0`.
    - `allow_outside_n`: `outside_count <= max_members_outside_range`.
  - Si l’equip no compleix, entra a `fora_rang_label`; no s’exclou ni es bloqueja.
  - Per `native_team`, resoldre integrants des de `team_subject.member_ids` de manera deduplicada.
  - Mantenir les particions manuals d’equip com ara; la nova partició per naixement conviu amb elles sense redissenyar-les en `particions_v2`.

- **Validació i compatibilitat**
  - Fer vàlid `BIRTH_YEAR_RANGE_PARTITION_CODE` també per `tipus=equips`.
  - Validar `team_rules`:
    - `reference_mode` només pot ser `oldest_member_birthdate`.
    - `compliance_mode` només `strict` o `allow_outside_n`.
    - `max_members_outside_range` obligatori i `>= 0` quan el mode és `allow_outside_n`.
    - `missing_birthdate_policy` només `outside_range`.
  - Actualitzar també la validació de plantilles globals perquè accepti equips.
  - Tractar `equips.particio_edat` com a legacy de lectura:
    - si existeix i no hi ha `team_rules` nous, el builder la mostra com a configuració legacy inferida.
    - en desar, sempre persistir només el contracte nou a `particions_config.any_naixement_forquilla`.
  - La conversió legacy ha de derivar forquilles de naixement equivalents a partir de `llindars` i la data de la competició; si no es pot resoldre una data de referència vàlida, marcar la configuració com a legacy pendent de revisió en lloc de reinterpretar-la silenciosament.

- **Builder i UX**
  - Moure `Context d'equips` i `Mode d'equips` al bloc **Metadades**, al costat de `Tipus`.
  - Deixar a **Particions**:
    - particions generals
    - particions manuals d’equip
    - configuració de `any_naixement_forquilla`
  - Reutilitzar el mateix editor de forquilles que ja existeix a inscripcions/classificacions.
  - Si `tipus=individual`, mostrar només:
    - rangs
    - `sense_data_label`
    - `fora_rang_label`
  - Si `tipus=equips`, afegir al mateix bloc:
    - “Regla d’equip” amb text clar que la forquilla es calcula pel membre més gran
    - selector `strict` / `allow_outside_n`
    - input `N` quan toca
    - nota que els membres sense data compten com a fora de forquilla
  - Eliminar del builder el bloc antic de “Partició per edat màxima d’equip”.

## Proves
- Accepta `any_naixement_forquilla` en `tipus=equips` a validació i a plantilles.
- `tipus=individual` continua agrupant exactament com ara.
- `tipus=equips + derived_from_individual`:
  - resol forquilla per equip amb el membre més gran
  - `strict` envia equips no conformes a `fora_rang_label`
  - `allow_outside_n` admet fins a `N` membres fora
  - membres sense data compten com a fora
- `tipus=equips + native_team` replica la mateixa semàntica.
- Equips sense cap data vàlida coneguda entren a `sense_data_label`.
- El builder mostra `Context d'equips` a Metadades i ja no mostra `equips.particio_edat`.
- Configs legacy amb `equips.particio_edat` es detecten, s’hidraten per revisió i es normalitzen al contracte nou en desar.

## Assumptions i defaults
- La nova partició de naixement s’aplica a **totes** les classificacions d’equips, inclòs `native_team`.
- L’equip que incompleix la regla va a `Fora de forquilla`; no s’exclou.
- `missing_birthdate_policy` queda fixat a `outside_range` en aquesta iteració.
- `reference_mode` queda fixat a la data del membre més gran; no s’obre encara a altres estratègies.
- Les particions manuals d’equip es mantenen especials en aquesta fase; no es passen encara a `particions_v2`.

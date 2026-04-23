# Pla D'Implementacio De Presencia De Jutges A `puntuacio`

## Objectiu
- Evitar que un jutge absent quedi materialitzat com si hagués puntuat `0`.
- Fer que la seleccio i agregacio de notes de jutges operin nomes sobre les notes realment introduides.
- Mantenir `0` com a valor valid i diferent de "sense dada".
- Fer que el canvi sigui robust davant:
  - guardat parcial des del portal del jutge
  - recalculs generals d'esquema
  - canvis de panell de jutges entre categories/nivells
- Deixar un pla executable per a un agent extern sense context oral previ.

## Resum Executiu
- El problema actual no es nomes de UI.
- El problema real es de model de dades:
  - el sistema desa `entry.inputs` despres de la normalitzacio de l'engine
  - aquesta normalitzacio expandeix la mida dels camps de jutges i omple absencies amb `0`
- Consequencia:
  - el sistema deixa de distingir entre `0 real` i `jutge absent`
  - `select_sum`, `eliminar_extrems`, `row_custom_compute`, `exec_by_judge` i derivats poden incloure jutges absents com si fossin notes reals
  - el portal del jutge tambe pot marcar un exercici com "guardat" quan nomes hi ha zeros fabricats

La estrategia correcta d'aquesta iteracio es:
- no fer migracio de model
- no afegir camps de base de dades nous
- guardar presencia de jutges dins d'`inputs` amb claus reservades
- mantenir `entry.inputs` com a font canonica `presence-aware`
- usar una projeccio temporal per al calcul
- impedir que l'engine torni a persistir la versio densificada amb zeros fantasma

## Abast
- Inclou:
  - `judge_save_partial`
  - `scoring_save`
  - `scoring_save_partial`
  - recalcul general de puntuacions en canvi d'esquema
  - `ScoringEngine` en tots els helpers que fan seleccio/agregacio de jutges
  - portal del jutge (`judge_portal` i `judge_updates`)
  - detail payload quan es projecten valors per jutges
  - tests
- Inclou camps amb shape:
  - `list` + `shape=judge`
  - `matrix` + `shape=judge_x_item`
  - `matrix` + `shape=judge_x_element`
- Inclou context individual i team si el runtime fa servir camps de jutge.
- No inclou:
  - neteja de dades historiques
  - redisseny global del model `ScoreEntry`
  - nova taula auxiliar
  - canvi de semantica de "guardat parcial de cel.les" fora del necessari per mantenir compatibilitat

## Diagnosi Del Comportament Actual

### Punt exacte del problema
- `views/judge/permissions.py`
  - el patch parcial conserva `None` localment per a posicions no informades
- `scoring_engine.py`
  - `validate_and_normalize_inputs` expandeix arrays/matrius a mida fixa i omple absencies amb `0`
- `views/judge/save.py`
  - desa `result.inputs` a `entry.inputs`
- `views/scoring/schema.py`
  - en recalc, torna a passar per l'engine i torna a persistir la versio densificada
- `templates/judge/portal.html`
  - dedueix "guardat" a partir de qualsevol valor existent dins `inputs`

### Efecte funcional incorrecte
Cas:
- schema amb `judges.count = 3`
- categoria A usa nomes J1 i J2
- J3 no puntua

Avui pot acabar passant:
- `entry.inputs["E"] == [[...J1...], [...J2...], [0, 0, 0, ...]]`
- el sistema interpreta J3 com a present
- `eliminar_extrems` i altres criteris operen sobre `[nota_J1, nota_J2, 0]`

### Requisit semantic que cal preservar
- `0` real ha de comptar
- absencia no ha de comptar
- un jutge absent no s'ha de convertir en `0` ni en persistencia ni en calcul temporal de seleccio

## Decisions Tancades
- No es fara migracio de model.
- No s'afegiran camps nous a `ScoreEntry` ni `TeamScoreEntry`.
- La presencia es guardara dins d'`inputs` amb claus reservades:
  - `__presence__<field_code>`
- `entry.inputs` deixara de ser la sortida normalitzada completa de l'engine.
- `entry.inputs` passara a ser la representacio canonica `presence-aware`.
- L'engine rebra una projeccio temporal derivada d'aquesta representacio canonica.
- La persistencia canonica mantindra la posicio del jutge:
  - amb `null` per jutges absents
  - amb `null` per cel.les no informades dins d'un jutge present, si aplica
- La seleccio/agregacio de jutges ha d'ignorar valors absents.
- El portal del jutge ha de decidir "guardat" a partir de presencia real, no a partir de zeros fabricats.
- El canvi ha de ser forward-only:
  - no cal corregir files antigues
  - pero els paths nous no han de reintroduir el problema

## No Objectius
- No resoldre ara la semantica de "un jutge present amb la fila a mitges" mes enlla del comportament necessari per no comptar absencies.
- No redissenyar la UX del portal.
- No canviar `candidate_source`, `selection_runtime` ni el motor de classificacions fora del necessari per respectar els valors correctes provinents de puntuacio.
- No substituir el `ScoringEngine`.

## Contracte De Dades Proposat

### Clau reservada de presencia
Per qualsevol camp `code = "E"` amb shape de jutges:
- la clau reservada sera `__presence__E`

### Shape canonic per camps `list` amb `shape=judge`
```json
{
  "J": [9.1, null, 8.7],
  "__presence__J": [true, false, true]
}
```

### Shape canonic per camps `matrix` amb `shape=judge_x_item` o `judge_x_element`
```json
{
  "E": [
    [0.1, null, 0.2, 0.0],
    [0.0, 0.1, 0.2, 0.1],
    null
  ],
  "__crash__E": [0, 0, null],
  "__presence__E": [true, true, false]
}
```

### Regles semantiques del shape canonic
- La posicio `i` correspon al jutge `i + 1`.
- `__presence__E[i] == true` vol dir:
  - aquest jutge ha introduit alguna dada valida per aquest camp
  - `0` es nota real si existeix a la seva posicio
- `__presence__E[i] == false` vol dir:
  - el jutge no ha de participar en la seleccio ni en l'agregacio d'aquest camp
- Si un jutge es absent:
  - `list/judge`: el valor ha de ser `null`
  - `matrix/judge_x_*`: la fila ha de ser `null`
  - `__crash__E[i]` ha de ser `null` o absent
- Si un jutge es present pero una cel.la concreta no ha estat omplerta:
  - la cel.la pot quedar a `null` en la representacio canonica
  - en calcul temporal pot passar a `0` dins de la logica de fila del jutge
  - aquesta iteracio no canvia la semantica actual de "cel.la buida dins d'un jutge present"

### Regla per `crash`
- Guardar `__crash__E` tambe ha de marcar presencia del jutge per al camp `E`.
- Un jutge pot quedar present per haver informat `crash` encara que no hagi omplert totes les cel.les de la fila.

### Fallback de compatibilitat
Si un entry no te `__presence__<field_code>`:
- no s'ha d'assumir que tothom es absent
- la presencia s'ha d'inferir de la representacio crua:
  - `list/judge`: valor no `null` a la posicio implica present
  - `matrix/judge_x_*`: fila no `null` implica present
  - `__crash__<field_code>` no `null` tambe implica present

Aixo serveix per:
- compatibilitat amb dades antigues
- compatibilitat amb paths no-QR que encara no escriguin la clau de presencia el primer dia

## Principi Arquitectonic

### Font de veritat
- `entry.inputs` canonic i `presence-aware`

### Projeccio temporal de calcul
- `runtime_inputs` derivat d'`entry.inputs`
- s'envia al `ScoringEngine`
- no es persisteix com a font de veritat

### Regla critica
- no desar mai `result.inputs` directament com a canonic si aquest resultat ja ha densificat absencies

## Estrategia D'Implementacio

## Fase 0. Contracte Tancat

### Objectiu
- Fixar el contracte de dades abans de tocar save paths, engine i UI.

### Resultat esperat
- Aquest document es considera la font de veritat de la iteracio.

### Done
- Claus reservades acceptades:
  - `__presence__<field_code>`
- Shape canonic acceptat:
  - llistes de mida fixa amb `null` a les posicions absents

## Fase 1. Helpers Reutilitzables De Presencia

### Objectiu
- Centralitzar la logica de presencia per evitar duplicacio i derives semantiques.

### Modul nou recomanat
- `competicions_trampoli/services/scoring/judge_presence.py`

### Responsabilitats del modul
- construir `presence_key(field_code)`
- detectar si un field es judge-shaped a partir del schema/runtime schema
- inferir presencia d'un field a partir del valor cru
- materialitzar una estructura canonica per a un field judge-shaped
- aplicar un patch parcial per jutge sense densificar zeros
- construir `runtime_inputs` per a calcul a partir d'`inputs` canonics
- oferir helpers per:
  - `present judges`
  - `row absent`
  - `scalar absent`

### API minima recomanada
- `presence_key(code) -> str`
- `is_judge_shaped_field(field_cfg) -> bool`
- `infer_presence_for_field(raw_field_value, raw_crash_value, n_judges) -> list[bool]`
- `merge_judge_patch_into_canonical(current_inputs, sanitized_patch, schema) -> dict`
- `build_runtime_inputs_from_canonical(canonical_inputs, schema) -> dict`
- `canonical_has_saved_presence(canonical_inputs, field_code) -> bool`

### Notes
- Si aquest modul nou no encaixa amb l'estructura actual, es pot repartir entre `views/judge/permissions.py` i `views/scoring/helpers.py`, pero es prefereix un modul dedicat.

## Fase 2. Save Paths I Persistencia Canonica

### Objectiu
- Fer que els paths de guardat deixin d'escriure `inputs` densificats.

### Fitxers afectats
- `competicions_trampoli/views/judge/save.py`
- `competicions_trampoli/views/scoring/save.py`
- `competicions_trampoli/views/judge/permissions.py`
- possiblement `competicions_trampoli/views/scoring/helpers.py`

### Canvi de responsabilitat
- `judge_save_partial`:
  - avui persisteix `result.inputs`
  - nou comportament:
    - fer merge del patch dins d'un `canonical_inputs`
    - generar `runtime_inputs` des de `canonical_inputs`
    - calcular `outputs` i `total`
    - persistir `canonical_inputs`, no `result.inputs`

- `scoring_save` i `scoring_save_partial`:
  - per coherencia forward-only, tambe han de poder persistir judge-shaped fields en format canonic
  - si reben payload complet d'un camp judge-shaped:
    - qualsevol jutge explicitament informat es considera present
    - qualsevol jutge absent o `null` queda absent

### Canvis concrets a `views/judge/permissions.py`
- substituir o encapsular `_apply_sanitized_patch`
- quan un jutge escriu sobre un field judge-shaped:
  - cal conservar posicions per index de jutge
  - cal marcar `__presence__<field_code>[judge_index - 1] = true`
  - no omplir la resta de jutges amb `0`
- el resultat canonic ha de ser:
  - `null` per jutges absents
  - llista parcial amb `null` per cel.les no informades si el jutge es present

### Casos especials que s'han de cobrir
- patch de `__crash__E` sense patch de `E`
- jutge present amb nota `0`
- jutge 3 present si J2 es absent:
  - la posicio 2 s'ha de conservar amb `null`

## Fase 3. Engine `presence-aware`

### Objectiu
- Fer que el calcul tracti els jutges absents com a absents, no com a zeros.

### Fitxer principal
- `competicions_trampoli/scoring_engine.py`

### Punt de disseny
- `validate_and_normalize_inputs` ja no pot convertir absencies de jutges a `0`.
- Ha de mantenir missingness en la projeccio temporal.

### Com ha de quedar la normalitzacio

#### `list` + `shape=judge`
- jutge present:
  - valor numeric clampat
  - `0` valid
- jutge absent:
  - `None`

#### `matrix` + `shape=judge_x_*`
- jutge present:
  - fila `list`
  - les cel.les `None` dins la fila es poden tractar com `0` nomes en la logica de calcul d'aquella fila
- jutge absent:
  - fila `None`

#### `__crash__<field>`
- jutge present:
  - enter valid o `0`
- jutge absent:
  - `None`

### Helpers que s'han de revisar
- `to_float`
- `select_exec_notes`
- `select_sum`
- `_agg`
- `_select_idx`
- `exec_by_judge`
- `row_custom_compute`
- `column_custom_compute`
- qualsevol helper que agregui vectors de jutges

### Regles semantiques de calcul

#### Regla 1. Seleccio de jutges
- jutges absents no entren al conjunt candidat

#### Regla 2. Agregacio de jutges
- jutges absents no entren a `sum`, `avg`, `max`, `min`, `median`, `eliminar_extrems`, etc.

#### Regla 3. Jutge present amb valor `0`
- compta com a valor valid

#### Regla 4. Jutge present amb fila parcial
- segueix comptant com a present
- les cel.les `null` de la seva fila es poden tractar com a `0` per compatibilitat amb el comportament actual de "save while typing"

#### Regla 5. Resultat buit
- si despres de filtrar absencies no queda cap valor seleccionable:
  - mantenir el comportament actual de retorn `0.0`
  - no llençar error nou en aquesta iteracio

### Canvi explicit a `exec_by_judge`
- si una fila de jutge es absent:
  - el vector resultant ha de contenir `None` per aquella posicio
  - no `0.0`

### Canvi explicit a `row_custom_compute`
- abans d'iterar la fila, detectar si el jutge es absent
- si es absent:
  - `by_judge.append(None)`
  - `by_judge_has_data.append(False)`
- la seleccio final sobre jutges ha d'ignorar aquests `None`

## Fase 4. Recalc D'Esquema

### Objectiu
- garantir que un recalc no reintrodueixi zeros fantasma.

### Fitxer principal
- `competicions_trampoli/views/scoring/schema.py`

### Regla
- el recalc ha de partir de `entry.inputs` canonics
- ha de construir `runtime_inputs`
- ha de persistir de nou els mateixos `canonical_inputs` o una versio canonitzada equivalent
- no ha de persistir `result.inputs`

### Punt critic
- avui `_split_inputs_by_allowed_codes` tracta claus desconegudes com `orphans`
- cal decidir que:
  - les claus `__presence__<field_code>` son metadades de camps coneguts
  - no s'han de perdre ni separar com si fossin soroll

### Implementacio recomanada
- ampliar la definicio de "known inputs" per incloure:
  - `field_code`
  - `__crash__field_code`
  - `__presence__field_code`

## Fase 5. Portal Del Jutge I Feed Incremental

### Objectiu
- que la UI del jutge mostri "guardat" nomes si hi ha presencia real.

### Fitxers afectats
- `competicions_trampoli/views/judge/portal.py`
- `competicions_trampoli/views/judge/updates.py`
- `competicions_trampoli/templates/judge/portal.html`

### Canvi necessari al payload
- el portal no s'ha de basar nomes en `inputs[field_code]`
- ha de rebre la presencia per camp d'una forma usable

### Opcio recomanada
- continuar retornant `inputs`
- afegir a cada exercici un petit bloc derivat:
```json
{
  "inputs": { "...": "..." },
  "presence": {
    "E": [true, false, true]
  }
}
```

### Alternativa acceptable
- incloure `__presence__<field_code>` dins `inputs`
- i fer que la UI els llegeixi explicitament

La primera opcio es preferible per no barrejar valors d'edicio amb metadades de transport al JS.

### Regla UI
- `hasSavedScoreForEntry` ha de mirar presencia real dels camps permesos
- no ha de fer servir `hasAnySavedValue(inputs[code])`

### `judge_updates`
- ha d'enviar la mateixa semantica que `judge_portal`
- si el feed incremental no inclou presencia, el portal tornara a pintar estats equivocats despres d'un poll

## Fase 6. Detail Payload I Lectures De Valors Per Jutge

### Objectiu
- evitar que el detall projecti jutges absents com si tinguessin files de zeros.

### Fitxer principal
- `competicions_trampoli/services/classificacions/engine/detail_payload.py`

### Problema actual
- `_apply_judge_selection` agafa totes les posicions disponibles del `raw_value`
- si una fila absent queda representada a la posicio amb `null`, avui s'acaba projectant igual

### Regla nova
- si el valor seleccionat d'un jutge es `None`:
  - no s'ha d'afegir a `picked`

### Consequencia
- el detall per jutges ha de mostrar nomes jutges presents

## Fase 7. Tests

### Objectiu
- blindar la regressio principal:
  - `0 real` vs `jutge absent`

### Tests nous o ampliats

#### 1. Save parcial del jutge
Fitxer recomanat:
- `competicions_trampoli/tests/scoring/judge/test_exclusions_and_partial_save.py`

Casos:
- schema amb 3 jutges, save nomes per J1
- `entry.inputs["E"]` ha de preservar:
  - fila J1 amb dades
  - J2 i J3 a `null`
  - `__presence__E == [true, false, false]`
- save posterior per J3:
  - `__presence__E == [true, false, true]`
  - J2 continua absent

#### 2. `0` valid
Cas:
- J1 entra `0`
- `__presence__E[0] == true`
- seleccio/agregacio el compta com a valor valid

#### 3. `eliminar_extrems` ignora jutge absent
Fitxer recomanat:
- nou fitxer `competicions_trampoli/tests/scoring/test_engine_judge_presence.py`

Cas:
- tres jutges configurats
- notes efectives: `9.1`, `8.7`, absent
- la seleccio `eliminar_extrems` ha d'operar sobre 2 valors, no sobre 3

#### 4. `exec_by_judge` ignora absents
Cas:
- matriu amb fila 3 absent
- el vector retornat ha de portar `None` a J3
- `select_sum` posterior no l'ha de convertir en candidat `0`

#### 5. Portal del jutge
Fitxer recomanat:
- mateix fitxer de tests de jutge o nou test especific

Cas:
- J1 ha guardat
- J2 i J3 absents
- l'exercici s'ha de marcar "guardat" nomes pel jutge actiu que consulta el seu camp
- una entrada absent no pot aparèixer com a completa per zeros fabricats

#### 6. Recalc d'esquema
Fitxer recomanat:
- test nou o ampliacio a tests de scoring/schema

Cas:
- persistir `inputs` canonics amb `__presence__`
- executar recalc
- verificar que les absencies continuen sent absencies

#### 7. Team context
Fitxer recomanat:
- `competicions_trampoli/tests/scoring/team/test_scoring_and_judge_permissions.py`

Cas:
- un camp team runtime amb permisos per jutge
- la presencia no ha de interferir amb la logica de `member_slot`

## Fitxers A Tocar

### Save / persistencia
- `competicions_trampoli/views/judge/save.py`
- `competicions_trampoli/views/judge/permissions.py`
- `competicions_trampoli/views/scoring/save.py`
- `competicions_trampoli/views/scoring/schema.py`
- `competicions_trampoli/views/scoring/helpers.py`

### Engine
- `competicions_trampoli/scoring_engine.py`

### Portal / feed
- `competicions_trampoli/views/judge/portal.py`
- `competicions_trampoli/views/judge/updates.py`
- `competicions_trampoli/templates/judge/portal.html`

### Detail / lectura
- `competicions_trampoli/services/classificacions/engine/detail_payload.py`

### Helper nou recomanat
- `competicions_trampoli/services/scoring/judge_presence.py`

### Tests
- `competicions_trampoli/tests/scoring/judge/test_exclusions_and_partial_save.py`
- `competicions_trampoli/tests/scoring/team/test_scoring_and_judge_permissions.py`
- `competicions_trampoli/tests/scoring/test_engine_score_values.py`
- nou:
  - `competicions_trampoli/tests/scoring/test_engine_judge_presence.py`

## Ordre Recomanat D'Execucio
1. Tancar helpers de presencia i el contracte canonic.
2. Canviar `judge_save_partial` per persistir `canonical_inputs`.
3. Canviar `scoring_save` i `scoring_save_partial`.
4. Fer `ScoringEngine` `presence-aware`.
5. Arreglar recalc d'esquema.
6. Arreglar `judge_portal` i `judge_updates`.
7. Arreglar `detail_payload`.
8. Escriure i passar tests.

## Riscos I Trampes

### Risc 1. Perdre `__presence__*` en recalc
- Si les claus de presencia es tracten com `orphans` i despres es perden en algun merge, el problema reapareix.

### Risc 2. Tornar a desar `result.inputs`
- Si algun path continua fent `entry.inputs = result.inputs`, el canvi queda mig trencat.

### Risc 3. Tractar `None` com `0` massa aviat
- Si `_select_idx` o `select_sum` passen per `to_float(None)` abans de filtrar, l'absencia tornara a entrar com a zero.

### Risc 4. Trencar detall de jutges
- Si `detail_payload` no filtra `None`, es mostraran jutges buits al detall.

### Risc 5. Trencar paths team
- Les claus reservades no poden col.lisionar amb codis runtime `__mN`.

## Criteris D'Acceptacio
- Guardar la nota d'un jutge no crea notes `0` ficticies per als jutges absents.
- `eliminar_extrems` i qualsevol altra seleccio de jutges ignoren absencies.
- Un `0` introduit per un jutge present continua comptant.
- Un recalc general no reintroduix zeros fantasma.
- El portal no marca com a "guardat" una entrada que nomes te absencies densificades.
- Els tests nous passen i no hi ha regressions als tests existents de puntuacio/jutges.

## Nota Final Per A L'Agent Implementador
- No intentis arreglar historic.
- No facis migracio de base de dades.
- No facis una solucio basada en "si la fila es tot zeros, assumeix absent".
- La semantica valida es exclusivament:
  - `presence = true` -> el jutge compta
  - `presence = false` -> el jutge no compta
  - `0` amb `presence = true` es nota real

Si has de triar entre tocar menys fitxers o mantenir aquesta semantica, prioritza la semantica.

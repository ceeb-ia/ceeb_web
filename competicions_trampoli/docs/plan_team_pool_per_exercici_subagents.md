# Pla D'Implementacio De `team_pool` Amb Pretractament Per Exercici Entre Membres Per Subagents

## Objectiu
- Afegir un mode nou de `team_pool` per a classificacions `equips` amb `team_mode=derived_from_individual`.
- Permetre que, dins de cada aparell, cada numero d'exercici mantingui la seva propia bossa de contributors entre membres.
- Fer que cada bossa d'exercici pugui resoldre:
  - seleccio de membres
  - agregacio de membres
  - configuracio diferent per exercici
- Fer que, despres d'aquest pretractament, el pipeline actual continui igual:
  - seleccio entre exercicis
  - agregacio d'exercicis
  - agregacio entre aparells
- Deixar un pla executable per subagents en paral.lel i un orquestrador que nomes necessiti aquest document.

## Abast
- Inclou nomes `puntuacio`.
- Inclou nomes:
  - `tipus=equips`
  - `team_mode=derived_from_individual`
  - `exercise_selection_scope=team_pool`
- Inclou:
  - validacio de schema
  - runtime de compute
  - wiring de l'orquestrador
  - builder de configuracio
  - tests
- No inclou ara:
  - `native_team`
  - `individual`
  - `entitat`
  - redisseny general de `desempat`
  - suport per recalcular aquest mode nou des de zero dins del pipeline propi de `desempat`

## Resum Executiu
- Avui, en `derived_from_individual + team_pool`, totes les files de l'equip d'un aparell entren en una bossa plana.
- Aixo permet seleccionar els millors `N` de tota la bossa, pero no permet dir:
  - a l'exercici 1 agafa els millors 2 membres i suma
  - a l'exercici 2 agafa els millors 3 membres i suma
  - despres selecciona/agrega entre aquests subtotals d'exercici
- El canvi correcte no es "complicar `participants_per_aparell`".
- El canvi correcte es afegir un submode nou de `team_pool` que preservi bosses separades per numero d'exercici abans de la seleccio principal entre exercicis.
- Aquest mode nou ha de ser incompatible amb `candidate_source_per_aparell`, perque qualsevol preseleccio/agregacio per membre destruiria la separacio per exercici.

## Decisions Tancades
- El mode nou nomes s'activa explicitament.
- El comportament actual de `team_pool` pla continua existint com a fallback.
- El mode nou nomes es valid per:
  - `tipus=equips`
  - `team_mode=derived_from_individual`
  - `exercise_selection_scope=team_pool`
- Amb el mode nou activat, nomes es permet entrada `raw_exercise`.
- `candidate_source_per_aparell` ha de quedar invalidat com a incompatible en aquest context.
- La seleccio/agregacio entre membres dins de cada exercici pot variar per exercici.
- La seleccio/agregacio posterior entre exercicis ha de reutilitzar el contracte actual de:
  - `exercicis_per_aparell`
  - `agregacio_exercicis_per_aparell`
- Els `main_selected_contributors` han de continuar propagant contributors crus amb `exercici` preservat, no buckets ja col.lapsats.
- En una primera fase, els desempats no han de poder recalcular aquest mode nou des de zero sobre el conjunt cru original d'exercicis de l'equip.
- Si un desempat treballa amb `main_selected_contributors`, si que ha de poder operar sobre el subconjunt heretat dels contributors principals.

## No Objectius
- No substituir el `team_pool` actual.
- No tocar la semantica de `per_member`.
- No afegir una segona implementacio equivalent del nou mode dins de `pipeline_runtime.py`.
- No obrir ara suport nou per `victories`.
- No redissenyar la representacio general de contributors.

## Problema Functional

### Com funciona avui
Per un aparell d'un equip derivat:
1. es calcula el valor de cada fila base d'exercici
2. si hi ha `candidate_source_per_aparell`, es pot preagregar per membre
3. si `exercise_selection_scope=team_pool`, totes les files candidates entren en una sola bossa plana
4. es seleccionen exercicis sobre aquesta bossa
5. s'agreguen exercicis

### Com ha de funcionar amb el mode nou
Per un aparell d'un equip derivat:
1. es calcula el valor de cada fila base d'exercici
2. no es permet `candidate_source_per_aparell`
3. es creen bosses per numero d'exercici:
   - exercici 1
   - exercici 2
   - etc.
4. dins de cada bossa:
   - es seleccionen membres
   - s'agreguen membres
   - surt un subtotal d'exercici
5. els subtotals resultants entren al flux actual:
   - seleccio entre exercicis
   - agregacio d'exercicis
   - agregacio entre aparells

### Consequencia clau
- El canvi entra entre la materialitzacio de files base per exercici i la seleccio principal.
- No entra al final del pipeline.
- No s'ha de modelar com una extensio tardana de `participants_per_aparell`.

## Shape Proposada

### Camps nous a `puntuacio`
```json
{
  "team_pool_mode_per_aparell": {
    "12": "per_exercici"
  },
  "team_pool_participants_per_exercici_per_aparell": {
    "12": {
      "1": { "mode": "millor_n", "n": 2 },
      "2": { "mode": "millor_n", "n": 3 }
    }
  },
  "team_pool_agregacio_participants_per_exercici_per_aparell": {
    "12": {
      "1": "sum",
      "2": "sum"
    }
  }
}
```

### Camps existents que continuen governant la fase posterior
```json
{
  "exercicis_per_aparell": {
    "12": { "mode": "tots" }
  },
  "agregacio_exercicis_per_aparell": {
    "12": "sum"
  }
}
```

### Valors admesos
- `team_pool_mode_per_aparell[app_id]`:
  - `flat`
  - `per_exercici`

### Regles de resolucio
Per un `app_id` concret:
1. si `team_pool_mode_per_aparell[app_id] != "per_exercici"`:
   - es mante el comportament actual de `team_pool`
2. si `team_pool_mode_per_aparell[app_id] == "per_exercici"`:
   - es creen buckets per `exercici`
   - cada bucket usa:
     - `team_pool_participants_per_exercici_per_aparell[app_id][exercici]`
     - `team_pool_agregacio_participants_per_exercici_per_aparell[app_id][exercici]`
   - si falta qualsevol d'aquestes dues peces per un exercici:
     - aquell exercici ha de caure a un default explicit definit per schema

### Decisio sobre fallback
- No s'ha de deduir cap selector magic.
- El builder i la validacio han d'exigir una configuracio efectiva completa per a cada exercici quan el mode `per_exercici` estigui actiu.
- Es permet un bloc `default` intern al builder si es considera util per UX, pero el payload persistit ha d'arribar canonitzat per exercici.

## Regles D'Incompatibilitat

### Incompatibilitat principal
Si `team_pool_mode_per_aparell[app_id] == "per_exercici"`:
- `candidate_source_per_aparell[app_id]` no es valid
- qualsevol mode que preagregui o preseleccioni per membre abans de la fase de buckets s'ha de rebutjar

### Motivacio
- El pretractament per membre destrueix la separacio entre exercicis.
- El mode nou necessita rebre files crues per `(membre, aparell, exercici)`.

### Regla de validacio
- L'error ha de ser semantic, no generic.
- Missatge recomanat:
  - "El mode `team_pool` per exercici nomes admet exercicis crus. No es compatible amb preseleccio o agregacio previa per membre."

## Impacte En `desempat`

### Regla tancada
- En aquesta iteracio, `desempat` no pot recalcular aquest mode nou des de zero sobre el conjunt cru complet de l'equip.

### Si un tie usa `raw_exercises`
- continua funcionant amb el contracte existent
- pero no ha de poder declarar aquesta nova semantica `per_exercici` dins del seu pipeline propi

### Si un tie usa `main_selected_contributors`
- ha de continuar sent valid
- el tie rep contributors crus heretats del calcul principal
- aquests contributors han de conservar:
  - `app_id`
  - `exercici`
  - `participant_id`
  - `source_rows`

### Consequencia
- un tie pot seguir fent coses com:
  - ultim exercici
  - llista d'exercicis
  - index concret
- pero sempre sobre el subconjunt de contributors heretat del `main score`

### Restriccio a implementar
- validacio explicita d'incompatibilitat si un `desempat` intenta recalcular aquest mode nou de forma autonoma

## Model D'Arquitectura

### Punt d'insercio
- El canvi ha d'entrar despres de materialitzar files base d'exercici i abans de la seleccio principal.

### Ordre del runtime
1. `orchestrator.py` carrega schema i ORM
2. `orchestrator.py` materialitza files base:
   - `app_ex_rows_by_ins`
   - `team_app_ex_rows_by_equip`
3. nou pas de `team_pool` per exercici:
   - agrupa per bucket d'exercici
   - selecciona membres
   - agrega membres
   - genera subtotals d'exercici
4. `selection_runtime.py` aplica la seleccio actual entre exercicis
5. `orchestrator.py` agrega exercicis i aparells com avui

### Modul nou proposat
- `competicions_trampoli/services/classificacions/engine/team_pool_buckets.py`

### Responsabilitat del modul nou
- Rebre files crues de `derived_from_individual` per aparell i equip.
- Construir buckets per `exercici`.
- Aplicar seleccio de membres dins de cada bucket.
- Aplicar agregacio de membres dins de cada bucket.
- Retornar files derivades "subtotal d'exercici" conservant tracabilitat cap a les files crues contributors.

### Responsabilitats que no ha d'assumir
- No ha de carregar ORM.
- No ha de decidir UX.
- No ha de renderitzar detail/display.
- No ha de implementar desempats.

## Contracte De Runtime

### Input minim del modul `team_pool_buckets`
- `app_id`
- `equip_id`
- files crues del team pool d'aquell aparell
- config:
  - `team_pool_mode_per_aparell`
  - `team_pool_participants_per_exercici_per_aparell`
  - `team_pool_agregacio_participants_per_exercici_per_aparell`

### Output esperat
- una col.leccio de files derivades per exercici
- cada fila derivada ha de representar el subtotal d'un bucket d'exercici
- cada fila ha de conservar:
  - `app_id`
  - `exercici`
  - `value`
  - `by_camp`
  - `source_rows`
  - identificacio suficient per continuar entrant al flux de seleccio d'exercicis existent

### Regla de contributors
- `source_rows` ha de conservar files crues contributors.
- No s'han de substituir per buckets col.lapsats a efectes de tracabilitat.

## UX Objectiu

### Visibilitat
El builder ha de mostrar aquest mode nomes quan:
- `tipus=equips`
- `team_mode=derived_from_individual`
- `exercise_selection_scope=team_pool`

### Controls nous
Dins de cada aparell:
- selector:
  - `Bossa plana`
  - `Bosses per exercici`

Si el mode es `Bosses per exercici`:
- es mostren blocs per numero d'exercici
- cada bloc te:
  - selector de membres del bucket
  - agregador de membres del bucket

### Controls que s'han de bloquejar
- qualsevol pretractament per membre incompatible amb aquest mode

### Copy recomanada
- `Bossa plana`
  - "Totes les aportacions de l'equip entren juntes."
- `Bosses per exercici`
  - "Cada numero d'exercici mante la seva bossa de membres abans de combinar els resultats entre exercicis."

## Orquestracio Recomanada

## Fase 0. Contracte Congelat

### Objectiu
- Fixar noms de claus, semantica i incompatibilitats abans d'obrir fronts paral.lels.

### Owner
- Integrador principal

### Write set
- aquest document

### Done
- Noms finals acceptats:
  - `team_pool_mode_per_aparell`
  - `team_pool_participants_per_exercici_per_aparell`
  - `team_pool_agregacio_participants_per_exercici_per_aparell`
- Incompatibilitat tancada:
  - `candidate_source_per_aparell` invalid quan `team_pool_mode_per_aparell=per_exercici`

## Fase 1. Schema, Validacio I Canonitzacio

### Objectiu
- Fer que el backend entengui i validi el nou shape.

### Subagent S1.A - Validacio de schema
#### Write set
- `competicions_trampoli/services/classificacions/validation.py`

#### Tasques
- Afegir validacio de les claus noves.
- Restringir-les al context:
  - `tipus=equips`
  - `team_mode=derived_from_individual`
  - `exercise_selection_scope=team_pool`
- Rebutjar `candidate_source_per_aparell` en aquest mode.
- Rebutjar configuracions parcials o incoherents per exercici.
- Rebutjar qualsevol intent de modelar aquest mode dins de `desempat`.

#### Restriccions
- No tocar runtime de compute.
- No introduir comportament implicit no documentat.

### Subagent S1.B - Tests de validacio
#### Write set
- `competicions_trampoli/tests/classificacions/test_engine_schema.py`

#### Tasques
- Afegir casos verds del shape nou.
- Afegir casos vermells:
  - fora de context
  - amb `candidate_source_per_aparell`
  - amb config incompleta per exercici
  - amb intents dins de `desempat`

#### Restriccions
- No tocar codi productiu.

## Fase 2. Runtime De Buckets Per Exercici

### Objectiu
- Implementar el preprocessat nou sense barrejar-lo amb la seleccio general.

### Subagent S2.A - Modul nou
#### Write set
- `competicions_trampoli/services/classificacions/engine/team_pool_buckets.py`

#### Tasques
- Crear el modul nou.
- Implementar:
  - agrupacio per `exercici`
  - seleccio de membres per bucket
  - agregacio de membres per bucket
  - preservacio de `source_rows`
- Reutilitzar les primitives existents de `selection.py` quan sigui possible.

#### Restriccions
- No tocar `selection_runtime.py`.
- No tocar `orchestrator.py`.
- No llegir ORM directament.

### Subagent S2.B - Tests unitaris del modul nou
#### Write set
- `competicions_trampoli/tests/scoring/test_engine_team_pool_buckets.py`

#### Tasques
- Cobrir:
  - dos exercicis amb selectors diferents
  - agregadors diferents per exercici
  - propagacio correcta de `source_rows`
  - ordre estable dels buckets
  - comportament buit o parcial

#### Restriccions
- No tocar runtime productiu.

## Fase 3. Integracio Amb El Runtime Principal

### Dependencia
- No comencar fins que S2.A estigui tancat o com a minim amb contracte estable.

### Objectiu
- Inserir el preprocessat nou al punt correcte del flux.

### Subagent S3.A - Wiring runtime
#### Write set
- `competicions_trampoli/services/classificacions/engine/selection_runtime.py`
- `competicions_trampoli/services/classificacions/engine/orchestrator.py`

#### Tasques
- Detectar el mode nou en el cami:
  - `equips`
  - `derived_from_individual`
  - `exercise_selection_scope=team_pool`
- Cridar `team_pool_buckets.py` despres de la materialitzacio de files base i abans de la seleccio principal entre exercicis.
- Garantir que la resta del flux actual rebi subtotals d'exercici sense saber com s'han produit.
- Conservar `main_selected_contributors` com a contributors crus.

#### Restriccions
- No tocar builder ni validacio.
- No refer la seleccio general si nomes cal inserir una fase previa.

### Subagent S3.B - Tests de runtime integrat
#### Write set
- `competicions_trampoli/tests/scoring/test_engine_selection_runtime.py`
- `competicions_trampoli/tests/equips/test_engine_team_runtime.py`

#### Tasques
- Cobrir:
  - `team_pool` actual `flat` sense regressio
  - `team_pool` nou `per_exercici`
  - seleccio posterior entre exercicis
  - agregacio posterior entre exercicis
  - contributors heretats amb `exercici` preservat

#### Restriccions
- No tocar codi productiu.

## Fase 4. Builder I Persistencia Del Payload

### Objectiu
- Exposar el mode nou de forma clara i impedir configuracions invalides des de UI.

### Subagent S4.A - Builder
#### Write set
- `competicions_trampoli/templates/classificacions/_puntuacio_script.html`

#### Tasques
- Afegir el selector de mode:
  - `flat`
  - `per_exercici`
- Renderitzar controls per exercici quan pertoqui.
- Hidratar i serialitzar:
  - `team_pool_mode_per_aparell`
  - `team_pool_participants_per_exercici_per_aparell`
  - `team_pool_agregacio_participants_per_exercici_per_aparell`
- Deshabilitar o ocultar `candidate_source_per_aparell` incompatible.
- Actualitzar el resum viu.

#### Restriccions
- No tocar backend.
- No canviar la UX de modes que no participen en aquest pla.

## Fase 5. Desempats I Restriccions D'Entrada

### Dependencia
- Es pot executar en paral.lel amb S4.A, pero necessita contracte tancat de S1.

### Objectiu
- Fer explicita la restriccio del nou mode respecte als pipelines de `desempat`.

### Subagent S5.A - Restriccio de desempats
#### Write set
- `competicions_trampoli/services/classificacions/pipeline_runtime.py`

#### Tasques
- Revisar si cal una guarda explicita al runtime de pipeline o si la validacio de schema ja talla prou aviat.
- Si cal, afegir una proteccio defensiva minima per rebutjar el mode nou quan aparegui en un tie recalculat.
- No implementar el nou mode dins de `pipeline_runtime.py`.

#### Restriccions
- No duplicar la logica del main runtime.

### Subagent S5.B - Tests de desempat
#### Write set
- `competicions_trampoli/tests/classificacions/test_compute_engine_contract.py`

#### Tasques
- Afegir un cas que confirmi:
  - `main_selected_contributors` continua usable amb contributors crus i `exercici` preservat
- Afegir un cas negatiu:
  - tie recalculat que intenta usar aquest mode nou des de zero i es rebutjat

#### Restriccions
- No tocar codi productiu.

## Fase 6. Integracio Final I Regressio

### Objectiu
- Verificar el flux complet sense regressions en modes existents.

### Owner
- Integrador principal

### Write set
- cap obligatori; nomes ajustos d'integracio si cal

### Suite minima recomanada
- `competicions_trampoli.tests.classificacions.test_engine_schema`
- `competicions_trampoli.tests.scoring.test_engine_team_pool_buckets`
- `competicions_trampoli.tests.scoring.test_engine_selection_runtime`
- `competicions_trampoli.tests.equips.test_engine_team_runtime`
- `competicions_trampoli.tests.classificacions.test_compute_engine_contract`

### Regressions critiques a mirar
- `per_member` continua exactament igual
- `team_pool flat` continua exactament igual
- `candidate_source_per_aparell` continua disponible fora del mode nou
- `detail` i `display` no perden contributors ni camps

## Dependencies Entre Subagents

### Es poden obrir en paral.lel des del principi
- S1.A
- S1.B
- S2.A
- S2.B
- S4.A

### Han d'esperar contracte o runtime base
- S3.A espera S2.A
- S3.B espera S3.A
- S5.A espera S1.A
- S5.B espera S3.A i S5.A

## Instruccions Per A L'Orquestrador

### Regla base
- Cada subagent rep nomes aquest document com a context.
- Cap subagent no ha d'assumir decisions fora del que hi diu.
- Si troba un dubte no resolt, no ha d'inventar contracte nou; ha de reportar bloqueig.

### Ordre recomanat
1. Llancar en paral.lel:
   - S1.A
   - S1.B
   - S2.A
   - S2.B
   - S4.A
2. Integrar contracte i runtime base.
3. Llancar:
   - S3.A
4. Quan S3.A tanqui:
   - S3.B
   - S5.A
5. Quan S5.A tanqui:
   - S5.B
6. Integracio final i suite de regressio.

### Regla de merge
- L'integrador es l'unic owner de conflictes entre `selection_runtime.py` i `orchestrator.py`.
- Si un subagent toca fora del seu write scope, el canvi no s'integra automaticament.

## Criteris De Done
- El builder pot configurar `team_pool` per exercici dins del context valid.
- El backend valida el shape nou i rebutja incompatibilitats de forma clara.
- El runtime calcula subtotals per exercici entre membres abans de la seleccio principal entre exercicis.
- El `team_pool flat` existent no regressa.
- Els `main_selected_contributors` continuen sent contributors crus amb `exercici` preservat.
- Els desempats no poden recalcular aquest mode nou des de zero.
- La suite minima recomanada queda en verd.

## Notes D'Implementacio
- El canvi s'ha de concebre com una capa nova de preprocessat, no com una branca especial al final del calcul.
- La temptacio de resoldre-ho dins de `teams.py` es incorrecta: alla ja es massa tard.
- La temptacio de reusar `participants_per_aparell` tambe es incorrecta: aquella capa opera sobre resultats per membre, no sobre bosses per numero d'exercici.
- El modul nou ha de ser petit i amb contracte net; la complexitat real ha de quedar absorbida per les configuracions existents de seleccio/agregacio.

# Pla D'Implementacio De `desempat` Amb Entrada Des De `puntuacio` Per Subagents

## Objectiu
- Permetre que cada criteri de `desempat` pugui triar entre:
  - recalcular des de zero sobre el conjunt cru actual
  - recalcular sobre un conjunt d'exercicis originals que han contribuït a `puntuacio`
- Mantenir el model de pipeline propi de `desempat`.
- Fer que el canvi sigui consistent per a tots els tipus de classificacio:
  - `individual`
  - `equips` amb `derived_from_individual`
  - `equips` amb `native_team`
  - extensible a `entitat`
- Definir una implementacio executable per subagents en paral.lel, amb write scopes clars i sense dependència de context oral.

## Resum Executiu
- El sistema actual de `desempat` recalcula normalment des de zero sobre el seu pipeline efectiu.
- La novetat no ha de substituir aquest mode.
- El contracte actual de `desempat` continua excloent el tractament per exercici dels camps:
  - `camps_mode_per_aparell`
  - `camps_per_exercici_per_aparell`
  - `agregacio_camps_per_exercici_per_aparell`
- La novetat afegeix un segon mode d'entrada:
  - `desempat` rep com a input els exercicis originals que han contribuït al conjunt de `puntuacio`
- Aquest conjunt d'entrada no s'agafa del resultat final agregat.
- S'agafa del conjunt que sobreviu a l'ultim pas selectiu per aparell i, des d'alla, es traça enrere als exercicis originals contributors.
- Amb aquest input, `desempat` executa el seu pipeline complet igual que ara.

## Regla Principal
- `desempat` continua sent un pipeline propi.
- La novetat no canvia la semantica del pipeline de `desempat`.
- La novetat canvia nomes la font inicial de files.
- El sistema ha de suportar dos modes d'entrada:
  - `raw_exercises`
  - `main_selected_contributors`

## Decisions Tancades
- S'ha de mantenir l'opcio actual de `desempat` des de zero.
- La novetat ha de ser disponible per a tots els tipus de classificacio.
- La traçabilitat necessaria ha de viure fora de la logica principal de comput.
- Aquesta traçabilitat ha d'anar en fitxers externs, no incrustada en el core.
- No es modelara ara cap variant especial per `victories`.
- El tall correcte per construir `main_selected_contributors` es:
  - el conjunt que sobreviu a l'ultim pas selectiu per aparell
  - i des d'aquest conjunt es traça enrere fins als exercicis originals contributors

- El pipeline propi de `desempat` continua treballant amb camps comuns per aparell.
- Aquest pla no obre suport per camps per exercici dins del pipeline de `desempat`.

## No Objectius
- No substituir el mode actual `raw_exercises`.
- No redissenyar `victories`.
- No reobrir la semantica de `team_pool` fora del que descriu aquest pla.
- No convertir la traçabilitat en el nou model intern principal del motor.

## Semantica Tancada

### Modes d'entrada de `desempat`

#### 1. `raw_exercises`
- Comportament actual.
- El tie calcula sobre el conjunt cru d'exercicis del seu context efectiu.
- El tie continua fent la valoracio de camps sobre base comuna per aparell.

#### 2. `main_selected_contributors`
- El tie calcula sobre els exercicis originals que han contribuït al conjunt de `puntuacio`.
- Aquest input no es el resultat final agregat.
- Aquest input es un conjunt d'exercicis originals ja filtrat per la traçabilitat de `puntuacio`.

- Un cop fixat aquest input, el tie continua calculant amb camps comuns per aparell.

## Regla De Tall Del Conjunt De `puntuacio`

### Principi unificador
`main_selected_contributors` s'obte des de:
- el conjunt que ha sobreviscut a l'ultim pas selectiu per aparell de `puntuacio`
- i es projecta enrere fins als exercicis originals contributors

### Contextos

#### `individual`
- l'ultim pas selectiu per aparell es el pas 3
- s'agafen les files que sobreviuen al pas 3
- es traça enrere fins als exercicis originals que les han format

#### `native_team`
- l'ultim pas selectiu per aparell es el pas 3
- s'agafen les files d'equip que sobreviuen al pas 3
- es traça enrere fins als exercicis originals d'equip que les han format

#### `derived_from_individual` amb `per_member`
- l'ultim pas selectiu per aparell es el pas 5
- primer es retenen nomes els membres que contribueixen al resultat final per aparell
- despres, dins de cada membre retingut, es mira quines files havien sobreviscut al pas 3
- finalment, es traça enrere fins als exercicis originals que havien format aquestes files

#### `derived_from_individual` amb `team_pool`
- l'ultim pas selectiu per aparell es el pas 3 sobre la bossa comuna
- s'agafen les files que sobreviuen al pas 3
- es traça enrere fins als exercicis originals contributors

### Important
- El pas 4 no defineix un tall nou. Agrega, pero no selecciona.
- Amb pretractament, no s'exposa la fila agregada del pretractament.
- S'exposen els exercicis originals que han contribuït a la fila que sobreviu.

## Model D'Arquitectura

### Idea base
- El motor continua calculant.
- Un subsistema extern de traçabilitat observa el motor i construeix el conjunt de contributors.
- `desempat` pot demanar aquest conjunt com a input.

### Paquet nou proposat
- `competicions_trampoli/services/classificacions/provenance/__init__.py`
- `competicions_trampoli/services/classificacions/provenance/models.py`
- `competicions_trampoli/services/classificacions/provenance/collector.py`
- `competicions_trampoli/services/classificacions/provenance/builders.py`
- `competicions_trampoli/services/classificacions/provenance/queries.py`

## Contracte De Traçabilitat

### Objectiu
- No cal guardar tots els passos del motor com a API publica.
- Cal guardar prou informacio per reconstruir `main_selected_contributors`.

### Peces minimes

#### `raw_row`
- representa un exercici original
- camps minims:
  - `row_id`
  - `app_id`
  - `exercici`
  - `participant_kind`
  - `participant_id`
  - `value`
  - `by_camp`

#### `derived_row`
- representa una fila derivada pel pipeline
- camps minims:
  - `row_id`
  - `stage`
  - `app_id`
  - `participant_kind`
  - `participant_id`
  - `value`
  - `by_camp`
  - `source_row_ids`

#### `selection_snapshot`
- registra una seleccio rellevant
- camps minims:
  - `snapshot_id`
  - `stage`
  - `app_id`
  - `subject_kind`
  - `subject_id`
  - `selected_row_ids`

### Stages necessaris
- `raw`
- `candidate_source`
- `exercise_selection`
- `member_selection`

### Regla
- No s'exposen tots els stages al builder.
- Pero si han d'existir a la traçabilitat per resoldre `main_selected_contributors`.

## Contracte De `desempat`

### Camps nous per tie
Es proposa afegir un bloc nou:

```json
{
  "input_source": {
    "mode": "raw_exercises"
  }
}
```

o

```json
{
  "input_source": {
    "mode": "main_selected_contributors"
  }
}
```

### Regla
- `raw_exercises` es el default.
- `main_selected_contributors` nomes es valid si el runtime principal pot construir aquest conjunt.

## UX Objectiu

### Builder de `desempat`
Dins de cada criteri:
- mantenir la configuracio actual del pipeline
- afegir un selector clar:
  - `Conjunt inicial`
    - `Tots els exercicis disponibles`
    - `Nomes exercicis que han contribuït a puntuacio`

### Copy recomanada
- `Tots els exercicis disponibles`
  - "El desempat recalcula des de zero sobre el conjunt cru del seu context."
- `Només exercicis que han contribuït a puntuació`
  - "El desempat recalcula sobre els exercicis originals que han contribuït al resultat de puntuació d'aquest aparell."

### Copy contextual
Per `derived + per_member`:
- "Primer es retenen els membres que han contribuït al resultat final per aparell. Després es recuperen només els exercicis originals contributors d'aquests membres."

## UI Objectiu

### Visibilitat
- la nova opcio ha d'estar visible a tots els tipus de classificacio
- si hi ha limitacions contextuals, s'han d'explicar amb hint, no amb semantica amagada

### Resum viu
- el resum de `desempat` ha d'incloure la font d'entrada
- exemples:
  - "Recalcula des de tots els exercicis disponibles"
  - "Recalcula només des dels exercicis que han contribuït a puntuació"

## Backend Objectiu

### Components

#### 1. Runtime principal
- exposa punts de hook per construir la traçabilitat
- no viu la traçabilitat dins del core

#### 2. Provenance collector
- rep events/rows del runtime
- construeix els snapshots necessaris

#### 3. Provenance query layer
- resol `main_selected_contributors` per:
  - inscripcio
  - equip derivat
  - equip natiu
  - grup si cal

#### 4. Runtime de `desempat`
- quan el tie fa servir `input_source.mode = main_selected_contributors`
- demana el conjunt al query layer
- i executa el pipeline complet des de les files retornades

## Mapa De Moduls

### Backend nou
- `services/classificacions/provenance/models.py`
- `services/classificacions/provenance/collector.py`
- `services/classificacions/provenance/builders.py`
- `services/classificacions/provenance/queries.py`

### Backend existent a tocar
- `services/classificacions/pipeline_runtime.py`
- `services/legacy/services_classificacions_2.py`
- `services/classificacions/validation.py`
- `services/classificacions/builder.py`
- `services/classificacions/ties/pipeline_builder.py`
- `services/classificacions/ties/ui_projection.py`
- `services/classificacions/ties/serializer_save.py`
- `services/classificacions/classificacio_templates.py`

### Frontend
- `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
- o el slice `templates/classificacions/builder/scripts/ties/*` segons la fase real del builder

## Fases D'Implementacio

## Fase 0. Contracte Congelat

### Objectiu
- Fixar la semantica sense ambiguitats abans d'obrir treball en paral.lel.

### Resultat esperat
- queden congelats:
  - `input_source.mode`
  - la regla de tall per context
  - el paquet `provenance/`

### Owner
- Integrador principal

### Write set
- aquest document

## Fase 1. Contracte I Validacio De `desempat`

### Objectiu
- Fer que el schema i el builder coneguin la nova opcio d'entrada.

### Subagent D1.1 - Schema i persistencia
#### Write set
- `services/classificacions/ties/pipeline_builder.py`
- `services/classificacions/ties/serializer_save.py`
- `services/classificacions/classificacio_templates.py`

#### Tasques
- afegir `input_source.mode`
- persistir-lo al tie canonic
- fer roundtrip a templates

### Subagent D1.2 - Validacio
#### Write set
- `services/classificacions/validation.py`

#### Tasques
- validar `input_source.mode`
- rebutjar valors desconeguts
- preparar hooks per validar contextualment `main_selected_contributors`

### Subagent D1.3 - Tests de contracte
#### Write set
- tests de templates i validacio de classificacions

#### Done
- es pot serialitzar, validar i reobrir el camp nou

## Fase 2. Paquet De Provenance

### Objectiu
- Crear la infraestructura externa de traçabilitat.

### Subagent D2.1 - Models i collector
#### Write set
- `services/classificacions/provenance/models.py`
- `services/classificacions/provenance/collector.py`

#### Tasques
- definir `raw_row`
- definir `derived_row`
- definir `selection_snapshot`
- definir una API de registre

### Subagent D2.2 - Builders i queries
#### Write set
- `services/classificacions/provenance/builders.py`
- `services/classificacions/provenance/queries.py`

#### Tasques
- construir snapshots finals
- resoldre `main_selected_contributors`
- donar una API estable per context

### Dependencia
- D2.1 i D2.2 poden anar en paral.lel si es congela abans el contracte de models

## Fase 3. Instrumentacio Del Runtime Principal

### Objectiu
- Fer que `puntuacio` emeti la traça necessaria sense barrejar-se amb la seva logica principal.

### Subagent D3.1 - Hooks del runtime pur
#### Write set
- `services/classificacions/pipeline_runtime.py`

#### Tasques
- afegir punts de hook per:
  - files base
  - files derivades
  - snapshots de seleccio

### Subagent D3.2 - Integracio al calcul real
#### Write set
- `services/legacy/services_classificacions_2.py`

#### Tasques
- registrar:
  - exercicis originals
  - files després de `candidate_source`
  - files seleccionades a pas 3
  - files seleccionades a pas 5 quan aplica
- no canviar el resultat numeric

### Notes
- la semantica del tall ha de seguir exactament el contracte d'aquest document

## Fase 4. Query De Contributors Per Context

### Objectiu
- Resoldre el conjunt `main_selected_contributors` de manera unificada.

### Subagent D4.1 - `individual` i `native_team`
#### Write set
- `services/classificacions/provenance/queries.py`
- tests associats

#### Tasques
- resoldre el tall al pas 3
- traçar enrere a exercicis originals

### Subagent D4.2 - `derived_from_individual`
#### Write set
- `services/classificacions/provenance/queries.py`
- tests associats

#### Tasques
- `per_member`:
  - tall a pas 5
  - traça enrere a pas 3 del membre
  - traça enrere a exercicis originals
- `team_pool`:
  - tall a pas 3 del pool
  - traça enrere a exercicis originals

### Dependencia
- D4.1 i D4.2 poden anar en paral.lel si comparteixen només helpers de lectura estables

## Fase 5. Runtime De `desempat` Amb Fonts D'Entrada Multiples

### Objectiu
- Permetre que el tie executi el seu pipeline complet des de dos inputs possibles.

### Subagent D5.1 - Runtime tie input source
#### Write set
- `services/classificacions/pipeline_runtime.py`
- helpers de ties si cal

#### Tasques
- afegir resolucio de font d'entrada:
  - `raw_exercises`
  - `main_selected_contributors`
- assegurar que el pipeline posterior es el mateix

### Subagent D5.2 - Adaptacio de criteris de tie
#### Write set
- `services/legacy/services_classificacions_2.py`

#### Tasques
- quan el tie demani `main_selected_contributors`, usar el query layer
- executar el criteri sobre aquest conjunt

## Fase 6. Builder UX I UI

### Objectiu
- Fer visible i comprensible la novetat al builder.

### Subagent D6.1 - UI
#### Write set
- `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
- o `templates/classificacions/builder/scripts/ties/*`

#### Tasques
- afegir selector `Conjunt inicial`
- hidratar-lo
- llegir-lo per save
- mostrar hints contextuals

### Subagent D6.2 - Projeccions UI
#### Write set
- `services/classificacions/ties/ui_projection.py`
- `services/classificacions/builder.py`

#### Tasques
- fer que reopen del builder mostri correctament el mode d'entrada
- afegir copy de resum al tie

## Fase 7. Cobertura I Paritat

### Objectiu
- Cobrir tots els contextos i evitar regressions.

### Subagent D7.1 - Tests de scoring
#### Write set
- `tests/scoring/...`

#### Casos minims
- individual:
  - `raw_exercises`
  - `main_selected_contributors`
- native team:
  - `raw_exercises`
  - `main_selected_contributors`
- derived + per_member:
  - `raw_exercises`
  - `main_selected_contributors`
- derived + team_pool:
  - `raw_exercises`
  - `main_selected_contributors`

### Subagent D7.2 - Tests de builder/template
#### Write set
- `tests/classificacions/...`

#### Casos minims
- save/reopen
- validacio
- templates
- resum viu / copy

## Ordre Recomanat D'Orquestracio

### Onada A
- Fase 0
- D1.1
- D1.2

### Onada B
- D2.1
- D2.2

### Onada C
- D3.1
- D6.1

### Onada D
- D3.2
- D4.1
- D4.2

### Onada E
- D5.1
- D5.2
- D6.2

### Onada F
- D7.1
- D7.2
- integracio final

## Write Scopes Recomanats

### Contracte
- `services/classificacions/ties/pipeline_builder.py`
- `services/classificacions/ties/serializer_save.py`
- `services/classificacions/classificacio_templates.py`
- `services/classificacions/validation.py`

### Provenance
- `services/classificacions/provenance/*`

### Runtime
- `services/classificacions/pipeline_runtime.py`
- `services/legacy/services_classificacions_2.py`

### UI/UX
- `templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
- `templates/classificacions/builder/scripts/ties/*`
- `services/classificacions/ties/ui_projection.py`
- `services/classificacions/builder.py`

### Tests
- `tests/scoring/...`
- `tests/classificacions/...`

## Criteri De Done
- `desempat` permet escollir la font inicial.
- `raw_exercises` continua funcionant igual.
- `main_selected_contributors` funciona a:
  - individual
  - native team
  - derived per_member
  - derived team_pool
- El tall del conjunt es coherent amb aquest document.
- La traçabilitat viu fora del core de comput.
- El builder ho exposa de manera entenedora.
- Els tests focalitzats passen.

## Riscos Principals

### Risc 1. Ambiguitat del tall
- Mitigacio:
  - no permetre interpretacions alternatives
  - seguir exactament la regla d'ultim pas selectiu per aparell

### Risc 2. Barrejar traçabilitat i calcul
- Mitigacio:
  - paquet extern `provenance/`
  - API de hooks minima

### Risc 3. Divergencia entre contexts
- Mitigacio:
  - mateixa API de query
  - mateixa semantica de font d'entrada

### Risc 4. UI confusa
- Mitigacio:
  - dues opcions nomes
  - copy molt clara
  - resum viu

## Checklist Final
- [ ] contracte congelat
- [ ] schema nou de `desempat`
- [ ] paquet `provenance/`
- [ ] hooks del runtime principal
- [ ] queries de contributors per context
- [ ] runtime de tie amb font d'entrada nova
- [ ] UI i UX de builder
- [ ] tests focalitzats
- [ ] integracio final

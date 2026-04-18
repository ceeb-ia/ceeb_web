# Pla D'Implementacio De `puntuacio` Amb Camps Per Exercici Per Subagents

## Objectiu
- Permetre que, dins de cada aparell de `puntuacio`, cada exercici es pugui valorar amb camps diferents.
- Fer que aquest valor per exercici entri al flux existent sense inventar una semantica nova despres:
  - formacio del conjunt candidat
  - pretractament (`candidate_source`)
  - seleccio d'exercicis
  - agregacio d'exercicis
  - agregacio entre membres, si aplica
  - agregacio entre aparells
- Mantenir el comportament actual com a fallback clar quan no s'activa el mode nou.
- Estructurar la feina de manera que diversos subagents puguin treballar en paral.lel amb write scopes nets i poca coordinacio.

## Abast
- Inclou `puntuacio` en mode `score`.
- Inclou:
  - classificacions individuals
  - equips derivats (`derived_from_individual`)
  - equips natius (`native_team`)
- No inclou ara:
  - `victories`
  - canvis nous a `desempat`
  - extensions del contracte de pipeline de `desempat` per acceptar camps per exercici

## Resum Executiu
- Avui, dins d'un aparell, tots els exercicis comparteixen:
  - `camps_per_aparell[app_id]`
  - `agregacio_camps_per_aparell[app_id]`
- El canvi nou no toca la semantica de seleccio o pretractament.
- El canvi toca la capa anterior: la construccio del valor de cada exercici.
- La idea correcta es:
  - primer es calcula el valor de cada exercici segons la seva configuracio de camps
  - despres tot el pipeline continua igual
- El builder ha de mantenir visible la configuracio comuna de l'aparell.
- El mode nou s'activa explicitament per aparell i, quan esta actiu, afegeix selectors per exercici detectat segons `nombre_exercicis` del `CompeticioAparell`.
- `desempat` queda expressament fora d'aquest canvi:
  - si aquestes claus entren a `desempat[*].pipeline`, s'han de stripar abans de persistir
  - el tie no les ha de validar ni conservar al pipeline canonitzat
  - el tie continua treballant sobre base comuna per aparell en el tractament dels camps

## Decisions Tancades
- El mode ha de ser explicit. El sistema no l'ha de derivar automaticament.
- `camps_per_aparell` continua sent obligatori com a base comuna de l'aparell.
- El builder ha de mantenir visibles els camps comuns de l'aparell encara que el mode per exercici estigui actiu.
- El mode nou ha de tenir fallback als camps comuns de l'aparell per a qualsevol exercici no configurat explicitament.
- El fallback d'un exercici es complet, no parcial:
  - si falta `camps`
  - o falta `agregacio`
  - aquell exercici hereta integrament la base comuna de l'aparell
- L'agregacio de camps tambe ha de poder ser per exercici.
- Si canvia `nombre_exercicis`, la configuracio sobrant s'ha de podar en save/hidratacio.
- El resum viu ha de ser:
  - compacte si la configuracio efectiva de tots els exercicis coincideix
  - detallat si la configuracio efectiva divergeix
- `by_camp` ha de continuar sent ric; el mode per exercici nomes canvia el calcul de `value`.
- L'abast es nomes `puntuacio`, no `victories`.
- `desempat` no ha d'heretar ni persistir `camps_mode_per_aparell`, `camps_per_exercici_per_aparell` ni `agregacio_camps_per_exercici_per_aparell`.
- Si aquestes claus apareixen al payload raw de `desempat`, s'han de netejar abans de validacio i persistencia.
- La semantica desitjada de `desempat` es mantenir una base comuna de camps per aparell dins del pipeline actual.
- Si la classificacio passa a `victories`, les claus noves es conserven pero queden ignorades.
- La poda de claus sobrants nomes s'ha de fer quan ja es coneix la competicio i el seu `nombre_exercicis`.

## Principi Functional

### Com funciona avui
Per cada exercici d'un aparell:
1. es llegeixen els camps comuns de l'aparell
2. s'aplica l'agregacio de camps comuna
3. surt un valor d'exercici
4. aquest valor entra a `candidate_source`, seleccio i agregacions posteriors

### Com ha de funcionar amb el canvi
Per cada exercici d'un aparell:
1. es resol si usa configuracio comuna o configuracio propia per exercici
2. es llegeixen els camps d'aquell exercici
3. s'aplica l'agregacio de camps d'aquell exercici
4. surt un valor d'exercici
5. aquest valor entra a `candidate_source`, seleccio i agregacions posteriors exactament igual que avui

### Consequencia clau
- No s'ha de tocar la idea de `candidate_source`.
- No s'ha de tocar la semantica de seleccio d'exercicis.
- S'ha de tocar la valoracio de la fila base d'exercici.
- `by_camp` no s'ha de fer minimalista per exercici; ha de continuar sent reutilitzable pels fluxos posteriors.

## Shape Proposada

### Camps nous a `puntuacio`
```json
{
  "camps_mode_per_aparell": {
    "12": "per_exercici"
  },
  "camps_per_exercici_per_aparell": {
    "12": {
      "1": ["A"],
      "2": ["B"]
    }
  },
  "agregacio_camps_per_exercici_per_aparell": {
    "12": {
      "1": "sum",
      "2": "avg"
    }
  }
}
```

### Camps existents que continuen sent base comuna
```json
{
  "camps_per_aparell": {
    "12": ["total"]
  },
  "agregacio_camps_per_aparell": {
    "12": "sum"
  }
}
```

### Regles de resolucio
Per un `app_id` i `exercici` concret:
1. si `camps_mode_per_aparell[app_id] != "per_exercici"`:
   - usa `camps_per_aparell[app_id]`
   - usa `agregacio_camps_per_aparell[app_id]`
2. si `camps_mode_per_aparell[app_id] == "per_exercici"`:
   - prova `camps_per_exercici_per_aparell[app_id][exercici]`
   - prova `agregacio_camps_per_exercici_per_aparell[app_id][exercici]`
   - si falta qualsevol dels dos, fallback a la configuracio comuna de l'aparell

### Valors admesos
- `camps_mode_per_aparell[app_id]`:
  - `comu`
  - `per_exercici`

## UX Objectiu

### Dins de cada targeta d'aparell
Es mantindra:
- selector comu de camps
- agregacio comuna de camps

I s'afegira:
- toggle o selector:
  - `Tractament de camps: Comu / Per exercici`

Si el mode es `per_exercici`:
- es mostren tants blocs com exercicis tingui l'aparell a la competicio
- cada bloc d'exercici te:
  - selector de camps
  - agregacio de camps
  - copy curta indicant que, si es deixa buit, hereta la configuracio comuna

### Copy recomanada
- configuracio comuna:
  - "Base comuna per a tots els exercicis d'aquest aparell"
- bloc per exercici:
  - "Exercici 1"
  - "Exercici 2"
  - etc.
- hint:
  - "Si no es defineix, aquest exercici hereta la base comuna de l'aparell."

## Impacte Arquitectonic

### Backend
- El pipeline ha d'admetre una nova capa "per exercici dins de l'aparell".
- El runtime ha de resoldre camps/agregacio per `app_id + exercici`.
- El calcul legacy real ha de construir `v_ex` amb aquesta resolucio nova.
- La conversio a plantilles ha de mapar les claus per aparell, igual que ja fa amb altres mapes.

### Frontend
- El builder ha de poder:
  - detectar `nombre_exercicis` per aparell
  - renderitzar blocs dinamics per exercici
  - llegir/hidratar els mapes nous
  - podar configuracions sobrants
  - resumir la diferencia entre exercicis

## No Objectius
- No afegir tractament per exercici a `victories`.
- No tocar la semantica de `desempat`.
- No permetre `camps_mode_per_aparell`, `camps_per_exercici_per_aparell` ni `agregacio_camps_per_exercici_per_aparell` dins de `desempat[*].pipeline`.
- No redissenyar el model de `candidate_source`.
- No canviar la seleccio d'exercicis ni d'aparells mes enlla d'alimentar-les amb valors per exercici ja calculats.
- No podar configuracions per exercici a nivell de plantilla global si no es coneix `nombre_exercicis`.

## Orquestracio Recomanada

## Fase 0. Contracte Congelat

### Objectiu
- Fixar noms de camps, fallback i semantica abans d'obrir fronts en paral.lel.

### Resultat esperat
- El contracte d'aquest document es considera bloquejat per a la resta de fases.

### Owner
- Integrador principal

### Write set
- aquest document

### Done
- Noms finals acceptats:
  - `camps_mode_per_aparell`
  - `camps_per_exercici_per_aparell`
  - `agregacio_camps_per_exercici_per_aparell`

## Fase 1. Schema, Validacio i Plantilles

### Objectiu
- Fer que el model persistent i el mapping de plantilles entenguin el nou shape.

### Subagent S1.1 - Validacio de schema
#### Write set
- `competicions_trampoli/services/classificacions/validation.py`

#### Tasques
- validar `camps_mode_per_aparell`
- validar `camps_per_exercici_per_aparell`
- validar `agregacio_camps_per_exercici_per_aparell`
- validar que les claus d'exercici siguin enters positius
- validar que els camps siguin scoreables dins de l'aparell corresponent

#### Notes
- no decidir defaults aqui; nomes validar shape i coherencia

### Subagent S1.2 - Templates i portabilitat
#### Write set
- `competicions_trampoli/services/classificacions/classificacio_templates.py`

#### Tasques
- exportar els mapes nous de id -> codi
- importar els mapes nous de codi -> id
- incloure les claus noves a requirements i roundtrip helpers

### Subagent S1.3 - Tests de contracte
#### Write set
- `competicions_trampoli/tests/classificacions/test_templates_competition.py`
- `competicions_trampoli/tests/classificacions/test_templates_global.py`
- tests de validacio pertinents

#### Tasques
- cobrir roundtrip
- cobrir validacio
- cobrir poda de claus sobrants quan canvia `nombre_exercicis`

### Dependencia
- S1.1 i S1.2 poden anar en paral.lel si es respecta el contracte congelat.
- S1.3 pot arrencar amb stubs i tancar al final de la fase.

## Fase 2. Runtime Pur Del Pipeline

### Objectiu
- Ensenyar al runtime a resoldre camps per `app_id + exercici`.

### Subagent S2.1 - Normalitzacio del pipeline
#### Write set
- `competicions_trampoli/services/classificacions/pipeline_runtime.py`

#### Tasques
- afegir els nous camps a `SCORING_PIPELINE_ALLOWED_KEYS`
- normalitzar:
  - `camps_mode_per_aparell`
  - `camps_per_exercici_per_aparell`
  - `agregacio_camps_per_exercici_per_aparell`
- incloure aquests camps a:
  - `build_main_scoring_pipeline_from_schema`
  - `normalize_scoring_pipeline`
  - serializers/compactadors de pipeline

### Subagent S2.2 - Resolucio per exercici
#### Write set
- `competicions_trampoli/services/classificacions/pipeline_runtime.py`

#### Tasques
- introduir helpers nous de resolucio:
  - `resolve_fields_for_app_exercise(app_id, ex_idx, pipeline)`
  - `resolve_field_agg_for_app_exercise(app_id, ex_idx, pipeline)`
- assegurar que el flux de calcul per exercici construeix `computed_rows` amb aquesta resolucio

### Notes
- S2.1 i S2.2 s'han de repartir el fitxer per franges clares o fer-se en serie curta.
- No obrir alhora dos workers amb edicio lliure sobre el mateix bloc.

## Fase 3. Calcul Legacy Real

### Objectiu
- Portar la semantica nova al calcul que avui genera el resultat final real.

### Subagent S3.1 - Calcul individual i derived team
#### Write set
- `competicions_trampoli/services/legacy/services_classificacions_2.py`

#### Tasques
- canviar la construccio de `v_ex` per usar camps/agregacio resolts per exercici
- mantenir intacte el flux posterior:
  - candidate rows
  - pretractament
  - seleccio
  - agregacions

### Subagent S3.2 - Casos native team
#### Write set
- `competicions_trampoli/services/legacy/services_classificacions_2.py`

#### Tasques
- revisar el branch de `native_team`
- garantir que el calcul de l'exercici natiu tambe usa la resolucio per exercici quan aplica

### Notes
- Aquests dos subagents no s'han de llançar alhora si tots dos editen el mateix bloc.
- Millor:
  - S3.1 implementa
  - S3.2 revisa i tanca el branch `native_team`

## Fase 4. Builder UI i Hidratacio

### Objectiu
- Afegir la UI del mode `per_exercici` per aparell i connectar-la amb el schema nou.

### Subagent S4.1 - HTML i render per aparell
#### Write set
- `competicions_trampoli/templates/classificacions/puntuacio.html`
- `competicions_trampoli/templates/classificacions/_puntuacio_script.html`

#### Tasques
- afegir el toggle `comu / per_exercici`
- renderitzar blocs per exercici segons `nombre_exercicis`
- mantenir visibles els camps comuns de l'aparell

### Subagent S4.2 - Read/save/hydration
#### Write set
- `competicions_trampoli/templates/classificacions/_puntuacio_script.html`

#### Tasques
- llegir:
  - `camps_mode_per_aparell`
  - `camps_per_exercici_per_aparell`
  - `agregacio_camps_per_exercici_per_aparell`
- hidratar-los correctament
- podar configuracions sobrants si baixa `nombre_exercicis`

### Subagent S4.3 - Resum viu
#### Write set
- `competicions_trampoli/templates/classificacions/_puntuacio_script.html`

#### Tasques
- resum compacte si tots els exercicis coincideixen
- resum detallat si divergeixen
- assegurar que el llenguatge del resum continua alineat amb el calcul real

### Dependencia
- S4.1 i S4.2 poden anar gairebe en paral.lel si es fixa abans el nom dels `data-*`.
- S4.3 millor al final de la fase.

## Fase 5. Tests Funcionals

### Objectiu
- Cobrir el comportament nou de punta a punta.

### Subagent S5.1 - Tests de scoring
#### Write set
- `competicions_trampoli/tests/scoring/team/test_classificacio_compute_modes.py`
- si cal, nous tests a `tests/scoring/...`

#### Casos minims
- individual, 2 exercicis, camps diferents per exercici
- derived team, `per_member`, camps diferents per exercici
- derived team, `team_pool`, camps diferents per exercici
- native team, camps diferents per exercici
- candidate source `raw_exercise`
- candidate source `participant_aggregate`

### Subagent S5.2 - Tests de builder/template
#### Write set
- tests de templates i validacio ja existents

#### Casos minims
- roundtrip de schema
- fallback a camps comuns
- poda en reduir `nombre_exercicis`
- resum viu i render de blocs per exercici

## Fase 6. Integracio i Neteja

### Objectiu
- Tancar incoherencies entre UI, schema i runtime.

### Owner
- Integrador principal

### Tasques
- revisar que el fallback sigui exactament el mateix a:
  - UI
  - runtime
  - validacio
  - templates
- revisar que no s'hagi tocat `victories`
- revisar que no hi hagi mirrors legacy nous innecessaris

## Ordre Recomanat D'Execucio

### Onada A
- Fase 0 completa
- S1.1
- S1.2

### Onada B
- S2.1
- S4.1

### Onada C
- S2.2
- S4.2

### Onada D
- S3.1
- S5.2

### Onada E
- S3.2
- S4.3
- S5.1

### Onada F
- integracio final
- passada de tests focalitzats

## Write Scopes Recomanats

### Backend contracte
- `services/classificacions/validation.py`
- `services/classificacions/classificacio_templates.py`

### Runtime pur
- `services/classificacions/pipeline_runtime.py`

### Calcul legacy
- `services/legacy/services_classificacions_2.py`

### UI
- `templates/classificacions/puntuacio.html`
- `templates/classificacions/_puntuacio_script.html`

### Tests
- `tests/scoring/...`
- `tests/classificacions/...`

## Riscos Principals

### Risc 1. Divergencia entre runtime nou i calcul legacy
- Mitigacio:
  - tests de score amb fixtures petites i numeriques

### Risc 2. UI massa carregada dins de cada aparell
- Mitigacio:
  - mode explicit tancat
  - blocs per exercici plegables si cal en una iteracio posterior

### Risc 3. Fallback no coherent
- Mitigacio:
  - mateixa regla de resolucio documentada i testejada a tots els nivells

### Risc 4. Trencar `team_pool` o `native_team`
- Mitigacio:
  - tests dedicats en Fase 5
  - no tocar la semantica postvaloracio

## Criteri De Done
- La UI permet activar `per_exercici` per aparell.
- Cada exercici pot tenir camps i agregacio de camps propis.
- Si no hi ha config d'un exercici, hereta la comuna.
- El runtime calcula el valor de cada exercici amb la seva config resolta.
- El pretractament i la seleccio treballen sobre aquests valors sense canviar de semantica.
- Templates, validacio i save coneixen el shape nou.
- El resum viu descriu el comportament real.
- La suite focalitzada de scoring + templates + validacio passa.

## Checklist Final D'Orquestracio
- [ ] congelar contracte
- [ ] obrir onada A
- [ ] integrar contracte/schema
- [ ] obrir onada B
- [ ] integrar runtime normalitzat
- [ ] obrir onada C
- [ ] integrar UI read/hydration
- [ ] obrir onada D
- [ ] integrar calcul real
- [ ] obrir onada E
- [ ] passar tests focalitzats
- [ ] repassar resum viu i fallback

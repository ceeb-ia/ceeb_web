# Pla D'Implementacio De Desempat Amb Pipeline Propi

## Objectiu
- Permetre que cada criteri de `desempat` defineixi un pipeline propi, detallat i autosuficient.
- Reutilitzar el mateix motor conceptual de calcul que ja fa servir `puntuacio`.
- No canviar el comportament, l'estructura ni la UX de `puntuacio`.
- Fer que `desempat` s'adapti a `puntuacio`, no a l'inreves.
- Deixar un cami d'implementacio prou clar per a un agent extern sense context previ del modul.

## Regla Mes Important
- `puntuacio` no s'ha de tocar funcionalment.
- No es pot degradar ni simplificar la UX nova de `puntuacio`.
- El nou `desempat` ha de poder expressar un pipeline equivalent al de `puntuacio`, pero encapsulat dins de cada criteri.
- El motor final ha de ser el mateix o una extraccio comuna del mateix algoritme, no dos motors paral.lels divergents.

## Resultat Final Esperat
- Cada element de `schema.desempat[]` tindra:
  - metadades propies del criteri
  - ordre (`asc` o `desc`)
  - un `pipeline` propi
- El pipeline del desempat sera prou ric per calcular un escalar comparable igual que la puntuacio principal.
- El ranking final seguira sent:
  - primer `score` principal de `puntuacio`
  - despres `desempat[0]`
  - despres `desempat[1]`
  - etc.
- `puntuacio` i `desempat.pipeline` compartiran primitives i runtime, pero no schema ni estat implicit.

## No Abast
- No canviar `schema.puntuacio`.
- No canviar la vista ni el contracte de `templates/classificacions/puntuacio.html` ni `templates/classificacions/_puntuacio_script.html` excepte si, en una fase posterior, es decideix reutilitzar helpers visuals sense alterar-ne el comportament.
- No introduir una logica nova de ranking aliena al motor actual.
- No mantenir per sempre la semantica antiga de `Hereta` com a eix del nou disseny.
- No afegir desempats recursius dins de desempats.
- No permetre `mode_resultat_aparells = victories` dins del pipeline de desempat en la primera versio robusta.

## Context Del Codi Actual

### Entrada i sortida del builder
- Vista builder: `competicions_trampoli/views/classificacions/builder.py`
- Hydration del builder: `competicions_trampoli/services/classificacions/builder.py`
- Persistencia schema: `competicions_trampoli/services/classificacions/runtime.py`
- Validacio schema: `competicions_trampoli/services/classificacions/validation.py`
- Builder principal: `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`

### Motor de calcul actual
- Pont public de compute: `competicions_trampoli/services/classificacions/compute.py`
- Implementacio real actual: `competicions_trampoli/services/legacy/services_classificacions_2.py`
- Runtime unificat: `competicions_trampoli/services/classificacions/runtime.py`

### Camps rellevants de `puntuacio` avui
- `aparells`
- `camps_per_aparell`
- `agregacio_camps_per_aparell`
- `agregacio_camps`
- `candidate_source_mode`
- `candidate_source_cfg`
- `candidate_source_per_aparell`
- `exercicis`
- `exercise_selection_scope`
- `mode_seleccio_exercicis`
- `exercicis_per_aparell`
- `agregacio_exercicis`
- `agregacio_aparells`
- `mode_resultat_aparells`
- `ordre`
- `victories`

### Problema actual de `desempat`
- El model actual de `desempat` es mes petit que `puntuacio`.
- Gran part del seu comportament depen d'heretar defaults de `puntuacio`.
- Aixo complica:
  - entendre que calcula realment cada criteri
  - hidratar configs antigues
  - mantenir coherencia entre UI, validacio i runtime
  - evolucionar `desempat` sense tocar `puntuacio`

## Principis De Disseny
- Principi 1: `puntuacio` es la font de score principal i no es modifica.
- Principi 2: un criteri de desempat ha de ser autoexplicatiu.
- Principi 3: el runtime ha de compartir primitives amb `puntuacio`.
- Principi 4: la UI del desempat ha de copiar el llenguatge visual i els blocs mentals de `puntuacio`.
- Principi 5: no hi ha herencia implicita com a model base del nou sistema.
- Principi 6: la compatibilitat legacy s'ha de resoldre a hydration i migracio, no al model nou.
- Principi 7: el pipeline del desempat ha de produir sempre un unic escalar comparable.

## Disseny De Dades Objectiu

### Nou format canonico per a `schema.desempat[]`
- Cada criteri sera un objecte amb aquesta forma:

```json
{
  "id": "tie_1",
  "nom": "Millor execucio en finals",
  "ordre": "desc",
  "pipeline_version": 1,
  "pipeline": {
    "aparells": { "mode": "seleccionar", "ids": [12, 13] },
    "camps_per_aparell": {
      "12": ["E_total"],
      "13": ["E_total"]
    },
    "agregacio_camps_per_aparell": {
      "12": "sum",
      "13": "sum"
    },
    "agregacio_camps": "sum",
    "candidate_source_mode": "raw_exercise",
    "candidate_source_cfg": {
      "mode": "tots",
      "best_n": 1,
      "index": 1,
      "ids": [],
      "agregacio_exercicis": "sum"
    },
    "candidate_source_per_aparell": {},
    "exercicis": {
      "mode": "millor_n",
      "best_n": 2,
      "index": 1,
      "ids": [],
      "max_per_participant": 0
    },
    "exercise_selection_scope": "per_member",
    "mode_seleccio_exercicis": "per_aparell_global",
    "exercicis_per_aparell": {},
    "agregacio_exercicis": "sum",
    "agregacio_aparells": "sum",
    "mode_resultat_aparells": "score",
    "ordre": "desc",
    "participants": { "mode": "tots", "n": 1 },
    "agregacio_participants": "sum"
  }
}
```

### Claus permeses dins de `desempat[].pipeline`
- S'admeten les claus de `puntuacio` necessaries per produir un escalar:
  - `aparells`
  - `camps_per_aparell`
  - `agregacio_camps_per_aparell`
  - `agregacio_camps`
  - `candidate_source_mode`
  - `candidate_source_cfg`
  - `candidate_source_per_aparell`
  - `exercicis`
  - `exercise_selection_scope`
  - `mode_seleccio_exercicis`
  - `exercicis_per_aparell`
  - `agregacio_exercicis`
  - `agregacio_aparells`
  - `mode_resultat_aparells`
  - `ordre`
  - `participants`
  - `agregacio_participants`

### Claus explicitament no permeses dins de `desempat[].pipeline`
- `victories`
- `desempat`
- `presentacio`
- `particions`
- `particions_v2`
- `particions_custom`
- `filtres`
- `equips`

### Raons de les exclusions
- `victories` obre una segona capa de comparacio dins d'un comparador i complica massa la primera versio.
- `desempat` dins `desempat` crea recursivitat i dificulta la comprensio.
- `presentacio`, `particions` i `filtres` no formen part del calcul d'un escalar.
- `equips` es configuracio de nivell classificacio, no de criteri de desempat.

### Camps del node arrel del criteri
- `id`
  - identificador estable d'UI
  - string curt, unic dins la llista
- `nom`
  - etiqueta humana del criteri
  - opcional pero molt recomanada
- `ordre`
  - direccio de comparacio final del criteri
  - `asc` o `desc`
- `pipeline_version`
  - per permetre evolucions futures del contracte
- `pipeline`
  - objecte obligatori en el nou model

## Estrategia De Compatibilitat

### Principi
- El sistema ha de poder llegir configs antigues i noves durant la transicio.
- El sistema ha de desar en format nou quan l'usuari edita un criteri des del builder nou.

### Lectura
- Si `desempat[i].pipeline` existeix, el criteri es tracta com a nou format.
- Si no existeix, el criteri es tracta com a legacy.
- La hidratacio del builder convertira criteris legacy a una representacio UI comuna equivalent al nou model.

### Persistencia
- En guardar des del builder nou, qualsevol criteri editat es desara en nou format.
- Els criteris no tocats en JSON avancat poden mantenir-se fins que l'usuari els regravi, si es vol una migracio lazy.

### Migracio recomanada
- No fer una migracio massiva immediata de totes les classificacions existents.
- Fer migracio lazy a nivell de configuracio quan s'obre i es desa des del builder.
- Opcionalment, afegir una comanda de manteniment posterior per convertir configs guardades en lot.

## Arquitectura De Runtime Recomanada

### Objectiu arquitectonic
- Extreure del motor actual una primitive comuna capaç de calcular un escalar des d'un pipeline.
- Fer que `puntuacio` usi aquesta primitive per al score principal o, si no es pot en una primera fase, fer que `desempat.pipeline` usi les mateixes helpers internes sense duplicacio conceptual.

### Cami recomanat
- Introduir una capa nova a `competicions_trampoli/services/classificacions/`.
- No escriure el nou runtime directament dins del template ni dins del view.

### Peces noves recomanades
- Nou modul: `competicions_trampoli/services/classificacions/pipeline_runtime.py`
- Nou modul: `competicions_trampoli/services/classificacions/pipeline_validation.py`
- Nou modul opcional: `competicions_trampoli/services/classificacions/pipeline_builder.py`

### API interna recomanada
- `normalize_scoring_pipeline(raw_pipeline, *, tipus, team_mode, strict=False) -> dict`
- `validate_scoring_pipeline(competicio, pipeline, *, tipus, team_mode, context_code="") -> list[str]`
- `compute_metric_from_pipeline(runtime_ctx, pipeline, subject) -> float`
- `build_pipeline_runtime_context(competicio, cfg_obj, schema_local, *, tipus) -> dict`

### Quina responsabilitat te cada helper
- `normalize_scoring_pipeline`
  - aplica defaults segurs
  - normalitza enums
  - neteja formes legacy minimes del pipeline
- `validate_scoring_pipeline`
  - comprova coherencia del pipeline en funcio de `tipus` i `team_mode`
  - valida aparells, camps, exercicis i restriccions d'equip
- `build_pipeline_runtime_context`
  - construeix caches, notes, aparells, mapes i seleccions compartides
  - evita recomputar el mateix per cada criteri
- `compute_metric_from_pipeline`
  - calcula un escalar per un subjecte concret
  - subjecte pot ser:
    - participant individual
    - entitat
    - equip derivat
    - equip natiu

### Regla de no regressio
- `compute_classificacio` pot continuar sent el punt d'entrada public.
- El refactor intern no ha de canviar resultats de `puntuacio`.
- Si cal, primer es crea la capa comuna i es consumeix nomes des de `desempat`.
- Quan estigui verificada, es pot plantejar una segona fase interna per fer que la puntuacio principal tambe hi passi, pero no forma part de l'abast obligatori d'aquest pla.

## Disseny De Runtime Per Al Desempat Nou

### Com ha de funcionar
- Per a cada fila ja classificada per `puntuacio`, el runtime calcula:
  - `score_principal`
  - `tie_values[]`
- Cada `tie_values[i]` surt de `compute_metric_from_pipeline(..., desempat[i].pipeline, subjecte_actual)`.
- La comparacio final fa servir:
  - score principal
  - tie value 1
  - tie value 2
  - etc.

### Subjecte del calcul
- En classificacio individual, el subjecte es la inscripcio.
- En classificacio per equips derivats, el subjecte es el grup de membres resolt.
- En classificacio per equips natius, el subjecte es l'equip.
- En classificacio per entitat, el subjecte es l'entitat agrupada.

### Notes importants
- El pipeline de desempat no ha de dependre de `puntuacio` per res implicit.
- Si l'usuari vol exactament el mateix que la puntuacio, el builder li podra oferir un clon inicial de la puntuacio principal.
- El runtime no ha de "copiar mentalment" defaults des de la puntuacio principal.

## Fases D'Implementacio

## Fase 0. Preparacio I Inventari
- Objectiu
  - Enumerar tots els punts del sistema on `desempat` es llegeix, es valida, es desa o es renderitza.
- Tasques
  - Inventariar helpers legacy que avui calculen criteris de desempat.
  - Inventariar proves actuals de `test_classificacions.py` i `test_team_scoring.py`.
  - Documentar quins casos de `desempat` actuals s'han de preservar via compatibilitat.
- Definition of done
  - Hi ha un mapa clar de fitxers tocats.

## Fase 1. Contracte De Dades I Normalitzacio
- Objectiu
  - Introduir el contracte `desempat[].pipeline`.
- Fitxers principals
  - `competicions_trampoli/services/classificacions/builder.py`
  - `competicions_trampoli/services/classificacions/runtime.py`
  - `competicions_trampoli/services/classificacions/validation.py`
- Tasques
  - Definir un normalitzador de pipeline reutilitzable.
  - Permetre que `prepare_schema_for_builder_hydration` converteixi criteris legacy a UI nova.
  - Permetre que `prepare_schema_for_persistence` guardi el nou format.
  - Introduir `pipeline_version`.
- Decisions
  - `ordre` ha d'estar al node arrel del criteri.
  - `pipeline.ordre` es pot admetre internament si ja existeix al subset de puntuacio, pero l'ordre efectiu del criteri ha de ser el del node arrel per evitar ambiguitat.
- Definition of done
  - El builder pot llegir i escriure `desempat[].pipeline`.

## Fase 2. Validacio Del Nou Pipeline
- Objectiu
  - Validar `desempat[].pipeline` com una mini puntuacio sense herencia implicita.
- Fitxers principals
  - `competicions_trampoli/services/classificacions/validation.py`
  - `competicions_trampoli/services/classificacions/pipeline_validation.py`
- Tasques
  - Reaprofitar al maxim la validacio de `puntuacio`.
  - Separar validacions "de calcul escalar" de validacions "de ranking principal".
  - Prohibir claus no permeses.
  - Validar `participants` i `agregacio_participants` nomes quan el `tipus` ho permet.
  - Mantenir restriccions actuals d'equips derivats i `team_pool`.
- Regles concretes
  - `mode_resultat_aparells` nomes permetra `score` en v1 robusta.
  - `victories` dins del pipeline del desempat retornara error.
  - `exercise_selection_scope` no pot dependre de `Hereta`.
  - `aparells.mode` admetra nomes formes explicites.
- Definition of done
  - Un pipeline invalid dona errors precisos amb path complet.

## Fase 3. Runtime Compartit
- Objectiu
  - Crear una primitive comuna per calcular un escalar a partir d'un pipeline.
- Fitxers principals
  - `competicions_trampoli/services/legacy/services_classificacions_2.py`
  - `competicions_trampoli/services/classificacions/pipeline_runtime.py`
- Tasques
  - Aillar les parts del motor actual que fan:
    - resolucio d'aparells objectiu
    - resolucio de camps per aparell
    - construccio de candidate rows
    - seleccio d'exercicis
    - agregacio de camps
    - agregacio d'exercicis
    - agregacio d'aparells
    - seleccio/aggregacio de participants
  - Construir un `runtime_ctx` compartit amb caches.
  - Afegir adaptadors per:
    - individual
    - equips derivats
    - equips natius
    - entitat
- Regla de seguretat
  - No canviar el resultat de `puntuacio` mentre s'extreu aquesta capa.
- Definition of done
  - Es pot calcular un valor de desempat nou a partir d'un pipeline complet sense heretar res de `puntuacio`.

## Fase 4. Integracio Amb El Ranking
- Objectiu
  - Fer que `_rank_v2` o el seu equivalent consumeixi `desempat[].pipeline`.
- Fitxers principals
  - `competicions_trampoli/services/legacy/services_classificacions_2.py`
- Tasques
  - Mantenir suport legacy.
  - Si el criteri te `pipeline`, usar el runtime nou.
  - Si el criteri es legacy, mantenir el cami antic.
  - Afegir cache de `tie_value` per evitar recalculs redundants.
- Definition of done
  - El ranking accepta criteris nous i antics.

## Fase 5. Builder UI I UX
- Objectiu
  - Donar al desempat una UX equiparable a `puntuacio`, sense tocar `puntuacio`.
- Fitxers principals
  - `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`
  - opcionalment helpers JS nous dins el mateix fitxer o parcials nous si la mida ho demana
- Disseny UX recomanat
  - Cada criteri de desempat es representa com una card expandible.
  - Cada card te:
    - nom del criteri
    - ordre
    - resum del pipeline
    - boto per expandir
    - boto per duplicar
    - boto per eliminar
  - Dins de la card expandida hi ha blocs visuals quasi iguals als de `puntuacio`:
    - aparells
    - camps per aparell
    - agregacio de camps
    - candidate source
    - criteri de seleccio d'exercicis
    - agregacio d'exercicis
    - agregacio d'aparells
    - participants, si aplica
- Accions UX obligatories
  - `Afegir criteri buit`
  - `Crear des de puntuacio actual`
  - `Duplicar criteri`
  - `Restablir criteri`
  - `Resumir criteri`
- Regla UX clau
  - El builder no ha de mostrar `Hereta` com a eix conceptual del model nou.
  - Si cal suportar criteris legacy hidratas, s'han de materialitzar en camps explicits.

## Fase 6. Reutilitzacio De Components D'UI
- Objectiu
  - Evitar copiar i divergir la UI de `puntuacio`.
- Estrategia recomanada
  - Extreure helpers de render de `puntuacio` a funcions reutilitzables.
  - No tocar el comportament de la seccio de `puntuacio`.
  - Reutilitzar:
    - construccio d'opcions d'aparells
    - selectors de camps per aparell
    - selectors d'agregacio
    - targetes de tractament d'exercicis
    - candidate source
    - participants
- Regla important
  - Primer extreure helpers purs.
  - Despres muntar la UI del desempat a sobre.
  - No refactoritzar visualment `puntuacio` mes del necessari.

## Fase 7. Hydration I Edicio Advanced JSON
- Objectiu
  - Fer que el builder visual i el JSON avancat siguin equivalents.
- Tasques
  - El `readTieUI()` ha de construir el nou schema.
  - El `renderTieUI()` ha de saber llegir el nou schema.
  - El mode advanced JSON ha de persistir `pipeline`.
  - Si entra un criteri legacy, hydration el converteix a la representacio visual nova.
- Definition of done
  - No hi ha perdua d'informacio en anar de JSON a UI i de UI a JSON.

## Fase 8. Runtime, Preview, Export I Live
- Objectiu
  - Garantir que totes les vies de render comparteixen el mateix resultat.
- Fitxers principals
  - `competicions_trampoli/services/classificacions/runtime.py`
  - `competicions_trampoli/services/classificacions/live.py`
  - `competicions_trampoli/views/classificacions/export.py`
- Tasques
  - Verificar que preview, live i export usen el mateix runtime.
  - Verificar que els criteris de desempat nous es reflecteixen al ranking en tots els modes.
- Definition of done
  - Mateix ordre a preview, live i export.

## Disseny UI/UX Detallat

### Estructura visual de la seccio `Desempat`
- Cabecera general
  - titol
  - text curt explicant que cada criteri calcula un valor independent
  - ajuda contextual
- Toolbar
  - `+ Afegir criteri`
  - `+ Crear des de puntuacio`
  - `Expandir tot`
  - `Col.lapsar tot`
- Llista de cards
  - una card per criteri

### Layout d'una card de criteri
- Capcalera
  - nom editable
  - resum curt
  - selector `ordre`
  - accions
- Cos
  - bloc `Aparells`
  - bloc `Camps`
  - bloc `Agregacio de camps`
  - bloc `Candidate source`
  - bloc `Seleccio d'exercicis`
  - bloc `Agregacio d'exercicis`
  - bloc `Agregacio d'aparells`
  - bloc `Participants`

### Resum curt del criteri
- Exemple de resum:
  - `TR + DMT | E_total | millors 2 | suma per aparell | suma final`
- El resum s'ha de regenerar en viu.
- Si el criteri esta invalid, el resum ho ha d'indicar amb un estat visual clar.

### UX de clonacio desde `puntuacio`
- Quan l'usuari prem `Crear des de puntuacio actual`:
  - es crea un criteri nou
  - el seu `pipeline` es una copia materialitzada de `schema.puntuacio`, reduida al subset permes
  - el nom inicial pot ser `Desempat basat en puntuacio`
  - l'usuari despres el modifica
- Aquesta accio es clau per evitar frustracio i configuracio repetitiva.

### UX d'errors
- Els errors s'han de mostrar:
  - a nivell de criteri
  - a nivell de bloc
  - a nivell de camp si es possible
- El text d'error ha d'usar el llenguatge del builder, no el nom intern cru de claus si es pot evitar.

### UX de compatibilitat legacy
- Si s'hidrata un criteri antic:
  - mostrar una etiqueta `criteri migrat`
  - el builder mostra la forma nova equivalent
  - no mostrar el concepte `Hereta` com a opcio principal

## Pla De Validacio Funcional

### Casos individuals
- Desempat amb pipeline equivalent a puntuacio, clonat i sense canvis.
- Desempat que usa nomes un aparell.
- Desempat que canvia camps pero manté la resta.
- Desempat que canvia seleccio d'exercicis.
- Desempat amb ordre `asc`.

### Casos d'equips derivats
- `per_member`
- `team_pool`
- limits `max_per_participant`
- seleccio de participants
- agregacio de participants

### Casos d'equips natius
- camps d'equip
- candidate source `team_aggregate` si ja es valid a puntuacio i aplica al subset admès
- sense reintroduir `victories` dins de desempat

### Casos d'entitat
- agregacio d'entitat amb criteri propi
- tie values consistents amb el ranking final

### Casos de compatibilitat
- schema antic es renderitza i es pot desar en schema nou
- schema antic continua computant igual si no s'edita
- schema nou no es degrada a format antic

## Pla De Proves

### Proves unitàries
- normalitzacio de `desempat[].pipeline`
- validacio de claus no permeses
- restriccions per `tipus`
- errors precisos per paths

### Proves de runtime
- mateix resultat que abans per configs antigues
- calcul correcte de tie value per pipeline nou
- casos amb aparell unic i multiparell
- casos amb `global_pool`
- casos amb equips derivats i natius

### Proves de builder/hydration
- render del nou contracte
- lectura UI -> schema
- schema -> UI -> schema sense perdua
- clonacio des de `puntuacio`

### Proves de regressio
- `puntuacio` no canvia resultat
- `puntuacio` no canvia schema
- live, preview i export mantenen consistencia

## Ordre Recomanat D'Execucio Per A L'Agent
1. Implementar el contracte nou i la seva normalitzacio.
2. Implementar la validacio del pipeline.
3. Construir el runtime compartit per calcular un escalar.
4. Integrar el runtime nou al ranking de `desempat`.
5. Implementar hydration del builder per al nou format.
6. Implementar la UI nova de cards de desempat.
7. Afegir clonacio des de `puntuacio`.
8. Cobrir compatibilitat legacy.
9. Tancar proves de regressio.

## Criteris D'Acceptacio Finals
- Es pot definir un criteri de desempat amb pipeline complet sense dependre implicitament de `puntuacio`.
- La UX del desempat es comparable a la de `puntuacio`.
- `puntuacio` no ha canviat de comportament.
- Configs antigues continuen funcionant.
- Configs noves es guarden en el nou format.
- El runtime de desempat fa servir el mateix model de calcul que la puntuacio, sense duplicacio incoherent.
- L'agent extern pot localitzar sense dubtes on tocar backend, runtime, validation, builder i tests.

## Notes Finals Per A Qui Ho Implementi
- No comencis per la UI.
- No intentis resoldre-ho només canviant `classificacions_builder_v2.html`.
- No barregis la migracio legacy amb la logica nova dins del runtime principal.
- No introdueixis `Hereta` com a eix del model nou.
- Si has de triar entre duplicar una mica de glue temporal o tocar `puntuacio`, tria glue temporal.
- Si el runtime compartit obliga a un refactor intern gran, fes-lo en passos petits i protegits per proves.

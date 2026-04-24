# Pla D'Implementacio De La Previsualitzacio De Geolocalitzacio I Clusters Per Subagents Paral.lels

## Objectiu
- Afegir una previsualitzacio prèvia al run de designacions que permeti veure les escoles/seus processades pel fitxer de partits, el resultat de la geocodificacio, la clusteritzacio geografica i l'impacte de diferents radis i opcions relacionades.
- Fer-ho de manera coherent amb el pipeline real del motor, evitant discrepancies entre "el que es veu al preview" i "el que despres usa el run".
- Preparar una arquitectura modular sota `designacions/clusteritzacio/` que separi:
  - preparacio de dades
  - geocodificacio
  - clusteritzacio
  - metriques i comptadors
  - renderitzat del mapa
  - futures regles manuals o overrides
- Deixar el treball paquetitzat perque un agent coordinador pugui delegar parts independents a subagents sense que aquests necessitin coneixer tot el modul.

## Resultat Funcional Esperat
- Des de la pantalla de pujada de fitxers de designacions, l'usuari pot executar una previsualitzacio de geolocalitzacio i clusters abans del run definitiu.
- La previsualitzacio:
  - usa els mateixos fitxers i filtres que el run
  - processa escoles noves no existents encara a BD
  - geocodifica o reutilitza coordenades existents
  - mostra un mapa interactiu de seus i clusters
  - mostra comptadors i metriques operatives
  - permet comparar diverses opcions de radi de clusteritzacio
  - prepara el cami per a una fase posterior d'overrides manuals de clusters
- El preview no llança el motor d'assignacio.
- El preview no ha de canviar la logica funcional actual del run definitiu.

## Regla Mes Important
- El preview ha de reutilitzar el mateix cami de preparacio de dades que el run real fins just abans de l'assignacio.
- No es pot implementar una logica "simplificada" paral.lela que acabi divergint de la logica real de filtrat, construccio d'adreces i geocodificacio.

## Context Minim Per A Qualsevol Agent

### Entrades actuals del modul
- Vista de pujada:
  - `designacions/views.py`
  - funcio `upload_view`
- Formulari:
  - `designacions/templates/upload.html`
- Lectura i filtrat de dades del run:
  - `designacions/services/run_scope.py`
  - funcions `filter_run_dataframes` i `load_scoped_run_data`

### Geocodificacio i adreces
- Construccio i normalitzacio d'adreces:
  - `designacions/services/addressing.py`
- Geocodificacio i cache a BD:
  - `designacions/services/geocoding_db.py`
- Model master d'adreces:
  - `designacions/models.py`
  - model `Address`

### Clusteritzacio actual
- Implementacio actual barrejada:
  - `designacions/geolocate.py`
  - funcions `clusteritza_i_plota` i `mapa_clusters_interactiu`
- Integracio al motor:
  - `designacions/main_fixed.py`
  - bloc d'adreces, geocodificacio i clusteritzacio

### Persistencia per run
- Model:
  - `designacions/models.py`
  - model `AddressCluster`
- Reparacio i reconstruccio:
  - `designacions/management/commands/repair_designacions_geodata.py`

### Mapa actual existent
- Mapa del run final:
  - `designacions/services/map_rebuild.py`
  - `designacions/views.py`
  - endpoint `run_map_view`
- Aquest mapa es d'assignacions finals, no de clusters base.

## Situacio Actual I Limitacions

### Limitacio 1. No hi ha preview real
- Actualment l'usuari pot configurar `cluster_eps_m` al formulari del run.
- No pot veure l'impacte d'aquest radi abans d'executar el run.
- El feedback arriba massa tard.

### Limitacio 2. El mapa visible avui no es el mapa de clusters
- El mapa servit al run mostra assignacions finals i estat de seus.
- No mostra el mapa base sobre el qual s'ha pres la clusteritzacio.

### Limitacio 3. La clusteritzacio esta acoblada al motor
- `main_fixed.py` combina:
  - preparacio de dades
  - geocodificacio
  - clusteritzacio
  - construccio de subgrups
  - assignacio
  - persistencia
  - mapes
- Aixo dificulta crear un preview net i reutilitzable.

### Limitacio 4. El mateix parametre participa en dues capes
- Avui `max_partits_subgrup` es passa tambe a `clusteritza_i_plota` com `max_punts_per_subcluster`.
- Aixo barreja:
  - cluster geografic
  - particio operativa del motor
- La primera implementacio del preview ha de fer visible aquesta realitat, pero no cal resoldre-la tota en la mateixa fase.

## Principis D'Arquitectura Del Preview

### Principi 1. Reutilitzar el pipeline real
- El preview ha d'executar:
  - lectura de fitxers
  - filtres de modalitat i dates
  - construccio d'adreces
  - resolucio d'`Address`
  - geocodificacio pendent
  - clusteritzacio
- I s'ha d'aturar just abans de l'assignacio del motor.

### Principi 2. Separar calcul pur de UI i persistencia
- Cal crear un paquet nou:
  - `designacions/clusteritzacio/`
- Aquest paquet no ha de dependre del HTML ni de la vista.
- La UI ha de consumir estructures de dades clares i serialitzables.

### Principi 3. Fer el preview incremental
- La geocodificacio es la part lenta.
- Un cop tenim coordenades, recalcular clusters per diversos radis ha de ser rapid.
- Per tant, el disseny ha de distingir:
  - preparacio de punts geocodificats
  - re-clusteritzacio sobre punts ja preparats

### Principi 4. Preparar la fase d'overrides manuals
- Encara que en la primera entrega no s'implementin overrides, el model del preview ha de permetre:
  - forcar un cluster manual
  - fusionar punts
  - separar punts
- No s'ha de tancar el disseny a una UI que impedeixi aquesta evolucio.

## Abast De La Primera Entrega
- Crear un preview funcional des de la pujada de fitxers.
- Permetre executar el preview amb els mateixos filtres del run.
- Mostrar:
  - mapa interactiu de seus i clusters
  - escoles sense geocodificacio
  - outliers
  - comptadors agregats
  - comparativa de diversos radis
  - metriques operatives basiques
- No incloure encara:
  - edicio manual de clusters
  - drag and drop sobre el mapa
  - persistencia d'overrides
  - simulacio completa d'assignacio per cada radi

## Estructura Objectiu

```text
designacions/
  clusteritzacio/
    __init__.py
    preview_service.py
    engine.py
    metrics.py
    maps.py
    selectors.py
    persistence.py
    contracts.py
    serializers.py

  templates/
    cluster_preview.html
    cluster_preview_partial.html

  docs/
    plan_previsualitzacio_geolocalitzacio_clusters_subagents.md
```

## Responsabilitat De Cada Modul Nou

### `clusteritzacio/contracts.py`
- Dataclasses o estructures clares per al preview.
- Ha de definir contractes com:
  - `PreviewInput`
  - `PreviewAddressPoint`
  - `PreviewClusterResult`
  - `PreviewMetrics`
  - `PreviewScenario`
- Aquesta capa es la font de veritat per a la resta del paquet.

### `clusteritzacio/preview_service.py`
- Orquestra el pipeline del preview.
- Rep fitxers o paths temporals i params.
- Crida:
  - `run_scope`
  - `addressing`
  - `geocoding_db`
  - `engine`
  - `metrics`
  - `maps`
- Retorna un objecte de preview complet, no HTML.

### `clusteritzacio/engine.py`
- Clusteritzacio geografica pura.
- No ha de fer `render`.
- No ha de fer `save` a disc.
- Hauria d'admetre:
  - un radi concret
  - una llista de radis
  - opcio de no trencar en subclusters operatius en la primera fase del calcul geografic pur

### `clusteritzacio/metrics.py`
- Calcula metriques per pantalla i per comparativa.
- Ha de donar:
  - `total_points`
  - `geocoded_points`
  - `missing_geocode_points`
  - `clustered_points`
  - `outlier_points`
  - `cluster_count`
  - `largest_cluster_size`
  - `singleton_cluster_count`
  - `cluster_size_distribution`
  - `estimated_base_subgroups`
  - `estimated_cross_cluster_transitions`
  - `estimated_unique_venues`
- Les metriques han de ser serialitzables i estables.

### `clusteritzacio/maps.py`
- Construeix el mapa interactiu de preview.
- Ha de poder renderitzar:
  - una vista d'un sol radi
  - una vista comparativa simple
- El mapa ha de diferenciar visualment:
  - clustered
  - outlier
  - missing geocode
  - punts nous geocodificats durant la preparacio

### `clusteritzacio/selectors.py`
- Gestiona l'exploracio de radis.
- Ha de permetre executar escenaris tipus:
  - `300, 400, 500, 650, 800`
- Pot incloure una heuristica simple de recomanacio basada en:
  - menys outliers
  - menys fragmentacio extrema
  - mida maxima de cluster raonable
  - millor estimacio operativa de subgrups

### `clusteritzacio/persistence.py`
- Primera fase:
  - lectura i eventual persistencia auxiliar del preview si es necessita
- Segona fase:
  - persistencia d'overrides manuals
- La primera implementacio pot no crear models nous si el preview pot viure com a resultat efimer o job temporal.

### `clusteritzacio/serializers.py`
- Adapta els contractes interns a JSON per a la UI.
- Important per desacoblar:
  - estructures Python internes
  - payloads HTTP

## Flux Funcional Del Preview

### Flux D'Usuari
1. L'usuari puja els dos fitxers a `upload.html`.
2. Selecciona:
   - modalitats
   - interval de dates
   - fase si aplica
   - radi base o mode comparatiu
3. Prem `Previsualitzar escoles i clusters`.
4. El backend crea un job de preview.
5. El job:
   - filtra dades
   - construeix adreces
   - geocodifica si cal
   - calcula escenaris de clusters
   - genera metriques i mapa
6. La UI mostra:
   - resum general
   - incidencies de geocodificacio
   - mapa
   - comparativa de radis
   - recomanacio o seleccio final
7. L'usuari decideix:
   - tornar a previsualitzar amb altres opcions
   - executar el run definitiu amb el radi triat

### Flux Tecnologic
1. `upload_view` o nova vista germana rep fitxers i params.
2. Guarda fitxers temporals igual que el run.
3. Crida `filter_run_dataframes`.
4. Genera `adreca` a partir de `Domicili` i `Municipi`.
5. Resol o geocodifica `Address`.
6. Construeix un DataFrame o llista de punts:
   - `address_id`
   - `adreca`
   - `lat`
   - `lon`
   - `municipality`
   - `source_status`
7. Executa clusteritzacio per un o diversos radis.
8. Calcula metriques.
9. Renderitza mapa i payload JSON.
10. Retorna una pantalla HTML o endpoint JSON consumit per la mateixa pantalla.

## Opcions De Previsualitzacio A Implementar

### Opcio 1. Preview Simple
- Un sol radi `cluster_eps_m`.
- Mostra:
  - mapa
  - comptadors
  - llistat d'incidencies

### Opcio 2. Preview Comparatiu De Radis
- Radi base + radi alternatives.
- Exemple per defecte:
  - `300`
  - `400`
  - `500`
  - `650`
  - `800`
- Mostra una taula comparativa de metriques.
- Permet seleccionar quin radi es vol portar al run.

### Opcio 3. Focus En Incidencies
- Filtre visual sobre:
  - nomes missing geocode
  - nomes outliers
  - nomes clusters d'un sol punt
  - nomes clusters grans

### Opcio 4. Vista Per Seu / Adreca
- Taula amb:
  - adreca
  - municipi
  - lat/lon
  - estat geocodificacio
  - cluster
  - nombre de partits associats
  - modalitats associades

## Comptadors I Metriques Obligatoris

### Comptadors Globals
- `total_matches`
- `total_unique_addresses`
- `total_geocoded_addresses`
- `total_missing_geocode_addresses`
- `total_clustered_addresses`
- `total_outlier_addresses`
- `total_clusters`

### Comptadors Operatius
- `total_unique_venues`
- `total_matches_with_cluster`
- `total_matches_without_cluster`
- `estimated_base_subgroups`
- `estimated_subgroups_same_cluster`
- `estimated_subgroups_cross_cluster_candidate`

### Metriques De Distribucio
- `largest_cluster_size`
- `average_cluster_size`
- `median_cluster_size`
- `singleton_cluster_count`
- `clusters_over_threshold_count`
- `outlier_ratio`

### Metriques De Qualitat Del Radi
- `score_outlier_penalty`
- `score_fragmentation_penalty`
- `score_oversized_cluster_penalty`
- `score_operational_balance`
- `scenario_score_total`

### Llistats D'Incidencies
- adreces sense coordenades
- adreces outlier
- clusters massa grans
- punts que pertanyen a municipis diferents dins del mateix cluster
- seus amb noms similars que podrien ser la mateixa escola i estan separades

## Heuristica Inicial Recomanada Per Al Selector De Radi
- Penalitzar fort:
  - molts outliers
  - clusters d'un sol punt en excés
  - clusters massa grans
- Penalitzar moderat:
  - distribucio molt irregular de mides
- Valorar positivament:
  - mida de cluster moderada
  - menys outliers
  - menys fragmentacio operativa aparent

## Elements De UI A Construir

### A La Pantalla De Pujada
- boto nou:
  - `Previsualitzar escoles i clusters`
- toggle:
  - `Comparar diversos radis`
- camp opcional:
  - `Radis a comparar`

### A La Pantalla De Preview
- capcalera amb resum:
  - fitxers
  - filtres
  - radi seleccionat
- targetes de comptadors
- bloc de geocodificacio
- bloc de comparativa de radis
- mapa interactiu
- taula de seus
- CTA final:
  - `Fer servir aquest radi i executar run`
  - `Tornar a configurar`

## Contracte De No Regressio
- No es pot trencar:
  - `upload_view`
  - l'execucio normal del run
  - el mapa final del run
  - la persistencia d'`Address`
  - la persistencia d'`AddressCluster` per run
- El preview no ha d'introduir canvis de comportament al motor mentre no s'activi explicitament el run.

## Decisions D'Arquitectura Recomanades

### Decisio 1. Crear una vista especifica de preview
- No reaprofitar `run_detail_view`.
- Crear noves rutes dedicades.
- Motiu:
  - el preview es pre-run
  - les seves necessitats de UI i estat son diferents

### Decisio 2. Reutilitzar la infraestructura de jobs
- Si es pot, fer servir el mateix patro de `task_id` i logs.
- Motiu:
  - coherencia amb el modul
  - la geocodificacio pot trigar

### Decisio 3. Guardar la geocodificacio a `Address`
- El preview si que pot actualitzar el master `Address`, perquè aquesta es una cache de coneixement geografic util.
- Això no es considera una mutacio funcional del run, sino una preparacio de dades.

### Decisio 4. No persistir encara un "preview model" si no cal
- La primera entrega pot ser:
  - job temporal
  - HTML guardat temporalment
  - payload JSON en jobstore
- Si el volum o la UX ho demana, es pot crear despres un model `ClusterPreviewRun`.

## Endpoints Recomanats

### Fase 1
- `POST /designacions/cluster-preview/`
  - crea el job de preview
- `GET /designacions/cluster-preview/<preview_id>/`
  - mostra la pantalla de preview
- `GET /designacions/cluster-preview/<preview_id>/status/`
  - estat del job
- `GET /designacions/cluster-preview/<preview_id>/map/`
  - retorna HTML del mapa

### Fase 2
- `POST /designacions/cluster-preview/<preview_id>/recluster/`
  - recalcula clusters sobre punts ja geocodificats
- `POST /designacions/cluster-preview/<preview_id>/commit-to-run/`
  - llança el run definitiu amb els params triats

### Fase 3
- `POST /designacions/cluster-preview/<preview_id>/overrides/`
  - crea o actualitza overrides manuals

## Ordre De Fases Recomanat

### Fase 0. Preparacio Arquitectonica
- Crear `designacions/docs/`
- Crear `designacions/clusteritzacio/`
- Definir contractes i write scopes
- No tocar encara la UI final

### Fase 1. Calcul Pur
- extreure la logica de preview a `clusteritzacio/preview_service.py`
- extreure clusteritzacio a `clusteritzacio/engine.py`
- extreure metriques a `clusteritzacio/metrics.py`
- afegir tests de calcul pur

### Fase 2. Endpoint I Job
- afegir task de preview
- afegir endpoint de creacio i estat
- afegir jobstore/logs

### Fase 3. UI Inicial
- afegir boto al formulari
- afegir plantilla de preview
- mostrar comptadors i mapa

### Fase 4. Comparativa De Radis
- selector de radi
- taula comparativa
- recomanacio heuristica

### Fase 5. Enduriment I Observabilitat
- millorar missatges d'incidencia
- millorar tests
- validar rendiment

### Fase 6. Fase Posterior D'Overrrides Manuals
- fora de l'abast inicial

## Paquets De Treball Per A Subagents

## Regles Generals Per A Tots Els Subagents
- Cada subagent ha de treballar en el seu write scope exclusiu.
- No ha d'assumir context extern fora del que s'indica en aquest document.
- No ha de refactoritzar altres parts del modul fora del seu abast.
- Si detecta dependències bloquejants, les ha de documentar clarament al coordinador.

### Worker 1. Contractes I Calcul Pur
**Write scope**
- `designacions/clusteritzacio/contracts.py`
- `designacions/clusteritzacio/engine.py`
- `designacions/clusteritzacio/metrics.py`
- tests nous associats

**Objectiu**
- Definir structs clars i calculs purs per clusteritzacio i metriques.

**Entrades conegudes**
- `designacions/geolocate.py`
- `designacions/main_fixed.py`
- `designacions/services/run_scope.py`

**No tocar**
- `views.py`
- `templates/`
- `tasks.py`

**Done criteria**
- Existeix API Python estable per:
  - clusteritzar punts
  - calcular metriques per escenari
  - comparar radis

### Worker 2. Orquestracio Del Preview
**Write scope**
- `designacions/clusteritzacio/preview_service.py`
- `designacions/clusteritzacio/serializers.py`
- tests nous associats

**Objectiu**
- Construir el pipeline de preview reutilitzant filtrat i geocodificacio reals.

**Entrades conegudes**
- `designacions/services/run_scope.py`
- `designacions/services/addressing.py`
- `designacions/services/geocoding_db.py`
- API definida per Worker 1

**No tocar**
- plantilles
- JS

**Done criteria**
- Donat un conjunt de fitxers i params, es pot obtenir un objecte de preview complet i serialitzable.

### Worker 3. Backend HTTP I Tasks
**Write scope**
- `designacions/views.py`
- `designacions/urls.py`
- `designacions/tasks.py`
- eventualment `designacions/services/jobstore.py` si cal ampliar-lo
- tests backend associats

**Objectiu**
- Exposar el preview com a job asíncron i endpoint usable per la UI.

**Entrades conegudes**
- infraestructura de jobs actual del modul
- API definida per Worker 2

**No tocar**
- calcul intern de clusteritzacio
- plantilla principal del mapa si no es estrictament necessari

**Done criteria**
- Es pot crear i consultar un preview via HTTP sense executar el run.

### Worker 4. Render Del Mapa
**Write scope**
- `designacions/clusteritzacio/maps.py`
- tests o helpers associats

**Objectiu**
- Construir el mapa interactiu de preview.

**Entrades conegudes**
- implementacions actuals a `geolocate.py` i mapa final de `main_fixed.py`
- API de Worker 2

**No tocar**
- vistes
- formulari del run

**Done criteria**
- El mapa representa correctament:
  - clustered
  - outlier
  - missing geocode
  - escenari seleccionat

### Worker 5. UI Del Formulari I Pantalla De Preview
**Write scope**
- `designacions/templates/upload.html`
- `designacions/templates/cluster_preview.html`
- `designacions/templates/cluster_preview_partial.html`
- JS inline necessari
- tests UI/backend smoke associats

**Objectiu**
- Afegir UX de preview al modul sense trencar el run actual.

**Entrades conegudes**
- endpoints de Worker 3
- payloads de Worker 2

**No tocar**
- logica de calcul intern

**Done criteria**
- L'usuari pot llançar preview, veure comptadors, comparar radis i anar cap al run.

### Worker 6. Testing I Integracio
**Write scope**
- `designacions/tests.py`
- nous fitxers de test si el coordinador decideix fragmentar-los

**Objectiu**
- Cobrir la integracio i estabilitzar contractes.

**Entrades conegudes**
- tot el flux implementat

**Done criteria**
- Hi ha cobertura minima de:
  - filtrat
  - geocodificacio
  - clusteritzacio
  - endpoint preview
  - render basica UI

## Sequencia Recomanada D'Orquestracio

### Etapa A. En Paral.lel
- Worker 1
- Worker 2
- Worker 4

### Etapa B. Quan A i B estiguin estabilitzats
- Worker 3

### Etapa C. Quan els endpoints existeixin
- Worker 5

### Etapa D. Al final
- Worker 6

## Dependències Entre Subagents
- Worker 2 depèn del contracte de Worker 1.
- Worker 3 depèn de Worker 2.
- Worker 5 depèn de Worker 3 i del payload estable serialitzat.
- Worker 6 depèn de tots.

## Punts Delicats Que El Coordinador Ha De Vigilar

### Punt Delicat 1. No duplicar la logica de filtrat
- Si un worker replica filtres manualment en lloc de cridar `run_scope`, hi haurà divergencies.

### Punt Delicat 2. No canviar la semantica actual del run
- El preview pot preparar dades i mostrar-les.
- No ha de alterar les assignacions ni canviar el contracte del run existent.

### Punt Delicat 3. No barrejar cluster geografic i segment operatiu si no es decideix explicitament
- En la primera entrega, les metriques poden exposar aquesta relacio.
- Pero l'API ha d'intentar mantenir-los separats conceptualment.

### Punt Delicat 4. Gestionar escoles noves del fitxer
- El preview ha de geocodificar les escoles que no existeixen encara.
- Aquest es un cas funcional central, no un edge case.

### Punt Delicat 5. Fer visible el cost de la geocodificacio
- Si el primer preview triga, la UI ho ha de comunicar.
- Els recalculs de radi posteriors han de ser més rapids.

## Validacio I Tests Obligatoris

### Tests De Calcul
- clusteritzacio amb punts geocodificats
- comparativa de radis
- calcul de metriques
- comptatge correcte d'outliers i missing geocode

### Tests De Pipeline
- el preview usa els mateixos filtres que el run
- escoles noves es geocodifiquen i entren al preview
- escoles existents reutilitzen `Address`

### Tests D'Endpoint
- crear preview
- consultar estat
- renderitzar preview
- renderitzar mapa

### Tests D'UI
- boto visible a `upload.html`
- bloc de comptadors visible
- comparativa de radis visible
- enllac o CTA cap al run definitiu

## Criteris D'Acceptacio Finals
- L'usuari pot veure un mapa de clusters abans del run.
- El preview processa les escoles reals del fitxer, incloses les noves.
- El preview mostra comptadors i metriques suficients per prendre decisions.
- El radi triat es pot traslladar de forma clara al run.
- L'arquitectura queda preparada per a una futura edicio manual de clusters.
- El run actual continua funcionant sense regressions.

## Fora D'Abast D'Aquest Pla
- Reescriure ara tot `main_fixed.py`
- resolver del tot la separacio entre clusters geografics i subgrups operatius
- fer l'editor manual de clusters
- refactoritzar tota la capa de mapes finals del run

## Recomanacio Final Per Al Coordinador
- Prioritzar una primera entrega on el preview sigui fiable i explicatiu, encara que la UI sigui austera.
- No introduir massa optimitzacions prematures.
- Bloquejar fort el contracte de dades del preview abans de repartir UI i backend.
- Posposar els overrides manuals fins que la previsualitzacio base estigui integrada i testejada.

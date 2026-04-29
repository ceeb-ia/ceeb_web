# Pla De Mobilitat Atomica I Tracking D'Assignacions Per Subagents

Data: 2026-04-29

Aquest document descriu dos canvis separats pero relacionats del motor de designacions:

1. Corregir la validacio de mobilitat perque treballi amb partits atomics ordenats, no amb segments agregats.
2. Afegir un motor de tracking d'assignacions que expliqui en quina fase i amb quina ruta s'ha assignat cada partit.

El document esta escrit perque un agent extern pugui orquestrar la implementacio amb subagents sense context previ de la conversa.

No es un document d'implementacio executada. Es una planificacio tecnica.

## Context Actual

El motor nou `phased_route_solver` viu principalment a:

```text
designacions/optimization/phase_runner.py
designacions/optimization/phase_solver.py
designacions/optimization/route_generation.py
designacions/optimization/rescue.py
designacions/optimization/state.py
designacions/optimization/diagnostics.py
designacions/main_fixed.py
```

El flux simplificat es:

1. `main_fixed.py` carrega partits i disponibilitats.
2. Es geocodifiquen adreces i es calculen clusters.
3. Es creen subgrups base.
4. El motor nou parteix subgrups en fragments de nivell.
5. `phase_runner.py` executa fases:
   - `high`
   - `partial_rescue:high`
   - `medium`
   - `general`
   - `final_rescue`
   - `new_route_rescue`
   - `individual_rescue:n`
6. Les rutes seleccionades es transformen en assignacions persistides.
7. El resum del run guarda diagnostics agregats, pero no una traça completa per assignacio.

## Problema 1: Mobilitat Validada Per Segments Agregats

### Símptoma

En alguns runs apareixen assignacions que el motor permet pero la validacio final detecta com a error de mobilitat.

Exemple real del run 139:

```text
Tutor 5368 F5, transport Moto

18:00  Maristes Sant Joan       cluster 43
20:00  SAFA Sant Andreu         outlier
21:00  Maristes Sant Joan       cluster 43

gap_diff_cluster_min = 100
gap_same_pitch_min = 60
```

El salt real conflictiu es:

```text
20:00 SAFA/outlier -> 21:00 Maristes/cluster 43
```

Aquest salt te 60 minuts i hauria de requerir 100 minuts, perque implica ubicacio no fiable i canvi de seu.

### Causa

La validacio interna de rutes compara segments agregats.

Si un segment conte dos partits:

```text
segment A = [18:00 Maristes, 20:00 SAFA]
segment B = [21:00 Maristes]
```

el codi compara els conjunts de seus:

```text
{Maristes, SAFA} intersect {Maristes} = {Maristes}
```

i classifica la transicio com a mateixa pista. Aixo aplica `gap_same_pitch_min` encara que cronologicament el darrer partit real del segment A sigui SAFA.

### Fitxers Amb Risc

```text
designacions/optimization/route_generation.py
designacions/optimization/rescue.py
designacions/optimization/package_generation.py
designacions/services/assignment_feasibility.py
```

Els punts mes sensibles son funcions equivalents a:

```python
_validate_gaps(...)
_required_gap(...)
_route_requires_vehicle(...)
_transition_requires_vehicle(...)
_segment_venues(...)
_segment_clusters(...)
```

`assignment_feasibility.py` ja treballa mes a prop del model atomic final, pero cal revisar que sigui coherent amb el nou helper compartit.

## Objectiu De Mobilitat Atomica

La mobilitat s'ha de validar sobre una sequencia ordenada de partits atomics:

```text
partit 1 -> partit 2 -> partit 3 -> ...
```

No sobre segments agregats.

Cada atom ha de contenir, com a minim:

```python
AtomicRoutePoint(
    match_id: str,
    start_dt: datetime | None,
    end_dt: datetime | None,
    venue: str,
    venue_id: str | None,
    cluster_id: str | None,
    cluster_status: str | None,
    source_segment_id: str | None,
)
```

Es pot implementar com a dataclass o com a dict intern, pero ha de tenir un contracte estable i tests.

## Regles Esperades

Per cada parella consecutiva d'atoms:

1. Mateixa seu real:
   - requerir `gap_same_pitch_min`.
2. Diferent seu, mateix cluster fiable:
   - requerir `gap_diff_pitch_min`.
   - generar warning informatiu de canvi de pista.
3. Diferent cluster fiable:
   - requerir `gap_diff_cluster_min`.
   - requerir vehicle.
   - si hi ha vehicle i gap suficient, warning informatiu.
4. Outlier, missing geocode, pending o cluster desconegut:
   - si es la mateixa seu real, permetre amb `gap_same_pitch_min` i warning.
   - si es seu diferent, tractar com a mobilitat incerta:
     - requerir vehicle.
     - requerir `gap_diff_cluster_min`.
     - si compleix, warning.
     - si no compleix, bloqueig.
5. Sense dades suficients:
   - mantenir fallback conservador.
   - no convertir silenciosament una transicio incerta en mateixa pista.

## Pla D'Implementacio Mobilitat Atomica

### Subagent A: Contracte Atomic Compartit

Responsabilitat:

- Crear un helper pur per expandir segments/rutes a atoms ordenats.
- El helper ha de funcionar amb dataclasses, dicts i objectes compatibles.

Fitxers candidats:

```text
designacions/optimization/route_points.py
designacions/optimization/contracts.py
```

Tasques:

1. Definir `AtomicRoutePoint`.
2. Implementar `route_points_from_segments(segments)`.
3. Implementar helpers:
   - `same_location(left, right)`
   - `transition_requires_vehicle(left, right)`
   - `required_gap(left, right, config)`
   - `validate_atomic_gaps(points, config)`
4. Fer fallback si un segment no te rows atomiques:
   - crear un atom equivalent al segment agregat.
   - marcar-lo com `source_is_aggregate=True` si cal.

Criteris d'acceptacio:

- Un segment amb rows `[Maristes 18:00, SAFA 20:00]` s'expandeix en dos atoms.
- La transicio `SAFA 20:00 -> Maristes 21:00` no es classifica com mateixa pista.

### Subagent B: Integracio A `route_generation.py`

Responsabilitat:

- Reemplaçar la validacio de gaps basada en segments agregats per la validacio atomica.

Fitxer:

```text
designacions/optimization/route_generation.py
```

Tasques:

1. Substituir `_validate_gaps(...)` per una versio que usa atoms.
2. Substituir `_route_requires_vehicle(...)` i `_transition_requires_vehicle(...)` o fer-los delegar al helper atomic.
3. Assegurar que `_score_route_candidate(...)` rep els warnings i bloquejos correctes.
4. Preservar el comportament per rutes simples d'un sol partit.

Criteris d'acceptacio:

- No es poden seleccionar rutes amb outlier/diferent seu i gap inferior a `gap_diff_cluster_min`.
- Rutes de mateixa pista continuen permetent `gap_same_pitch_min`.
- Rutes de mateix cluster i pista diferent continuen permetent `gap_diff_pitch_min`.

### Subagent C: Integracio A `rescue.py`

Responsabilitat:

- Aplicar la mateixa logica atomica a repesques.

Fitxer:

```text
designacions/optimization/rescue.py
```

Tasques:

1. Fer que `_score_direct_candidate(...)` validi la ruta completa atomica.
2. Revisar `run_partial_rescue`, `run_new_route_rescue` i `run_individual_rescue`.
3. Verificar que quan s'insereix un partit en una ruta existent es comproven totes les transicions atomiques resultants.

Criteris d'acceptacio:

- Cap repesca pot introduir el fals positiu del run 139.
- Els comptadors `gap_too_short`, `vehicle_required` i warnings continuen omplint-se.

### Subagent D: Revisio De `package_generation.py`

Responsabilitat:

- Verificar si el motor `package_solver` o rutes fusionades encara poden patir el mateix problema.

Fitxer:

```text
designacions/optimization/package_generation.py
```

Tasques:

1. Revisar `_can_route(...)`, `_required_gap(...)`, `_merge_route(...)`.
2. Aplicar el helper atomic si el package solver continua actiu.
3. Evitar divergencia de regles entre motors.

Criteris d'acceptacio:

- `legacy`, `package_solver` i `phased_route_solver` no tenen criteris contradictoris de mobilitat.

### Subagent E: Tests De Regressio

Responsabilitat:

- Afegir tests focalitzats i petits.

Fitxer:

```text
designacions/tests.py
```

Tests minims:

1. Segment agregat amb `A -> B`, seguit de `A`, no aplica gap de mateixa pista per al salt `B -> A`.
2. Outlier diferent seu amb vehicle i gap suficient dona warning.
3. Outlier diferent seu amb vehicle i gap insuficient bloqueja.
4. Outlier mateixa seu amb dos partits permet gap de mateixa pista i warning.
5. Sense vehicle i ubicacio incerta diferent seu bloqueja.
6. Insercio en ruta existent valida transicions abans i despres del nou partit.

Comandes suggerides:

```text
docker compose exec -T web python manage.py test designacions.tests.DesignacionsOptimizationPackageSolverTests --verbosity 1
docker compose exec -T web python manage.py test designacions.tests.DesignacionsDateAwareHelpersTests --verbosity 1
docker compose exec -T web python manage.py check
```

## Problema 2: Falta Tracking Persistent D'Assignacions

### Estat Actual

El model `Assignment` nomes desa:

```text
run
match
referee
locked
note
manual_override_warning
manual_override_reason
updated_at
```

El motor nou genera informacio de fase i ruta en memoria:

```text
phase_name
selected_routes
coverage_by_phase
phase_summaries
state.stage_records
```

Pero aquesta traça no queda persistida per assignacio.

Conseqüencia:

- Es pot saber agregadament quants partits venen de cada fase.
- No es pot saber facilment per cada partit:
  - en quina fase va entrar;
  - si era part d'una ruta;
  - amb quins altres partits anava;
  - si va ser inserit en una ruta existent;
  - quin candidat competia amb ell;
  - quins warnings tenia en el moment de seleccio.

## Objectiu Del Motor De Tracking

Disposar d'una traça persistent, consultable i exportable, que expliqui cada assignacio.

Preguntes que ha de poder respondre:

1. Aquest partit es va assignar a `high`, `medium`, `general` o repesca?
2. Era un partit individual o part d'una ruta?
3. Quins altres partits formaven la ruta?
4. La ruta es va inserir sobre una ruta ja existent del tutor?
5. Quin cost/score tenia el candidat seleccionat?
6. Quins warnings tenia?
7. Quins bloquejos principals van impedir altres candidats, si estan disponibles?
8. L'assignacio es manual, automatica o modificada despres?

## Millora De L'Explicacio Per A Usuari Final

L'usuari final no ha de necessitar coneixer el funcionament intern per fases, rutes, fragments o repesques. El tracking ha de servir com a font de dades per millorar l'`Explicacio` existent, no per exposar jargon intern sense traduir.

Peca existent:

```text
designacions/services/assignment_explainer.py
```

Actualment l'explicacio es centra en:

- compatibilitat horaria i operativa;
- encaix de nivell;
- cost/effective cost;
- possibles alternatives millors;
- avisos o bloquejos de la designacio actual.

Amb tracking, aquesta explicacio hauria d'afegir una capa narrativa d'origen de l'assignacio:

```text
Aquest tutor s'ha assignat perque encaixava amb l'horari, el nivell era compatible
i el partit formava part d'una sequencia viable de 3 partits el mateix dia.
La sequencia inclou canvis de seu, per aixo queda marcada per revisio.
```

No s'ha de mostrar per defecte:

```text
stage=individual_rescue:3
route_id=...
phase_name=general
```

S'ha de traduir a etiquetes comprensibles:

```text
Assignacio directa prioritaria
Assignacio en fase general
Assignacio recuperada automaticament
Assignacio afegida a una jornada que el tutor ja tenia
Part d'una sequencia de 3 partits
Revisio recomanada per canvi de seu
```

### Mapa De Traduccio Recomanat

El tracking pot conservar valors tecnics, pero la UI i l'explicacio han d'usar etiquetes humanes.

```text
high
  Etiqueta: Assignacio prioritaria
  Explicacio: El partit es va cobrir en la primera passada, reservada als partits de mes exigencia esportiva.

medium
  Etiqueta: Assignacio de nivell mitja/alt
  Explicacio: El partit es va cobrir quan el motor va ampliar tutors i partits compatibles.

general
  Etiqueta: Assignacio general
  Explicacio: El partit es va cobrir en la passada general, amb tots els tutors compatibles disponibles.

partial_rescue:*
  Etiqueta: Recuperacio parcial
  Explicacio: El partit venia d'un grup que no s'havia pogut assignar completament i es va recuperar per separat.

final_rescue
  Etiqueta: Recuperacio final
  Explicacio: El partit es va assignar en una passada final per aprofitar tutors i buits encara disponibles.

new_route_rescue
  Etiqueta: Nova sequencia recuperada
  Explicacio: El motor va formar una nova sequencia amb partits pendents i la va assignar a un tutor compatible.

individual_rescue:n
  Etiqueta: Recuperacio individual
  Explicacio: El partit es va assignar individualment en una passada de recuperacio.
```

### Explicacio De Ruta Sense Jargon

Si `route_size > 1`, l'explicacio ha de parlar de "sequencia" o "jornada del tutor", no de "ruta candidata" o "fragment".

Exemple:

```text
Aquest partit forma part d'una sequencia de 3 partits del mateix tutor:

18:00 Maristes Sant Joan
20:00 SAFA Sant Andreu
21:00 Maristes Sant Joan
```

Si `inserted_into_existing_route=True`:

```text
El partit es va afegir a una jornada que aquest tutor ja tenia assignada.
```

Si hi ha warnings:

```text
La designacio es viable, pero queda marcada per revisio per canvi de seu.
```

Si hi ha outlier o missing geocode:

```text
Una de les seus no te ubicacio geografica fiable. El sistema ha aplicat criteris conservadors i ho deixa per revisio.
```

Si hi ha error:

```text
La designacio incompleix una regla de mobilitat: el temps entre seus es inferior al minim configurat.
```

### Integracio Amb L'Explicacio Existent

Subagent responsable d'aquesta part ha de modificar l'explicacio existent, no crear una experiencia paral.lela.

Fitxer principal:

```text
designacions/services/assignment_explainer.py
```

Canvis recomanats:

1. Fer que `_build_explanation_payload(...)` carregui `AssignmentTrace` si existeix.
2. Afegir al payload una seccio `assignment_origin`:
   - `label`
   - `summary`
   - `stage`
   - `route_size`
   - `inserted_into_existing_route`
   - `route_match_codes`
3. Afegir una seccio `route_context`:
   - llista ordenada de partits de la sequencia;
   - hora;
   - seu;
   - cluster/status si cal per debug o tooltip.
4. Mantenir `debug_payload` fora de la vista principal.
5. Si no hi ha trace, retornar una explicacio degradada:
   - "Origen no disponible perque aquesta designacio es anterior al tracking."

La UI hauria de mostrar primer el resum huma i deixar els camps tecnics en un desplegable secundari o tooltip.

## Disseny Recomanat De Tracking

### Opcio Recomanada: Model Nou `AssignmentTrace`

Afegir un model nou, separat de `Assignment`, per evitar carregar el model principal.

Proposta de camps:

```python
class AssignmentTrace(models.Model):
    run = models.ForeignKey(DesignationRun, ...)
    assignment = models.OneToOneField(Assignment, null=True, blank=True, ...)
    match = models.ForeignKey(Match, ...)
    referee = models.ForeignKey(Referee, null=True, blank=True, ...)

    engine_name = models.CharField(max_length=80)
    stage = models.CharField(max_length=80)
    phase_name = models.CharField(max_length=80, blank=True, default="")
    rescue_kind = models.CharField(max_length=80, blank=True, default="")
    rescue_iteration = models.IntegerField(null=True, blank=True)

    route_id = models.CharField(max_length=255, blank=True, default="")
    candidate_id = models.CharField(max_length=255, blank=True, default="")
    tutor_id = models.CharField(max_length=80, blank=True, default="")
    route_match_ids = models.JSONField(default=list)
    route_match_codes = models.JSONField(default=list)
    route_size = models.IntegerField(default=1)
    inserted_into_existing_route = models.BooleanField(default=False)

    selected_score = models.FloatField(null=True, blank=True)
    selected_cost = models.FloatField(null=True, blank=True)
    level_fit = models.CharField(max_length=80, blank=True, default="")
    warning_codes = models.JSONField(default=list)
    mobility_summary = models.JSONField(default=dict)
    debug_payload = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
```

Alternativa mes simple:

- Afegir `trace = models.JSONField(default=dict)` a `Assignment`.

No es recomana com a primera opcio si es vol fer reporting i filtres, perque barreja estat operatiu amb debug/provenance.

### Granularitat

Es recomana guardar una fila per assignacio, pero amb camps de ruta compartits:

```text
Partit A -> trace route_id R1, route_match_ids [A, B, C]
Partit B -> trace route_id R1, route_match_ids [A, B, C]
Partit C -> trace route_id R1, route_match_ids [A, B, C]
```

Aixo fa facil consultar per partit i reconstruir la ruta.

Opcionalment, en una segona fase, afegir un model `RouteTrace`:

```text
RouteTrace 1 -- N AssignmentTrace
```

Pero per una primera implementacio, una sola taula `AssignmentTrace` es suficient.

## Pla D'Implementacio Tracking

### Subagent F: Model I Migracio

Responsabilitat:

- Crear model `AssignmentTrace`.
- Crear migracio.

Fitxers:

```text
designacions/models.py
designacions/migrations/....
```

Criteris d'acceptacio:

- Es pot crear una trace per cada `Assignment`.
- Es pot esborrar un run i netejar traces associades.
- Indexos recomanats:
  - `(run, stage)`
  - `(run, referee)`
  - `(run, match)`
  - `route_id`

### Subagent G: Captura De Traces Al Motor Nou

Responsabilitat:

- Convertir les rutes seleccionades del motor nou en traces persistibles.

Fitxers:

```text
designacions/optimization/state.py
designacions/optimization/phase_runner.py
designacions/main_fixed.py
```

Tasques:

1. Ampliar `state.stage_records` per incloure:
   - `route_id`
   - `candidate_id`
   - `phase_name`
   - `route_match_ids`
   - `inserted_into_existing_route`
   - `warning_codes`
   - `score/cost`
2. Fer que `phase_runner.py` preservi aquesta informacio en `selected_routes`.
3. A `main_fixed.py`, quan es persisteixen assignacions, crear `AssignmentTrace`.
4. Assegurar que els IDs del motor (`engine_id`) es mapegen correctament a `Match`.

Criteris d'acceptacio:

- Cada assignacio automatica del `phased_route_solver` te trace.
- Es pot veure si un partit va entrar per `individual_rescue:3` o per `general`.
- Les rutes de 2 o 3 partits comparteixen `route_id` i `route_match_ids`.

### Subagent H: Tracking Per Legacy I Package Solver

Responsabilitat:

- Afegir traces basiques als altres motors.

Fitxers:

```text
designacions/main_fixed.py
designacions/optimization/package_generation.py
```

Regla:

- Si el motor no te traça rica, guardar com a minim:
  - `engine_name`
  - `stage`
  - `route_match_ids`
  - `route_size`
  - `debug_payload` minim.

Criteris d'acceptacio:

- Les assignacions legacy no queden sense trace.
- Si falta informacio, el camp queda buit pero no trenca UI.

### Subagent I: UI I Export

Responsabilitat:

- Exposar la traça on sigui util.
- Integrar la traça dins l'`Explicacio` existent amb llenguatge comprensible per usuari final.

Fitxers candidats:

```text
designacions/views.py
designacions/templates/run_detail.html
designacions/templates/assignments.html
designacions/services/excel_export.py
designacions/services/assignment_explainer.py
```

Funcionalitats inicials:

1. Al detall del run:
   - resum per origen amb etiquetes humanes.
   - nombre de partits per tipus d'assignacio.
   - nombre de sequencies per tipus d'assignacio.
2. Al llistat d'assignacions:
   - columna o tooltip amb origen huma.
   - filtre per origen d'assignacio.
   - indicador de sequencia: `partit individual`, `sequencia de 3`, `afegit a jornada existent`.
3. A l'`Explicacio` sota demanda:
   - resum narratiu de per que s'ha assignat.
   - origen traduit, no `stage` cru.
   - sequencia completa del tutor si el partit forma part d'una ruta.
   - avisos explicats en llenguatge operatiu.
   - camp tecnic opcional nomes per debug.
4. Export Excel:
   - stage.
   - etiqueta d'origen.
   - route_id.
   - route_match_codes.
   - warning_codes.

Criteris d'acceptacio:

- L'usuari pot respondre sense consola: "aquest partit es va assignar directament, recuperat automaticament o afegit a una sequencia existent".
- L'usuari no necessita saber que volen dir `high`, `general`, `new_route_rescue` o `individual_rescue:3`.
- Les dades tecniques continuen disponibles per debug, pero no son el primer nivell de lectura.

### Subagent J: Tests De Tracking

Responsabilitat:

- Cobrir persistencia i presentacio.

Tests minims:

1. Run amb motor nou crea `AssignmentTrace` per cada assignacio.
2. Una ruta de 2 partits crea dues traces amb el mateix `route_id`.
3. Una repesca individual desa `stage = individual_rescue:n`.
4. Una assignacio manual actualitza o marca la trace com `manual_override`.
5. La UI no falla si una assignacio antiga no te trace.
6. L'`Explicacio` retorna `assignment_origin` amb etiqueta humana quan hi ha trace.
7. L'`Explicacio` retorna un missatge degradat quan no hi ha trace.

## Ordre Recomanat D'Execucio

1. Implementar mobilitat atomica.
2. Afegir tests de regressio del cas run 139.
3. Executar suite focalitzada.
4. Implementar model `AssignmentTrace`.
5. Connectar `phase_runner/state/main_fixed` per persistir traces.
6. Afegir UI/export minim.
7. Fer una revisio final amb un run real:
   - verificar que no apareix el fals error de mobilitat;
   - verificar que cada assignacio explica el seu origen.

## Paralelitzacio Recomanada

Treball que es pot fer en paralel:

- Subagent A pot preparar el helper atomic.
- Subagent F pot preparar model/migracio de tracking.
- Subagent I pot preparar UI amb dades mock o traces opcionals.

Treball que no s'ha de fer en paralel sobre els mateixos fitxers:

- `main_fixed.py` hauria de tenir un sol integrador.
- `route_generation.py` i `rescue.py` poden ser subagents separats, pero han d'acordar el contracte del helper atomic abans.
- `tests.py` pot tenir conflictes; millor que cada subagent afegeixi tests en blocs separats i un integrador revisi.

## Riscos

1. Canviar la mobilitat pot reduir cobertura en casos on abans hi havia falsos positius.
   - Es desitjable si aquests casos eren realment impossibles.
2. Si el helper atomic no pot extreure rows d'algun segment, pot quedar en fallback agregat.
   - Cal log/debug per detectar aquests casos.
3. Tracking massa detallat pot inflar `result_summary`.
   - Per aixo es recomana model separat.
4. Runs antics no tindran traces.
   - La UI ha de tolerar absencia de trace.

## Criteris Finals D'Acceptacio

Mobilitat:

- El cas `Maristes 18:00 -> SAFA 20:00 -> Maristes 21:00` amb `gap_diff_cluster_min=100` queda bloquejat al salt `20:00 -> 21:00`.
- El mateix cas amb `21:45` queda permes amb warning si el tutor te vehicle.
- Dos partits consecutius a la mateixa seu outlier continuen sent viables amb warning.

Tracking:

- Cada assignacio automatica nova te una trace.
- La trace indica stage/fase, ruta i si es repesca.
- El detall del run permet agrupar assignacions per fase.
- El llistat d'assignacions pot mostrar o filtrar per origen d'assignacio.

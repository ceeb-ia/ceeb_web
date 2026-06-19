# Pla D'Implementacio De Snapshots Per Particio En Fases Avancades

## Objectiu

Permetre congelar i actualitzar independentment les particions d'una fase
avancada, mantenint:

- el snapshot global actual com a accio general;
- les `ProgramUnit` ja creades i programades a rotacions;
- la separacio entre categories que competeixen en moments diferents;
- la compatibilitat amb snapshots globals existents;
- la coherencia de classificacions, reserves, portal de jutges i notes.

Cas de referencia:

- Alevi i Cadet comparteixen fase final i classificacio preliminar d'origen.
- Alevi acaba abans i es congela nomes la seva particio.
- Cadet continua sense slots omplerts i no apareix a la classificacio final.
- Quan acaba Cadet, es congela la seva particio sense tocar Alevi ni la seva
  programacio.

## Diagnosi Actual

### Comportament

`apply_qualification(fase)`:

1. calcula tota la classificacio origen;
2. genera preview de totes les particions;
3. buida tots els slots de la fase;
4. omple totes les unitats;
5. desa un unic hash i run global.

La classificacio scoped a una fase consumeix tots els slots `filled` o `manual`
de la fase. Per tant, congelar Alevi tambe materialitza un tall provisional de
Cadet i fa apareixer aquests participants abans d'hora.

### Peces existents reutilitzables

- `ProgramUnit.partition_key`
- `FasePartitionState`
  - `generated`
  - `confirmed`
  - `stale`
  - `qualification_run`
  - `source_snapshot_hash`
- `QualificationRun`
- metadata de snapshot a `ProgramUnit`
- publicacio individual de `ProgramUnit`
- vinculacio de rotacions a `ProgramUnit`, no als seus slots

### Limitacions estructurals

- `FasePartitionState` existeix, pero el snapshot real continua sent global.
- `qualification_is_stale()` compara tota la fase.
- la neteja, proteccio i substitucio de slots es fan globalment.
- reserves i candidats recuperables parteixen de l'ultim run global.
- els bloquejos de publicacio d'unitat consulten obsolescencia global.
- el repartiment de candidats es fa conjuntament entre totes les unitats d'una
  particio.

## Decisions Tancades

### Granularitat

- La granularitat operativa nova es la particio.
- L'accio es pot iniciar des d'una targeta de `ProgramUnit`.
- Si diverses unitats comparteixen `partition_key`, s'actualitzen conjuntament.
- No s'implementa en aquesta iteracio el snapshot d'una sola unitat dins d'una
  particio compartida.

### Snapshot global

- El boto global es conserva.
- Internament aplica totes les particions dins una sola transaccio.
- Un run global pot continuar sent compartit per diversos
  `FasePartitionState`.

### Font de veritat

- `FasePartitionState` passa a indicar quin `QualificationRun` es vigent per a
  cada particio.
- `phase.config["qualification"]` queda com a resum i compatibilitat legacy; no
  ha de decidir quin run correspon a una particio.
- Un `QualificationRun` sense scope explicit es considera global legacy.

### Unitats programades

- No es recrea ni s'elimina cap `ProgramUnit` durant el snapshot.
- Es conserven id, ordre, rotacions, franges, tipus i capacitat.
- Nomes es netegen i omplen els slots de les unitats de la particio objectiu.

### Visibilitat

- Una particio no congelada ha de mantenir els seus slots buits.
- Les classificacions de fase continuen obtenint participants dels slots
  materialitzats.
- Un snapshot `stale` continua representant el tall congelat i no ha de fer
  desapareixer participants; ha de mostrar avisos i bloquejar accions de risc.
- La visibilitat al portal de jutges continua depenent de
  `ProgramUnit.status == published`.

### Proteccions

- Programada, no publicada i sense notes: es pot actualitzar amb confirmacio.
- Publicada: cal retirar la unitat abans d'actualitzar la particio.
- Amb slots `locked` o `manual`: bloqueig normal; override administratiu
  explicit si es conserva el mecanisme actual.
- Amb notes de la fase: bloqueig dur en aquesta iteracio.

## Contracte Proposat

### Scope dels runs

Desar dins `QualificationRun.payload`:

```json
{
  "scope": {
    "kind": "partition",
    "partition_keys": ["categoria:Alevi"]
  }
}
```

Valors:

- `global`: totes les particions incloses al run;
- `partition`: una particio concreta;
- absencia de `scope`: run global legacy.

No es necessaria una migracio de model per a la primera iteracio. Si despres cal
consultar massivament per scope, es pot promoure a camps indexats.

### Hash

Cada `FasePartitionState.source_snapshot_hash` ha de dependre nomes de:

- recepta de tall aplicable;
- configuracio de classificacio;
- files origen de la particio;
- capacitats i ordre de les unitats de la particio;
- estrategia de repartiment;
- candidats, reserves i assignacio resultants.

Un canvi Cadet no pot alterar el hash Alevi.

El hash global es calcula a partir dels hashes de les particions incloses.

### Repartiment determinista

Preview i aplicacio han de produir la mateixa assignacio.

- `classification_order`, `serpentine` i `first_last` ja son deterministes.
- `random` ha d'usar una llavor estable incorporada al payload o conservar
  explicitament el resultat previsualitzat.
- No es pot recalcular un `random.shuffle()` independent durant l'aplicacio.

### Aplicacio selectiva

Nova API interna orientativa:

```python
preview_qualification(fase, partition_keys=None)
apply_qualification(fase, partition_keys=None, ...)
qualification_partition_is_stale(fase, partition_key)
```

`partition_keys=None` conserva el comportament global.

Per una aplicacio parcial:

1. bloquejar la fase i els estats afectats amb `select_for_update`;
2. recalcular la preview de les particions objectiu;
3. validar proteccions;
4. buidar completament els slots de les unitats afectades;
5. omplir-los amb la nova distribucio;
6. actualitzar nomes aquestes unitats i estats;
7. conservar intactes la resta de particions;
8. recalcular l'estat agregat de la fase.

Cal buidar tots els slots objectiu abans de `fill_program_unit_slots`, ja que
aquest helper no neteja les places sobrants.

### Reserves i recuperacio

- Les reserves d'un slot s'obtenen del run vigent del seu
  `FasePartitionState`.
- Els candidats recuperables tambe es resolen per particio.
- No s'ha d'usar simplement l'ultim `QualificationRun` de tota la fase.
- Una reserva no pot creuar particions, excepte futura politica explicita.

### Compatibilitat legacy

- Un snapshot global existent es considera aplicat a totes les particions
  presents al payload o als seus `FasePartitionState`.
- No es reomplen ni migren slots automaticament.
- Les unitats sense `partition_key` pertanyen a `global`.
- En actualitzar una sola particio d'un snapshot global:
  - la resta continua apuntant al run global anterior;
  - la particio actualitzada apunta al nou run parcial.

## Fases D'Implementacio

### Fase 1. Primitives I Tests De Contracte

Objectiu: separar calcul global i calcul per particio sense mutar dades.

Canvis:

- extreure el calcul d'una particio a una funcio reutilitzable;
- afegir filtre `partition_keys` a preview;
- generar hash independent per particio;
- fer determinista l'estrategia `random`;
- afegir scope al payload de `QualificationRun`;
- crear helpers per resoldre:
  - estat vigent d'una particio;
  - run vigent d'una particio;
  - unitats d'una particio;
  - estat agregat de la fase.

Validacions:

- preview Alevi no conte Cadet;
- canviar una nota Cadet no canvia el hash Alevi;
- canviar una nota Alevi si que el canvia;
- dues previews `random` identiques produeixen el mateix resultat;
- run legacy sense scope es resol com global.

Criteri de tancament:

- cap escriptura nova;
- tots els tests legacy de qualificacio continuen passant.

### Fase 2. Aplicacio Selectiva I Compatibilitat Global

Objectiu: materialitzar una o diverses particions sense tocar les altres.

Canvis:

- adaptar `apply_qualification`;
- substituir `_clear_qualification_slots(fase)` per neteja scoped;
- fer scoped:
  - deteccio de slots assignats;
  - slots manuals o bloquejats;
  - metadades de les unitats;
  - sincronitzacio de `FasePartitionState`;
- conservar el boto global com aplicacio de totes les particions;
- mantenir compatibilitat amb runs globals antics.

Validacions:

- congelar Alevi deixa Cadet buit;
- congelar Cadet despres no altera slots, metadata ni rotacions Alevi;
- actualitzar Alevi no modifica `updated_at` dels slots Cadet;
- el global omple totes les particions atomicament;
- una fallada en una particio d'un global fa rollback complet;
- una unitat programada conserva els seus `rotacio_links`.

Criteri de tancament:

- no hi ha cap escriptura fora de les particions objectiu.

### Fase 3. Obsolescencia, Reserves I Proteccions

Objectiu: eliminar dependencias operatives de l'ultim snapshot global.

Canvis:

- implementar obsolescencia per particio;
- adaptar `mark_qualification_stale_if_needed`;
- adaptar reserves i candidats recuperables al run de la particio;
- detectar notes individuals i d'equip de les unitats afectades;
- definir blockers per particio:
  - publicada;
  - notes existents;
  - slots locked;
  - slots manuals;
  - font o pla de grups incompatible.

Validacions:

- Cadet stale no bloqueja publicar Alevi;
- Alevi stale no desapareix de classificacions;
- reserves Alevi provenen del run Alevi;
- no es pot regenerar una particio publicada;
- no es pot regenerar una particio amb notes;
- override de slots protegits no afecta altres particions.

Criteri de tancament:

- cap helper de reserves o obsolescencia depen exclusivament de
  `phase.config["qualification"]["run_id"]`.

### Fase 4. Classificacions I Publicacio

Objectiu: assegurar el comportament parcial en tots els consumidors.

Canvis:

- revisar `phase_slot_subject_ids_for_phase`;
- conservar la lectura dels slots materialitzats de snapshots legacy;
- impedir que una particio nova sense snapshot aporti candidats;
- fer els blockers de publicacio d'unitat dependents de la seva particio;
- mantenir l'accio global de publicacio estricta;
- permetre publicar una unitat Alevi mentre Cadet continua pendent.

Validacions:

- abans de qualsevol snapshot, la classificacio de fase no mostra noms;
- despres del snapshot Alevi, nomes mostra Alevi;
- despres del snapshot Cadet, mostra totes dues particions;
- preview, export i live retornen el mateix univers;
- portal i guardat de jutges nomes accepten unitats publicades;
- classificacions individuals i natives d'equip tenen el mateix contracte.

Criteri de tancament:

- el cas Alevi/Cadet queda cobert end-to-end.

### Fase 5. UI/UX Del Planner

Objectiu: exposar el flux parcial sense confondre unitat i particio.

Menu lateral:

- conservar `Previsualitzar snapshot` i `Congelar/Actualitzar snapshot`;
- indicar que l'accio afecta tota la fase;
- mostrar resum per particions i estats.

Targeta d'unitat:

- afegir `Previsualitzar particio`;
- afegir `Congelar particio` o `Actualitzar particio`;
- mostrar el nom de la particio;
- si hi ha diverses unitats amb la mateixa clau, avisar:
  - "Aquesta accio actualitzara 2 unitats de la particio Alevi.";
- mostrar badges:
  - Sense snapshot
  - Generada
  - Confirmada
  - Obsoleta
  - Publicada

Confirmacions:

- programada:
  - "Es conservaran les rotacions i se substituiran els participants.";
- publicada:
  - boto desactivat amb motiu i accio per retirar del portal;
- amb notes:
  - boto desactivat, sense override des de la UI ordinaria;
- manual/locked:
  - explicar quines places impedeixen l'actualitzacio.

Preview:

- candidats i reserves;
- unitats afectades;
- places buides o insuficients;
- participants entrants i sortints quan es una actualitzacio;
- avisos d'empats i proteccions.

Validacions UI:

- no enviar `unit_id` com a scope de negoci;
- resoldre sempre el `partition_key` al servidor des de la unitat;
- rebutjar unitats d'una altra fase;
- evitar dobles submits;
- mostrar missatges diferenciats per global i particio.

Criteri de tancament:

- l'usuari entén que l'accio iniciada en una unitat afecta tota la seva
  particio.

### Fase 6. Neteja I Documentacio

- eliminar lectures operatives globals que hagin quedat obsoletes;
- documentar el fallback legacy;
- actualitzar manual d'usuari;
- afegir notes d'auditoria als missatges i payloads;
- executar la bateria completa de fases, classificacions, notes, jutges i
  rotacions.

## Orquestracio Recomanada

Ordre obligatori:

1. Fase 1 abans de qualsevol mutacio.
2. Fase 2 abans de tocar classificacions o UI.
3. Fase 3 abans d'habilitar accions parcials a usuaris.
4. Fase 4 abans de considerar el backend funcionalment complet.
5. Fase 5 quan els contractes backend ja siguin estables.
6. Fase 6 al final.

Repartiment possible:

- Agent A: `qualification.py`, scope, hash i apply.
- Agent B: reserves, stale i blockers, nomes despres del contracte de l'Agent A.
- Agent C: classificacions, notes i jutges, nomes despres de Fases 2 i 3.
- Agent D: planner i templates, nomes despres de fixar payloads i blockers.
- Agent E: tests d'integracio i regressio transversal.

Regles:

- no executar en paral.lel canvis sobre `qualification.py` i
  `slot_overrides.py` sense contracte previ;
- cada fase ha de deixar tests verds abans de continuar;
- no modificar snapshots, slots o notes existents amb migracions de dades;
- preservar canvis locals no relacionats presents al worktree;
- cada agent ha de documentar qualsevol desviacio del contracte abans de
  continuar.

## Matriu De Validacio Funcional

| Escenari | Resultat esperat |
|---|---|
| Snapshot Alevi amb Cadet pendent | Nomes s'omplen unitats Alevi |
| Snapshot Cadet posterior | Alevi queda intacte |
| Unitat Alevi programada | Conserva franja i estacio |
| Particio publicada | No es pot actualitzar fins retirar-la |
| Particio amb notes | Actualitzacio bloquejada |
| Particio amb manual/locked | Bloqueig o override explicit |
| Canvi de notes Cadet | Nomes Cadet queda stale |
| Snapshot global legacy | Continua sent valid i visible |
| Actualitzacio parcial sobre legacy | Nomes canvia el run de la particio |
| Fase individual | Slots `inscripcio` correctes |
| Fase nativa d'equip | Slots `team_unit` correctes |
| Preview random | Mateix resultat que apply |

## Fitxers Principals Afectats

- `models/competicio.py`
  - evitar migracio inicial si el scope viu al payload.
- `services/fases/qualification.py`
  - nucli de preview, apply, hash i stale.
- `services/fases/slot_overrides.py`
  - reserves i recuperacio per particio.
- `services/fases/dashboard.py`
  - estat i accions UI.
- `views/competition/fases/actions.py`
  - endpoints global i parcial.
- `templates/competicio/fases/drawer/_qualification.html`
- `templates/competicio/fases/drawer/_partitions.html`
- `templates/competicio/fases/_program_unit_card.html`
- `templates/competicio/fases/_program_unit_row.html`
- `services/classificacions/engine/loaders.py`
  - univers de participants scoped.
- `services/scoring/phase_eligibility.py`
  - verificar publicacio per unitat.

## Tests Minims

- `tests/fases/test_qualification.py`
- `tests/fases/test_basic_planner_contract.py`
- `tests/fases/test_phase_guardrails.py`
- `tests/classificacions/test_phase_scope.py`
- tests de classificacio nativa d'equip;
- `tests/scoring/notes/test_phase_eligibility.py`
- `tests/scoring/judge/test_portal_assignments.py`
- `tests/rotacions/test_program_unit_assignments.py`

Ordre recomanat:

1. tests unitaris dels helpers de scope i hash;
2. tests de servei de qualificacio;
3. tests del planner;
4. classificacions;
5. notes i jutges;
6. rotacions;
7. paquet complet `competicions_trampoli.tests`.

## Riscos I Mitigacions

### Esborrat transversal de slots

- Risc: reutilitzar la neteja global actual.
- Mitigacio: totes les mutacions reben explicitament unitats objectiu i tenen
  tests de no-modificacio sobre particions germanes.

### Barreja de runs

- Risc: reserves o stale resolts des de l'ultim run global.
- Mitigacio: resolucio canonica via `FasePartitionState.qualification_run`.

### Unitats ja disputades

- Risc: substituir participants amb notes.
- Mitigacio: bloqueig dur abans de qualsevol escriptura.

### Aleatorietat inestable

- Risc: preview i apply diferents.
- Mitigacio: llavor persistent o aplicacio del payload previsualitzat.

### Estat global incoherent

- Risc: marcar tota la fase stale per una sola particio.
- Mitigacio: derivar l'estat de fase dels estats de particio i usar blockers
  scoped per unitat.

## Criteris Finals D'Acceptacio

- Es pot congelar Alevi sense materialitzar Cadet.
- Es pot congelar Cadet despres sense modificar Alevi.
- El snapshot global continua disponible.
- Els snapshots globals existents continuen funcionant sense migracio manual.
- Les rotacions de les unitats no canvien.
- No es poden substituir participants d'unitats publicades o puntuades.
- Classificacions, export i live mostren el mateix univers.
- Reserves, recuperacio i stale funcionen independentment per particio.
- Individuals i equips natius estan coberts.
- La UI explica sempre l'abast real de l'accio.

## Fora D'Abast

- Snapshot d'una sola unitat dins d'una particio compartida.
- Redistribucio automatica de notes quan canvien participants.
- Migracio o regeneracio automatica dels snapshots globals existents.
- Reserves compartides entre particions.
- Redisseny general de fases, rotacions o classificacions.

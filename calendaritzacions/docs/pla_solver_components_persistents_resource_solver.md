# Pla d'implementacio: solver persistent per components del resource_solver

## 0. Objectiu

Aquest document defineix el pla d'implementacio per transformar el
`resource_solver` en un pipeline persistent, reanudable i executable per
components connexos del graf de dependencies.

El problema actual es que el run global pot acabar construint un model CP-SAT
massa gran, amb un sostre de RAM important. El graf de descomposicio ja permet
detectar subdominis independents. La seguent fase ha de fer que aquests
components siguin unitats de treball persistents:

```text
run global
  -> context global
  -> decomposition
  -> validacio de split segur
  -> persistencia de manifest i subcontexts
  -> cua de components
  -> solve component C001
  -> solve component C002
  -> ...
  -> merge final
  -> Excel i auditories globals
```

El worker real que executara les tasques pesades es `worker-heavy` de
`docker-compose.intern.yml`. Aquest worker esta pensat per treballar amb un sol
fil:

```text
celery -A ceeb_web worker -l INFO -Q heavy_queue -c 1 --prefetch-multiplier=1 --max-tasks-per-child=1
```

Aixo implica que la implementacio no ha de dependre de paralelisme real. El
benefici principal ve de:

```text
1. no construir mai el model global gegant si el split es segur
2. alliberar RAM entre components
3. persistir resultats parcials
4. poder reintentar nomes el component que falla
5. poder deixar el sistema hores sense perdre l'estat real
```

## 1. Principis tancats

```text
1. Redis/Celery no es la font de veritat.
2. La font de veritat es DB + fitxers d'auditoria atomics.
3. Cada component es una tasca idempotent.
4. Cada component pot ser reexecutat sense repetir tot el run.
5. El split nomes s'activa si la validacio de seguretat passa completa.
6. Si hi ha dubte, es torna a solver global o es deixa el run en estat explicable.
7. Els resultats parcials s'han de poder inspeccionar abans del merge final.
8. Cap fallada pot quedar silenciosa: ha d'haver-hi status, error i heartbeat.
9. El worker-heavy pot morir; el sistema s'ha de poder reanudar.
10. El merge final ha de validar invariants globals abans d'escriure l'Excel.
```

## 2. Modes d'execucio

Afegir un mode explicit al config del `resource_solver`:

```text
decomposition_mode:
  off
  audit_only
  persist_components
  solve_components
```

Semantica:

```text
off:
  no genera decomposition.

audit_only:
  estat actual; genera auditories i plots, pero resol global.

persist_components:
  genera decomposition, valida split, escriu manifest/subcontexts,
  pero no encola solves.

solve_components:
  genera decomposition, valida split, persisteix components,
  encola cada component i fa merge quan tots acaben.
```

Default recomanat:

```text
audit_only
```

El mode `solve_components` ha d'estar darrere de config explicita fins que hi
hagi fixtures i runs reals validats.

## 3. Model d'estat persistent

### 3.1. Model Django proposat

Crear un model nou:

```python
class CalendarizationComponentRun(models.Model):
    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="component_runs")
    component_id = models.CharField(max_length=32)
    status = models.CharField(max_length=32)
    attempt = models.PositiveIntegerField(default=1)
    active_attempt = models.PositiveIntegerField(default=1)

    team_count = models.PositiveIntegerField(default=0)
    candidate_count = models.PositiveIntegerField(default=0)
    competition_count = models.PositiveIntegerField(default=0)
    resource_count = models.PositiveIntegerField(default=0)
    linkage_count = models.PositiveIntegerField(default=0)

    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    context_path = models.TextField(blank=True, default="")
    validation_path = models.TextField(blank=True, default="")
    model_summary_path = models.TextField(blank=True, default="")
    raw_result_path = models.TextField(blank=True, default="")
    solution_path = models.TextField(blank=True, default="")
    logs_path = models.TextField(blank=True, default="")
    error_path = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        unique_together = [("run", "component_id", "attempt")]
```

Statuses:

```text
pending
queued
running
success
error
stale
skipped
merged
superseded
```

Regles:

```text
success:
  raw_result_path i solution_path existeixen i son JSON valids.

error:
  error_message o error_path existeix.

stale:
  status running amb heartbeat_at massa antic.

superseded:
  intent antic substituit per un intent mes nou.
```

### 3.2. Manifest JSON

Encara que hi hagi DB, generar sempre:

```text
components/manifest.json
```

Exemple:

```json
{
  "artifact_type": "resource_solver_component_manifest",
  "run_id": 121,
  "mode": "solve_components",
  "created_at": "2026-05-14T10:30:00Z",
  "split_validation": {
    "status": "valid",
    "path": "components/split_validation.json"
  },
  "components": [
    {
      "component_id": "C001",
      "status": "success",
      "active_attempt": 1,
      "team_count": 69,
      "candidate_count": 552,
      "context_path": "components/C001/attempt_001/context.json",
      "result_path": "components/C001/attempt_001/raw_result.json"
    }
  ]
}
```

El manifest es pot reconstruir des de DB, pero queda com a auditoria portable.

## 4. Layout de fitxers

Tot ha de viure dins el directori d'auditoria del run:

```text
<input>_resource_solver_audit/
  components/
    manifest.json
    split_validation.json
    C001/
      attempt_001/
        context.json
        validation.json
        model_summary.json
        raw_result.json
        solution_partial.json
        logs.jsonl
        error.txt
      attempt_002/
        ...
    C002/
      attempt_001/
        ...
  merged/
    component_merge_validation.json
    merged_raw_result.json
    merged_solution.json
    merged_logs.jsonl
```

Tots els writes JSON han de ser atomics:

```text
write file.tmp
flush/close
replace file.tmp -> file.json
```

No es pot deixar un JSON parcial si el worker mor.

## 5. Contracte de split segur

Implementar validacio abans de qualsevol solve per components.

Invariants obligatoris:

```text
1. Cada team del context global apareix en exactament un component.
2. Cap component conte un team desconegut.
3. Tots els candidates tenen team_id dins el component corresponent.
4. Cap candidate queda orfe.
5. Cap group_id apareix en mes d'un component.
6. Cap base_resource_id apareix en mes d'un component.
7. Cap linkage_key activa apareix en mes d'un component.
8. Suma de teams dels subcontexts == teams globals.
9. Suma de candidates dels subcontexts == candidates globals.
10. Suma de groups dels subcontexts == groups globals.
11. Cada subcontext es serialitzable i deserialitzable.
12. El build_model d'un subcontext petit funciona sense tocar el global.
```

Si qualsevol invariant falla:

```text
status split = invalid
guardar components/split_validation.json
no encolar components
si config ho permet, fallback a solver global
si config exigeix components, run error explicable
```

## 6. Execucio idempotent de components

Tasca proposada:

```python
solve_resource_component(run_id: int, component_id: str, attempt: int) -> None
```

Regles:

```text
1. Si l'intent ja esta success i els fitxers existeixen, sortir sense recalcular.
2. Si l'intent no es l'actiu, marcar skipped/superseded i sortir.
3. Abans de construir model: status running, started_at, heartbeat_at.
4. Despres de carregar context: heartbeat.
5. Despres de build_model: model_summary.json + heartbeat.
6. Despres de solve: raw_result.json + heartbeat.
7. Despres de solution parcial: solution_partial.json + success.
8. Qualsevol excepcio: error.txt + logs + status error.
```

El component no ha de guardar nomes logs en memoria. Ha d'anar escrivint
`logs.jsonl` o fer flush per fases.

## 7. Heartbeat i watchdog

### 7.1. Heartbeat

Cada tasca de component ha d'actualitzar:

```text
heartbeat_at = now()
```

Moments minims:

```text
component_start
context_loaded
model_built
solve_started
solve_finished
artifacts_written
```

Si OR-Tools bloqueja molta estona dins `solve_model`, no hi ha heartbeat intern
facil. Per aixo cal:

```text
time_limit_seconds finit
logs abans i despres del solve
watchdog que detecti running antic
max_tasks_per_child=1 per reciclar proces
```

### 7.2. Watchdog

Crear una management command:

```bash
python manage.py reconcile_resource_components --run 121
python manage.py reconcile_resource_components --all-running
```

Funcions:

```text
1. Detectar components running amb heartbeat_at antic.
2. Si el proces Celery ja no existeix o el run esta aturat, marcar stale.
3. Reencolar stale si attempt < max_attempts i config ho permet.
4. Marcar error si supera max_attempts.
5. Recalcular manifest.json des de DB.
6. Si tots success, encolar merge.
```

Threshold inicial:

```text
stale_after_minutes = max(30, 2 * time_limit_seconds / 60)
```

## 8. Merge incremental i final

Tasca proposada:

```python
merge_resource_component_results(run_id: int) -> None
```

Precondicions:

```text
tots els components actius estan success o skipped justificat
split_validation.status == valid
```

Validacions de merge:

```text
1. Cada team global te exactament una assignment final.
2. Cap assignment apunta a team desconegut.
3. Cap group_id parcial es desconegut.
4. Suma assignments parcials == teams globals.
5. Si algun component INFEASIBLE, status global INFEASIBLE.
6. Si algun component UNKNOWN/TIME_LIMIT, status global UNKNOWN excepte INFEASIBLE.
7. Si tots OPTIMAL/FEASIBLE, status global FEASIBLE o OPTIMAL segons regla conservadora.
8. Objective global = suma objectives si totes son numeriques; si no, null.
```

Output:

```text
merged/merged_raw_result.json
merged/merged_solution.json
merged/component_merge_validation.json
assignacions_<input>.xlsx
plots finals
```

## 9. Reexecucio de components

Operacions necessaries:

```bash
python manage.py rerun_resource_component 121 C002
python manage.py rerun_resource_components 121 --failed
python manage.py rerun_resource_components 121 --stale
python manage.py rerun_resource_components 121 --all
python manage.py merge_resource_components 121
```

Regla de reexecucio:

```text
1. Crear attempt nou.
2. Marcar intent anterior superseded nomes quan el nou intent acaba success.
3. No esborrar artefactes antics.
4. Actualitzar active_attempt al nou intent.
5. Encolar component.
6. Quan acabi, invalidar merge anterior i encolar merge nou.
```

Exemple d'estructura:

```text
components/C002/attempt_001/raw_result.json
components/C002/attempt_001/error.txt
components/C002/attempt_002/raw_result.json
```

## 10. UI minima

Afegir al workspace una pestanya o panell:

```text
Components
```

Columnes:

```text
component_id
status
attempt
teams
candidates
started_at
heartbeat_at
finished_at
duration
error
actions
```

Accions:

```text
Veure graf
Veure logs
Veure error
Reexecutar component
Reexecutar fallits
Recalcular merge
```

La UI no ha de ser imprescindible per operar. Les management commands han de
permetre recuperar el sistema encara que la UI no estigui disponible.

## 11. Pla per subagents

Els write-sets han d'estar separats per minimitzar conflictes. Cada agent ha de
deixar tests i no ha de activar `solve_components` per defecte.

### PCS-01: estat persistent i storage atomic

Objectiu:

```text
crear la base persistent de components i helpers d'escriptura atomica
```

Write-set:

```text
calendaritzacions/django/models.py
calendaritzacions/django/migrations/*
calendaritzacions/django/services/component_runs.py
calendaritzacions/tests/test_resource_solver_component_state.py
```

Tasques:

```text
1. Model CalendarizationComponentRun.
2. Helpers create/update/heartbeat.
3. Helper atomic_write_json.
4. Helper component_attempt_dir.
5. Tests d'idempotencia i paths.
```

Criteris d'acceptacio:

```text
model amb unique constraint
atomic write no deixa fitxer final si falla abans del replace
heartbeat actualitza nomes component actiu
no toca service.py encara
```

### PCS-02: split de context i validacio forta

Objectiu:

```text
filtrar SolverContext per component i validar que el split es segur
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/engine/variants/resource_solver/component_context.py
calendaritzacions/tests/test_resource_solver_component_context.py
```

Tasques:

```text
1. filter_context_by_team_ids.
2. split_context_by_components.
3. validate_component_split.
4. JSON payload de split_validation.
5. Tests fixtures: dos components, resource pont, linkage pont, group compartit invalid.
```

Criteris d'acceptacio:

```text
suma teams/candidates/groups coincideix
detecta group/resource/linkage compartit
no construeix CP-SAT
```

### PCS-03: persistencia de manifest i subcontexts

Objectiu:

```text
materialitzar components validats a disc i DB sense resoldre'ls
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/component_persistence.py
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/tests/test_resource_solver_component_persistence.py
```

Tasques:

```text
1. build_component_manifest.
2. write component context.json per attempt_001.
3. Crear CalendarizationComponentRun per component.
4. Mode persist_components.
5. Registrar audit_path component_manifest.
```

Criteris d'acceptacio:

```text
run amb persist_components no executa solver global
manifest portable existeix
subcontexts existeixen
si split invalid, guarda split_validation i no crea tasques
```

### PCS-04: tasca Celery de component

Objectiu:

```text
executar una unitat component de forma idempotent
```

Write-set:

```text
calendaritzacions/django/tasks.py o tasks existents
calendaritzacions/django/services/component_tasks.py
calendaritzacions/tests/test_resource_solver_component_tasks.py
```

Tasques:

```text
1. solve_resource_component(run_id, component_id, attempt).
2. Rebutjar intents no actius.
3. Heartbeat per fases.
4. Captura d'excepcions.
5. Logs persistits.
```

Criteris d'acceptacio:

```text
component success no es recalcula
component amb excepcio queda error amb error.txt
component stale es pot reencolar
tests amb mocks, sense OR-Tools real
```

### PCS-05: adapter de solve per component

Objectiu:

```text
connectar subcontext -> build_solver_model -> solve_model -> raw_result parcial
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/component_solver.py
calendaritzacions/tests/test_resource_solver_component_solver.py
```

Tasques:

```text
1. load_component_context.
2. solve_component_context.
3. write model_summary.json.
4. write raw_result.json.
5. write solution_partial.json.
```

Criteris d'acceptacio:

```text
funciona amb fixture petita
no depen de DB
retorna payload JSON-ready
```

### PCS-06: merge de resultats

Objectiu:

```text
fusionar resultats parcials i produir sortida global
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/component_merge.py
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/tests/test_resource_solver_component_merge.py
```

Tasques:

```text
1. load active component results.
2. merge RawSolverResult.
3. validate merged assignments.
4. escriure merged_solution/raw_result.
5. generar Excel final i plots finals quan tots success.
```

Criteris d'acceptacio:

```text
merge falla explicitament si falta component
detecta team duplicat o absent
status global conservador correcte
```

### PCS-07: watchdog i reexecucio

Objectiu:

```text
recuperar components morts o fallits sense operar manualment fitxers
```

Write-set:

```text
calendaritzacions/django/management/commands/reconcile_resource_components.py
calendaritzacions/django/management/commands/rerun_resource_component.py
calendaritzacions/django/services/component_recovery.py
calendaritzacions/tests/test_resource_solver_component_recovery.py
```

Tasques:

```text
1. reconcile --run.
2. reconcile --all-running.
3. rerun component.
4. rerun --failed/--stale/--all.
5. max attempts.
```

Criteris d'acceptacio:

```text
running antic passa a stale
stale es reencola si attempt < max_attempts
rerun crea attempt nou sense esborrar l'anterior
manifest es regenera
```

### PCS-08: UI de components

Objectiu:

```text
donar visibilitat i operacions manuals al workspace
```

Write-set:

```text
calendaritzacions/django/views.py
calendaritzacions/django/templates/calendaritzacions/resource_workspace.html
calendaritzacions/django/static/calendaritzacions/calendaritzacions.js
calendaritzacions/tests/test_django_calendaritzacions_views.py
```

Tasques:

```text
1. Panell Components.
2. Status, heartbeat, durada, intents.
3. Links a logs/errors/artifacts.
4. Accio reexecutar component.
5. Accio merge.
```

Criteris d'acceptacio:

```text
UI llegeix estat DB
no bloqueja si no hi ha components
accions POST amb csrf
```

### PCS-09: integracio intern i operativa

Objectiu:

```text
assegurar que docker.intern i la cua heavy funcionen amb runs llargs
```

Write-set:

```text
docker-compose.intern.yml
calendaritzacions/docs/pla_solver_components_persistents_resource_solver.md
calendaritzacions/tests/test_django_calendaritzacions_services.py
```

Tasques:

```text
1. Confirmar worker-heavy concurrency=1.
2. Confirmar prefetch_multiplier=1.
3. Confirmar max_tasks_per_child=1.
4. Documentar com reanudar despres d'una caiguda.
5. Documentar com veure cua i logs.
```

Criteris d'acceptacio:

```text
docker compose -f docker-compose.intern.yml --env-file .env.intern ps
worker-heavy consumeix heavy_queue
tasques pesades no van a worker default
```

## 12. Ordre d'implementacio

Ordre recomanat per cua unica:

```text
1. PCS-01 estat persistent i storage atomic
2. PCS-02 split de context i validacio forta
3. PCS-03 persistencia manifest/subcontexts
4. PCS-07 watchdog minim amb reconcile sense reencolar
5. PCS-04 tasca Celery idempotent amb mocks
6. PCS-05 adapter solve component
7. PCS-06 merge
8. PCS-07 reexecucio completa
9. PCS-08 UI
10. PCS-09 hardening intern
```

No activar `solve_components` fins que PCS-01..PCS-06 passin tests.

## 13. Operativa d'un run llarg

### 13.1. Llançament

```text
1. Crear run amb decomposition_mode=solve_components.
2. El servei construeix context i components.
3. Persisteix manifest.
4. Encola components a heavy_queue.
5. Retorna o deixa el run en status running_componentized.
```

### 13.2. Durant la nit

El sistema ha de poder respondre:

```text
quants components han acabat?
quin component esta corrent?
quan va fer heartbeat?
quin component ha fallat?
quin error concret ha deixat?
quins fitxers parcials existeixen?
```

### 13.3. Si el worker mor

Procediment:

```bash
docker compose -f docker-compose.intern.yml --env-file .env.intern ps
python manage.py reconcile_resource_components --all-running
python manage.py rerun_resource_components <run_id> --stale
```

El sistema no ha de dependre de saber si Celery conserva la tasca pendent. Ha de
poder recrear la cua des de DB.

### 13.4. Si un component falla

Procediment:

```bash
python manage.py rerun_resource_component <run_id> C002
python manage.py merge_resource_components <run_id>
```

La UI ha de permetre el mateix amb botons, pero la CLI es el fallback fiable.

## 14. Criteris de done globals

La fase es considera completada quan:

```text
1. Un run pot generar manifest i subcontexts sense resoldre.
2. Un run pot resoldre components en cua heavy de forma seqüencial.
3. La RAM queda limitada per component, no pel model global.
4. Els components success tenen raw_result i solution parcial.
5. Un component error deixa error visible i reexecutable.
6. Un worker mort deixa component stale detectable.
7. El merge genera un Excel global validat.
8. Es pot reexecutar un component sense perdre intents antics.
9. Les management commands permeten recuperar un run sense UI.
10. `audit_only` continua sent el default segur.
```

## 15. Riscos i mitigacions

### Component gegant unic

Risc:

```text
la decomposition retorna un component molt gran i pocs components petits
```

Mitigacio:

```text
encara hi ha benefici parcial si no es construeixen altres components alhora
caldria fase futura de split heuristic dins component, no inclosa aqui
```

### Dependencia no modelada al graf

Risc:

```text
el solver global acobla dos components per una restriccio no representada
```

Mitigacio:

```text
validacio forta
mode audit_only default
fixtures comparant global vs components
fallback a global si hi ha dubte
```

### OR-Tools no allibera RAM

Risc:

```text
la memoria no baixa despres d'un component
```

Mitigacio:

```text
--max-tasks-per-child=1 al worker-heavy
cada component com a tasca Celery separada
no executar tots els components en un bucle dins el mateix proces
```

### Fallada silenciosa

Risc:

```text
worker mort, tasca perduda, run queda running per sempre
```

Mitigacio:

```text
heartbeat persistent
watchdog reconcile
status stale
commands de reencua
manifest regenerable des de DB
```

## 16. Notes per als workers

Cada subagent ha de:

```text
1. llegir aquest document i el pla de grafitzacio existent
2. tocar nomes el write-set assignat
3. no activar solve_components per defecte
4. afegir tests focalitzats
5. deixar missatge final amb fitxers canviats i com verificar
```

Fitxers base relacionats:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/engine/variants/resource_solver/model.py
calendaritzacions/engine/variants/resource_solver/solution.py
calendaritzacions/django/services/runs.py
docker-compose.intern.yml
```


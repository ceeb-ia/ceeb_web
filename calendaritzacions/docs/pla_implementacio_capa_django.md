# Pla d'implementacio de la capa Django

## 0. Objectiu

Aquest document defineix una capa Django instal.lable per al paquet existent
`calendaritzacions`, sense moure ni duplicar el codi ja separat.

La capa Django ha de conviure amb:

```text
calendaritzacions/application/
calendaritzacions/analysis/
calendaritzacions/domain/
calendaritzacions/engine/
calendaritzacions/ingestion/
calendaritzacions/reporting/
calendaritzacions/second_phase/
```

El codi de motors i pipelines no s'ha de copiar a la capa Django. La capa Django
nomes ha d'orquestrar, persistir runs i renderitzar templates.

## 1. Principis

Decisions tancades:

```text
1. Afegir una subcarpeta nova `calendaritzacions/django/`.
2. No modificar els motors `legacy` ni `resource_solver`.
3. No moure codi de `application`, `engine`, `analysis`, `reporting` ni `ingestion`.
4. Les views han de cridar serveis Django, no motors directament.
5. Els serveis Django han de cridar `calendaritzacions.application.process_calendarization`.
6. La capa Django ha de ser instal.lable amb `calendaritzacions.django`.
7. Les templates i statics han d'estar namespaced.
8. El projecte host nomes hauria d'afegir `INSTALLED_APPS` i `include(...)`.
```

## 2. Estructura objectiu

Nova estructura:

```text
calendaritzacions/
  django/
    __init__.py
    apps.py
    urls.py
    forms.py
    models.py
    admin.py
    views.py
    services/
      __init__.py
      runs.py
      storage.py
      audit_reader.py
    templates/
      calendaritzacions/
        base.html
        run_list.html
        run_create.html
        run_detail.html
        audit_detail.html
        partials/
          run_status_badge.html
          audit_links.html
          logs_panel.html
          artifact_summary.html
    static/
      calendaritzacions/
        calendaritzacions.css
        calendaritzacions.js
    templatetags/
      __init__.py
      calendaritzacions_json.py
    migrations/
      __init__.py
```

Tests nous:

```text
tests/test_django_calendaritzacions_models.py
tests/test_django_calendaritzacions_forms.py
tests/test_django_calendaritzacions_services.py
tests/test_django_calendaritzacions_views.py
tests/test_django_calendaritzacions_urls.py
```

## 3. Instal.lacio esperada al projecte host

El projecte Django host hauria de poder fer:

```python
INSTALLED_APPS += [
    "calendaritzacions.django",
]
```

I a `urls.py`:

```python
from django.urls import include, path

urlpatterns += [
    path("calendaritzacions/", include("calendaritzacions.django.urls")),
]
```

Configuracio opcional:

```python
CALENDARITZACIONS_DEFAULT_ENGINE = "resource_solver"
CALENDARITZACIONS_DEFAULT_PHASE = "primera_fase"
CALENDARITZACIONS_ASYNC_BACKEND = "sync"
CALENDARITZACIONS_UPLOAD_SUBDIR = "calendaritzacions/inputs"
CALENDARITZACIONS_OUTPUT_SUBDIR = "calendaritzacions/outputs"
```

La capa ha de funcionar amb defaults si aquests settings no existeixen.

## 4. Model Django

Fitxer: `calendaritzacions/django/models.py`

Model principal:

```python
class CalendarizationRun(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"

    ENGINE_LEGACY = "legacy"
    ENGINE_RESOURCE_SOLVER = "resource_solver"

    PHASE_FIRST = "primera_fase"
    PHASE_SECOND = "segona_fase"

    input_file = models.FileField(...)
    input_name = models.CharField(...)
    engine_name = models.CharField(...)
    phase = models.CharField(...)
    status = models.CharField(...)
    output_path = models.TextField(blank=True)
    kpis_path = models.TextField(blank=True)
    audit_paths = models.JSONField(default=dict, blank=True)
    logs = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
```

Notes:

```text
input_file ha d'usar storage Django.
output_path pot ser path absolut o path de storage, segons el servei.
audit_paths ha de guardar claus com `resource_solution`, `solver_explanations`.
logs ha de ser llista de strings.
```

Metodes recomanats:

```python
is_finished
duration_seconds
available_audits
mark_running()
mark_success(...)
mark_error(...)
```

## 5. Formularis

Fitxer: `calendaritzacions/django/forms.py`

Formulari principal:

```python
class CalendarizationRunForm(forms.ModelForm):
    class Meta:
        model = CalendarizationRun
        fields = ["input_file", "engine_name", "phase"]
```

Regles:

```text
engine_name choices: legacy, resource_solver
phase choices: primera_fase, segona_fase
validar extensions .xlsx, .xls, .csv si es vol suportar CSV
no validar contingut complet del fitxer a la form
```

La validacio profunda ha de continuar dins `ingestion`/`application`.

## 6. URLs

Fitxer: `calendaritzacions/django/urls.py`

Rutes:

```python
app_name = "calendaritzacions"

urlpatterns = [
    path("", RunListView.as_view(), name="run_list"),
    path("new/", RunCreateView.as_view(), name="run_create"),
    path("runs/<int:pk>/", RunDetailView.as_view(), name="run_detail"),
    path("runs/<int:pk>/download/", RunDownloadView.as_view(), name="run_download"),
    path("runs/<int:pk>/audit/<slug:artifact>/", AuditDetailView.as_view(), name="audit_detail"),
]
```

No afegir API REST en l'MVP. La capa demanada es template-based.

## 7. Views natives Django

Fitxer: `calendaritzacions/django/views.py`

Views:

```text
RunListView      -> ListView
RunCreateView    -> FormView o CreateView
RunDetailView    -> DetailView
AuditDetailView  -> DetailView o TemplateView
RunDownloadView  -> View amb FileResponse
```

### 7.1. `RunListView`

Responsabilitats:

```text
mostrar runs recents
ordenar per created_at desc
filtrar opcionalment per status/engine
```

Template:

```text
calendaritzacions/run_list.html
```

### 7.2. `RunCreateView`

Responsabilitats:

```text
crear CalendarizationRun en pending
cridar service d'execucio
redirigir al detail
```

En l'MVP pot executar sincronament. El service ha de quedar preparat per ser
cridat des d'una tasca async en el futur.

Template:

```text
calendaritzacions/run_create.html
```

### 7.3. `RunDetailView`

Responsabilitats:

```text
mostrar status
mostrar logs
mostrar links de resultats i auditoria
mostrar error si status error
```

Template:

```text
calendaritzacions/run_detail.html
```

### 7.4. `AuditDetailView`

Responsabilitats:

```text
llegir artifact JSON segurament
mostrar resum i JSON formatat
retornar 404 si artifact no existeix
```

No ha d'executar motors.

Template:

```text
calendaritzacions/audit_detail.html
```

### 7.5. `RunDownloadView`

Responsabilitats:

```text
retornar FileResponse del resultat final
validar que run.status == success
no permetre path traversal
```

## 8. Services Django

Els services son l'adaptador entre Django i el core existent.

### 8.1. `services/runs.py`

Contractes:

```python
def execute_run(run: CalendarizationRun) -> CalendarizationRun:
    ...

def enqueue_run(run: CalendarizationRun) -> CalendarizationRun:
    ...
```

`execute_run` ha de:

```text
1. marcar run com running
2. cridar `calendaritzacions.application.process_calendarization`
3. passar engine_name i segona_fase_bool
4. guardar output_path, logs i audit_paths
5. marcar success o error
```

Pseudocodi:

```python
from calendaritzacions.application import process_calendarization

def execute_run(run):
    run.mark_running()
    try:
        output = process_calendarization(
            input_path=run.input_file.path,
            return_logs=True,
            segona_fase_bool=(run.phase == CalendarizationRun.PHASE_SECOND),
            engine_name=run.engine_name,
        )
        output_path, logs = output if isinstance(output, tuple) else (output, [])
        audit_paths = discover_audit_paths(output_path)
        run.mark_success(output_path=output_path, logs=logs, audit_paths=audit_paths)
    except Exception as exc:
        run.mark_error(str(exc))
    return run
```

Important:

```text
No importar `legacy_pipeline` directament.
No importar `resource_solver` directament.
No copiar codi dels motors.
```

### 8.2. `services/storage.py`

Responsabilitats:

```text
resoldre paths de fitxers de sortida
validar existencia de fitxers
obrir fitxers per download
mapar output_path absolut a FileResponse
```

Ha de protegir:

```text
path traversal
fitxer inexistent
download abans de success
```

### 8.3. `services/audit_reader.py`

Responsabilitats:

```text
discover_audit_paths(output_path)
read_audit_artifact(run, artifact)
json pretty/context for templates
```

Per `resource_solver`, els audit paths ja venen dins `EngineResult.audit_paths`
quan es crida via engine. Per legacy, pot descobrir fitxers per nom si cal.

Contracte recomanat:

```python
def discover_audit_paths(output_path: str) -> dict[str, str]:
    ...

def read_audit_artifact(run, artifact: str) -> dict:
    ...
```

## 9. Templates

La UI ha de ser operacional i compacta, no landing page.

### 9.1. `base.html`

Contingut:

```text
layout base
nav simple
bloc content
carrega CSS namespaced
```

No assumir Bootstrap. Si el projecte host ja en te, el template pot conviure.
CSS propi namespaced sota `.calendaritzacions-app`.

### 9.2. `run_list.html`

Ha de mostrar:

```text
taula de runs
status
engine
phase
input_name
created_at
durada
link al detail
boto nova calendaritzacio
```

### 9.3. `run_create.html`

Ha de mostrar:

```text
formulari upload
selector engine
selector phase
errors de formulari
submit
```

### 9.4. `run_detail.html`

Ha de mostrar:

```text
status badge
input
engine / phase
created/started/finished
download si success
llista audit artifacts
logs
error_message si error
```

### 9.5. `audit_detail.html`

Ha de mostrar:

```text
nom artifact
resum si es pot inferir
JSON pretty
link tornar al run
```

### 9.6. Partials

```text
partials/run_status_badge.html
partials/audit_links.html
partials/logs_panel.html
partials/artifact_summary.html
```

## 10. Static i templatetags

### 10.1. CSS

Fitxer:

```text
calendaritzacions/django/static/calendaritzacions/calendaritzacions.css
```

Objectiu:

```text
taules compactes
badges d'estat
panells de logs
JSON preformatat
botons simples
```

No dependre d'un framework CSS.

### 10.2. JavaScript

Fitxer:

```text
calendaritzacions/django/static/calendaritzacions/calendaritzacions.js
```

MVP:

```text
cap JS obligatori
opcional: auto-refresh en detail si status pending/running
```

### 10.3. Template tags

Fitxer:

```text
calendaritzacions/django/templatetags/calendaritzacions_json.py
```

Filtres:

```text
json_pretty
dict_get
basename
```

## 11. Admin

Fitxer:

```text
calendaritzacions/django/admin.py
```

Registrar `CalendarizationRun` amb:

```text
list_display: id, input_name, engine_name, phase, status, created_at, finished_at
list_filter: status, engine_name, phase
search_fields: input_name, error_message
readonly_fields: audit_paths, logs, output_path, created_at, started_at, finished_at
```

No executar runs des de l'admin en l'MVP.

## 12. Async futur

L'MVP pot ser sync, pero el service ha de preparar el pas a async.

Patro:

```python
def enqueue_run(run):
    backend = getattr(settings, "CALENDARITZACIONS_ASYNC_BACKEND", "sync")
    if backend == "sync":
        return execute_run(run)
    if backend == "celery":
        # futura integracio
        ...
```

Futur fitxer opcional:

```text
calendaritzacions/django/tasks.py
```

No implementar Celery si el projecte host no l'exigeix.

## 13. Pla per subagents

### DJANGO-00 scaffold-app

Objectiu:

```text
crear carpeta `calendaritzacions/django`
afegir apps.py, __init__.py, urls.py buit/minim
no tocar core existent
```

Write-set:

```text
calendaritzacions/django/__init__.py
calendaritzacions/django/apps.py
calendaritzacions/django/urls.py
tests/test_django_calendaritzacions_urls.py
```

Criteris:

```text
import calendaritzacions.django funciona
AppConfig.name == "calendaritzacions.django"
urls exposa app_name = "calendaritzacions"
```

### DJANGO-01 models-admin

Objectiu:

```text
crear model CalendarizationRun
crear migracio inicial
registrar admin
```

Write-set:

```text
calendaritzacions/django/models.py
calendaritzacions/django/admin.py
calendaritzacions/django/migrations/__init__.py
calendaritzacions/django/migrations/0001_initial.py
tests/test_django_calendaritzacions_models.py
```

Criteris:

```text
model instanciable
methods mark_running/mark_success/mark_error funcionen
choices engine/phase/status definides
```

### DJANGO-02 forms

Objectiu:

```text
crear CalendarizationRunForm
validar engine i phase
validar extensio d'input
```

Write-set:

```text
calendaritzacions/django/forms.py
tests/test_django_calendaritzacions_forms.py
```

Criteris:

```text
form accepta legacy/resource_solver
form accepta primera/segona fase
form rebutja extensio no permesa
```

### DJANGO-03 services

Objectiu:

```text
crear services/runs.py, storage.py, audit_reader.py
connectar amb process_calendarization
```

Write-set:

```text
calendaritzacions/django/services/__init__.py
calendaritzacions/django/services/runs.py
calendaritzacions/django/services/storage.py
calendaritzacions/django/services/audit_reader.py
tests/test_django_calendaritzacions_services.py
```

Criteris:

```text
execute_run crida process_calendarization, no motors directament
segona_fase_bool deriva de run.phase
engine_name deriva de run.engine_name
errors queden guardats al run
audit reader llegeix JSON segur
```

### DJANGO-04 views-urls

Objectiu:

```text
crear views basades en TemplateView/ListView/FormView/DetailView
connectar urls finals
```

Write-set:

```text
calendaritzacions/django/views.py
calendaritzacions/django/urls.py
tests/test_django_calendaritzacions_views.py
tests/test_django_calendaritzacions_urls.py
```

Criteris:

```text
run_list respon 200
run_create GET respon 200
run_create POST crea run i crida enqueue_run
run_detail respon 200
audit_detail retorna 404 si artifact no existeix
download usa FileResponse si success
```

### DJANGO-05 templates-static

Objectiu:

```text
crear templates i CSS namespaced
```

Write-set:

```text
calendaritzacions/django/templates/calendaritzacions/**
calendaritzacions/django/static/calendaritzacions/calendaritzacions.css
calendaritzacions/django/static/calendaritzacions/calendaritzacions.js
```

Criteris:

```text
templates no fallen sense Bootstrap
no hi ha text que assumeixi una marca externa
UI compacta i operativa
links usen namespace calendaritzacions:
```

### DJANGO-06 templatetags

Objectiu:

```text
crear filtres per JSON i paths
```

Write-set:

```text
calendaritzacions/django/templatetags/__init__.py
calendaritzacions/django/templatetags/calendaritzacions_json.py
tests/test_django_calendaritzacions_templatetags.py
```

Criteris:

```text
json_pretty retorna string estable
dict_get funciona amb claus inexistents
basename no exposa path complet si no cal
```

## 14. Estrategia de tests

Els tests Django han de ser petits.

Si Django no esta instal.lat en l'entorn de test:

```text
usar skipUnless(importlib.util.find_spec("django"))
```

No s'ha d'exigir base de dades real externa. Usar la DB de test de Django.

Tests recomanats:

```text
model methods
form validation
service execute_run amb mock de process_calendarization
view create amb mock de enqueue_run
audit_reader amb JSON temporal
url reverse names
template render basic
```

No executar calendaritzacions reals dins tests de views.

## 15. Definicio de fet

La capa Django es considera llesta quan:

```text
1. `calendaritzacions.django` es pot afegir a INSTALLED_APPS.
2. `include("calendaritzacions.django.urls")` funciona.
3. Es pot crear un run des d'un formulari template.
4. El service reutilitza `process_calendarization`.
5. Es pot escollir `legacy` o `resource_solver`.
6. Es pot escollir primera o segona fase.
7. Es mostra detall de run, logs i errors.
8. Es poden descarregar resultats.
9. Es poden veure artefactes d'auditoria JSON.
10. No s'ha copiat cap codi de motor.
11. Els tests Django petits passen o se salten netament si Django no esta instal.lat.
```

## 16. Riscos

### 16.1. Duplicar logica de motor

Risc:

```text
views o services importen legacy/resource_solver directament i reimplementen fluxos
```

Mitigacio:

```text
services/runs.py nomes crida process_calendarization
tests amb patch sobre calendaritzacions.django.services.runs.process_calendarization
```

### 16.2. Paths insegurs

Risc:

```text
download o audit detail obren qualsevol path
```

Mitigacio:

```text
centralitzar a services/storage.py
validar existencia i propietat del run
no acceptar paths arbitrats per querystring
```

### 16.3. Runs llargs en request web

Risc:

```text
execute_run sync bloqueja request
```

Mitigacio MVP:

```text
documentar que sync es per proves o runs petits
deixar enqueue_run com boundary per Celery/RQ futur
```

### 16.4. Conflicte de templates/static amb projecte host

Mitigacio:

```text
templates sota templates/calendaritzacions/
static sota static/calendaritzacions/
CSS sota classe .calendaritzacions-app
```

## 17. Extensions futures

Quan la capa MVP funcioni:

```text
polling AJAX de status
cancel.lacio de runs
reexecucio d'un run
comparativa legacy vs resource_solver dins la UI
taules especifiques per resource_pressure/resource_solution
integracio Celery/RQ
permisos per usuari
neteja automatica de fitxers antics
```

## 18. Estat d'implementacio

Implementat en l'MVP:

```text
calendaritzacions/django com a app instal.lable
models, migracio inicial i admin de CalendarizationRun
formulari d'upload amb engine i phase
services Django per executar runs via process_calendarization
return_artifacts opt-in a application.process_calendarization
urls template-based amb namespace calendaritzacions
views natives Django per llista, alta, detall, auditoria i download
templates i static namespaced sota calendaritzacions/
templatetags json_pretty, dict_get i basename
tests Django executats amb Django instal.lat
requirements.txt inclou Django
```

Decisions de compatibilitat:

```text
process_calendarization(..., return_logs=True) mante el retorn antic (output_path, logs)
process_calendarization(..., return_artifacts=True) retorna output_path, logs, audit_paths, kpis_path
la capa Django usa return_artifacts=True
```

Validacio executada:

```text
docker compose run --rm app python -m unittest discover -s tests -p "test_django_calendaritzacions*.py"
docker compose run --rm app python -m unittest tests.test_resource_solver_service
docker compose run --rm app python -m unittest discover -s tests
```

Queda fora de l'MVP:

```text
backend async real Celery/RQ
cancel.lacio i reexecucio de runs
permisos per usuari
empaquetat Python complet amb pyproject/setup/MANIFEST
```

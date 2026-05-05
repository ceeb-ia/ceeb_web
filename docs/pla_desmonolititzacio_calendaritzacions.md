# Pla de desmonolititzacio i reorganitzacio del repo

## 0. Objectiu del document

Aquest document defineix un pla executable per desacoblar el programa de
calendaritzacions sense canviar el comportament actual. Esta pensat perque
diversos subagents o desenvolupadors puguin treballar en paralel amb poc
context previ, amb fronteres clares de responsabilitat i criteris de verificacio.

El principi rector es aquest:

> La V1 actual ha de quedar encapsulada com a motor `legacy`, amb contracte
> estable, abans d'introduir cap variant nova de motor.

Per tant, la primera etapa no busca "millorar" l'algorisme. Busca separar-lo,
fer-lo auditable i preparar-lo per comparar motors futurs.

## 1. Restriccions globals

Qualsevol subagent que executi una part d'aquest pla ha de respectar aquestes
regles:

- No canviar el resultat funcional de la V1.
- No canviar el format final de l'Excel mentre no hi hagi una fase especifica.
- No eliminar `main.py`, `assignacions.py` ni `app.py` d'entrada.
- Crear wrappers i facanes de compatibilitat abans de moure responsabilitats.
- Mantenir `process_excel(...)` com a punt d'entrada compatible fins que Django
  tingui el seu propi cas d'us.
- Evitar refactors cosmetics o de format en fitxers grans.
- Separar canvis per dominis amb write-set disjunt.
- Afegir tests petits i caracteritzadors, no calendaritzacions completes de 20
  minuts.

## 2. Estat actual resumit

Fitxers principals actuals:

- `app.py`: API FastAPI, jobs, Redis, validacio de `file_path`, download.
- `main.py`: monolit d'aplicacio. Ingesta, normalitzacio, CASA/FORA,
  segona fase, bucle per categories, KPIs, Excel, JSON.
- `assignacions.py`: motor d'assignacio legacy. Costos, hungares, reparacions,
  swaps locals, fairness.
- `consulta_resultats.py`: client i parser CEEB.
- `logs.py`: Redis/logs i constants de calendaris `primera_fase` i
  `segona_fase`.
- `scripts/plot_kpis.py`: generacio de grafics a partir del JSON de KPIs.

Problema principal:

`main.py` i `assignacions.py` concentren massa responsabilitats i fan dificil
introduir motors nous, auditar decisions o integrar el sistema en Django sense
arrossegar infraestructura i reporting dins el nucli.

## 3. Arquitectura objectiu

Estructura objectiu proposada:

```text
calendaritzacions/
  __init__.py

  domain/
    __init__.py
    phases.py
    models.py
    requests.py
    normalization.py
    errors.py

  ingestion/
    __init__.py
    excel_reader.py
    validators.py
    ids.py
    modalitat_map.py

  engine/
    __init__.py
    base.py
    registry.py
    config.py
    legacy/
      __init__.py
      service.py
      home_away.py
      group_sizing.py
      slots.py
      costs.py
      matrix.py
      hungarian.py
      repairs.py
      local_search.py
      fairness.py
      result_builder.py
    variants/
      __init__.py
      README.md

  second_phase/
    __init__.py
    ceeb_client.py
    classifications.py
    team_matching.py
    cache.py

  analysis/
    __init__.py
    indicators.py
    incidents.py
    fairness_report.py
    run_audit.py
    explainability.py

  reporting/
    __init__.py
    excel_writer.py
    json_writer.py
    plot_kpis.py

  application/
    __init__.py
    use_cases.py
    progress.py
    storage.py
    compatibility.py

interfaces/
  fastapi_app.py
  cli.py

tests/
  unit/
  integration/
  characterization/
  fixtures/
```

Durant la migracio es pot crear primer el paquet `calendaritzacions/` sense
esborrar els fitxers top-level. Els fitxers existents poden importar de la nova
estructura progressivament.

## 4. Contractes principals

### 4.1. `PhaseConfig`

La diferencia entre primera i segona fase no ha d'estar escampada com
`segona_fase_bool`. Ha de quedar concentrada en un objecte de configuracio:

```python
@dataclass(frozen=True)
class PhaseConfig:
    code: str
    name: str
    calendar: list[list[tuple[int, int]]]
    uses_classifications: bool
    classification_source: str | None = None
    ranking_balance_mode: str | None = None
```

Instancies inicials:

- `FIRST_PHASE`: usa calendari de 7 jornades i no consulta classificacions.
- `SECOND_PHASE`: usa calendari de 14 jornades i activa enriquiment amb CEEB.

### 4.2. `CalendarizationEngine`

Tots els motors presents i futurs han d'implementar el mateix contracte:

```python
class CalendarizationEngine(Protocol):
    name: str

    def run(
        self,
        input_data: NormalizedInput,
        config: EngineConfig,
        progress: ProgressReporter | None = None,
    ) -> EngineResult:
        ...
```

El motor actual sera `legacy`.

Motors futurs encaixaran a `calendaritzacions/engine/variants/` i no haurien de
tocar ingesta, reporting, API ni Django.

### 4.3. `CalendarizationRunResult`

El cas d'us d'aplicacio ha de retornar una estructura completa:

```python
@dataclass
class CalendarizationRunResult:
    excel_path: str
    kpis_path: str
    audit_path: str | None
    result_data: EngineResult
    warnings: list[str]
    logs: list[str]
```

En la primera etapa, `result_data` pot continuar contenint DataFrames per no
forcar una migracio total.

## 5. Estrategia de tests realista

El proces complet pot durar uns 20 minuts. Per tant, no es pot convertir una
calendaritzacio real en test habitual.

S'han de crear quatre nivells de verificacio:

### 5.1. Tests unitaris rapids

Objectiu: menys d'1 segon per test.

Candidats:

- normalitzacio de noms.
- parsing de `Num. sorteig`.
- generacio d'IDs.
- patrons casa/fora per numero.
- calcul de diferencies de jornades.
- `crear_grups_equilibrats`.
- `build_slots`.
- `add_dummies`.
- `level_entropy`, `day_entropy`, `position_entropy`.
- validacions de CASA/FORA incoherents.

### 5.2. Tests de categoria petita

Objectiu: provar el motor legacy amb 8, 10, 14 o 16 equips.

No han de consultar CEEB ni escriure Excels grans.

### 5.3. Tests de caracteritzacio

Objectiu: congelar comportament actual.

Entrades petites o mitjanes anonimitzades han de guardar:

- output simplificat.
- KPIs essencials.
- incidencies principals.
- assignacions per equip.

Si el refactor canvia aquests snapshots, s'ha d'explicar per que.

### 5.4. Golden runs manuals o nightly

Objectiu: executar una calendaritzacio real llarga fora del cicle normal.

No han de ser obligatoris en cada canvi. Poden viure com a script o job manual:

- `tests/characterization/golden_run_manifest.json`
- `scripts/run_golden_calendarization.py`

## 6. Fase 0: congelar i caracteritzar la V1

### Objectiu

Abans de moure codi, crear punts de comparacio per assegurar que el comportament
no canvia.

### Fitxers a tocar

- `tests/characterization/`
- `tests/fixtures/`
- opcionalment `docs/`

### Tasques

1. Crear fixtures petits amb categories sintetiques.
2. Crear helper de comparacio d'assignacions sense exigir igualtat de format
   Excel.
3. Capturar sortides del motor actual per:
   - una categoria exactament de 8 equips;
   - una categoria amb dummies;
   - dues categories amb mateixa entitat per validar fairness;
   - cas amb peticions `CASA/FORA`;
   - cas de segona fase amb classificacio mockejada.
4. Documentar quines comparacions son estrictes i quines son tolerants.

### Criteris d'acceptacio

- Els tests no executen calendaritzacions de 20 minuts.
- No hi ha consultes de xarxa.
- Els snapshots son prou petits per revisar-los en PR.

### Subagent suggerit

`AGENT-00-characterization`

Write-set:

- `tests/characterization/**`
- `tests/fixtures/**`
- `docs/**` nomes si cal documentar fixtures.

No ha de tocar codi de produccio.

## 7. Fase 1: crear el paquet i la facana de compatibilitat

### Objectiu

Introduir l'estructura nova sense moure encara logica pesada.

### Fitxers nous

- `calendaritzacions/__init__.py`
- `calendaritzacions/application/use_cases.py`
- `calendaritzacions/application/compatibility.py`
- `calendaritzacions/application/progress.py`
- `calendaritzacions/domain/errors.py`
- `calendaritzacions/engine/base.py`
- `calendaritzacions/engine/registry.py`
- `calendaritzacions/engine/config.py`

### Contingut

`application/compatibility.py`:

- wrapper inicial que crida `main.process_excel(...)`.
- mante la signatura compatible.

`application/use_cases.py`:

- `process_calendarization(...)`, inicialment delegant a compatibilitat.

`engine/base.py`:

- protocol o classe abstracta `CalendarizationEngine`.

`engine/registry.py`:

- registre de motors per nom.
- de moment nomes `legacy`.

`application/progress.py`:

- interfici de progres independent de Redis.

### Criteris d'acceptacio

- `process_excel(...)` continua funcionant.
- L'API actual pot continuar important de `main.py`.
- Encara no hi ha moviment de logica gran.

### Subagent suggerit

`AGENT-01-package-shell`

Write-set:

- `calendaritzacions/application/**`
- `calendaritzacions/domain/errors.py`
- `calendaritzacions/engine/base.py`
- `calendaritzacions/engine/registry.py`
- `calendaritzacions/engine/config.py`

## 8. Fase 2: domini pur i fases

### Objectiu

Treure constants i funcions pures de domini dels fitxers acoblats.

### Fitxers desti

- `calendaritzacions/domain/phases.py`
- `calendaritzacions/domain/requests.py`
- `calendaritzacions/domain/normalization.py`
- `calendaritzacions/domain/models.py`

### Funcions candidates

De `logs.py`:

- `primera_fase`
- `segona_fase`

De `main.py` i `assignacions.py`:

- `parse_int`
- `normalize_seed_value`
- `_request_type`
- `_request_display_code`
- `_expected_seed`
- `_normalize_team_key`
- `_normalize_entity_name`
- `_level_idx`
- `_level_letter`
- `_pairwise_avg_distance`

De `assignacions.py`:

- `build_disposicions`

### Regla de compatibilitat

Els fitxers antics poden reexportar o importar les funcions noves, pero no s'ha
de canviar la semantica. Si hi ha dues versions duplicades, primer s'ha de crear
un test que demostri que fan el mateix o decidir explicitament quina es la font
de veritat.

### Criteris d'acceptacio

- `logs.py` deixa de ser la font conceptual dels calendaris, encara que pugui
  reexportar temporalment.
- Les funcions pures tenen tests unitaris.
- Cap test ha de tocar Redis, Excel ni xarxa.

### Subagent suggerit

`AGENT-02-domain`

Write-set:

- `calendaritzacions/domain/**`
- tests unitaris associats.

Evitar tocar `main.py` i `assignacions.py` excepte imports minims si la fase ho
requereix.

## 9. Fase 3: ingesta, validacio i IDs

### Objectiu

Separar la preparacio de dades del proces d'assignacio.

### Fitxers desti

- `calendaritzacions/ingestion/excel_reader.py`
- `calendaritzacions/ingestion/validators.py`
- `calendaritzacions/ingestion/ids.py`
- `calendaritzacions/ingestion/modalitat_map.py`

### Responsabilitats

`excel_reader.py`:

- llegir Excel.
- eventualment llegir CSV si encara cal.
- retornar DataFrame sense iniciar cap proces de negoci.

`validators.py`:

- columnes minimes.
- valors obligatoris.
- incoherencies `CASA/FORA` per mateix equip.
- errors estructurats en lloc de `sys.exit`.

`ids.py`:

- generacio d'`Id` estable.
- normalitzacio previa usada per hash.

`modalitat_map.py`:

- carregar `map_modalitat_nom.csv`.
- validar que una modalitat/categoria existeix.

### Funcions candidates

De `main.py`:

- part inicial de `processar_dades_2`.
- `_mk_id` intern.
- validacio de columnes.
- comprovacio de conflictes CASA/FORA.
- lectura de `map_modalitat_nom.csv`.

### Criteris d'acceptacio

- La normalitzacio genera exactament els mateixos IDs que abans.
- Els errors encara es poden transformar en missatges compatibles amb l'API.
- Les validacions tenen tests petits.

### Subagent suggerit

`AGENT-03-ingestion`

Write-set:

- `calendaritzacions/ingestion/**`
- tests unitaris d'ingesta.

## 10. Fase 4: resolucio global CASA/FORA

### Objectiu

Extreure una de les parts de domini mes importants: la conversio de peticions
textuals `CASA/FORA` a numeros concrets.

### Fitxer desti

- `calendaritzacions/engine/legacy/home_away.py`

### Responsabilitats

- construir `entitats_links`.
- definir i usar duples:
  - `(1, 5)`
  - `(6, 2)`
  - `(7, 3)`
  - `(8, 4)`
- ordenar entitats per criticitat.
- calcular preferencies de duples.
- fer fallback deterministic per hash.
- retornar:
  - `equip_to_num_sorteig`
  - `entitats_assigned`
  - `duples_casa_fora`
  - traça explicativa.

### Contracte suggerit

```python
@dataclass
class HomeAwayResolution:
    equip_to_num_sorteig: dict[str, int]
    entitats_assigned: dict[str, int]
    duples_casa_fora: list[tuple[int, int]]
    entity_links: dict[str, set[str]]
    explanation_rows: list[dict]
```

### Criteris d'acceptacio

- Mateixos mappings que la V1 per fixtures.
- Tests per:
  - entitat amb CASA;
  - entitat amb FORA;
  - entitat amb CASA i FORA en equips diferents;
  - `Pista joc` com a clau;
  - fallback hash.

### Subagent suggerit

`AGENT-04-home-away`

Write-set:

- `calendaritzacions/engine/legacy/home_away.py`
- tests associats.

## 11. Fase 5: motor legacy per categoria

### Objectiu

Partir `assignacions.py` en moduls petits mantenint `assignar_grups_hungares`
com a facana compatible.

### Fitxers desti i funcions

`engine/legacy/group_sizing.py`:

- `crear_grups_equilibrats`

`engine/legacy/slots.py`:

- `build_slots`
- `add_dummies`
- helpers de conversio `Descans`

`engine/legacy/costs.py`:

- `cost_calc`
- `position_entropy`
- `level_entropy`
- `day_entropy`
- `recalcular_costos_base_sense_factors`

`engine/legacy/matrix.py`:

- `build_cost_matrix`

`engine/legacy/hungarian.py`:

- wrapper de `linear_sum_assignment`

`engine/legacy/repairs.py`:

- `check_feasibility_entity`
- `build_groups_from_assignment`
- `entity_conflicts`
- `repair_by_hungarian_per_position`

`engine/legacy/fairness.py`:

- `actualitzar_costos_entitat`
- `rebuild_entitat_factor`
- analisi de fairness acumulada si es mantingui dins motor

`engine/legacy/local_search.py`:

- `homogeneitzar_nivell`
- `homogeneitzar_costs`

`engine/legacy/result_builder.py`:

- construccio del DataFrame final per categoria.
- calcul de `Diferencies jornades`.
- ordenacio final de grups per nivell.

`engine/legacy/service.py`:

- `LegacyCalendarizationEngine`.
- orquestracio del motor per categoria.
- facana equivalent a `assignar_grups_hungares`.

### Regla critica

Primer moure funcions sense canviar-les. Despres netejar.

No s'ha d'intentar "arreglar" en aquesta fase:

- pesos aparentment no usats.
- dependencia d'ordre de categories.
- heuristiques locals.
- gestio d'impossibilitats.

Tot aixo es comportament V1 i ha de quedar preservat.

### Criteris d'acceptacio

- `assignar_grups_hungares(...)` pot continuar existint com a wrapper.
- Fixtures petites retornen la mateixa assignacio que abans.
- Cap modul del motor legacy importa FastAPI, Redis ni escriptura Excel.

### Subagents suggerits

Es pot dividir en diversos subagents amb write-set disjunt:

- `AGENT-05A-legacy-basic`: `group_sizing.py`, `slots.py`, tests.
- `AGENT-05B-legacy-costs`: `costs.py`, `matrix.py`, tests.
- `AGENT-05C-legacy-repairs`: `repairs.py`, `hungarian.py`, tests.
- `AGENT-05D-legacy-search`: `local_search.py`, `fairness.py`, tests.
- `AGENT-05E-legacy-result`: `result_builder.py`, `service.py`, tests.

Els subagents no han d'editar els mateixos fitxers.

## 12. Fase 6: segona fase i CEEB

### Objectiu

Separar la integracio externa de la logica del motor.

### Fitxers desti

- `calendaritzacions/second_phase/ceeb_client.py`
- `calendaritzacions/second_phase/classifications.py`
- `calendaritzacions/second_phase/team_matching.py`
- `calendaritzacions/second_phase/cache.py`

### Responsabilitats

`ceeb_client.py`:

- `fetch_ceeb_async`.
- credencials des d'entorn, no hardcodejades en una fase posterior.
- timeout i errors estructurats.

`classifications.py`:

- `parse_ceeb_xml`.
- `xml_to_dataframe`.
- normalitzacio del format de classificacions.

`team_matching.py`:

- `_normalize_team_key`.
- `_get_team_position`.
- equips no trobats.
- equips classificats no utilitzats.

`cache.py`:

- cache opcional per evitar consultes repetides.
- no necessari en primera extraccio si complica.

### Criteris d'acceptacio

- Primera fase no importa cap modul CEEB.
- Segona fase pot mockejar classificacions en tests.
- Les credencials no han d'apareixer en nous tests ni nous docs operatius.

### Subagent suggerit

`AGENT-06-second-phase`

Write-set:

- `calendaritzacions/second_phase/**`
- tests associats.

## 13. Fase 7: analisi exhaustiva i auditoria del run

### Objectiu

Cada calendaritzacio ha d'anar acompanyada d'un estudi exhaustiu del que ha
passat. Els KPIs actuals son bons, pero insuficients per auditar decisions.

### Fitxers desti

- `calendaritzacions/analysis/indicators.py`
- `calendaritzacions/analysis/incidents.py`
- `calendaritzacions/analysis/fairness_report.py`
- `calendaritzacions/analysis/run_audit.py`
- `calendaritzacions/analysis/explainability.py`

### Que moure del codi actual

De `main.py`:

- `_build_indicator_tables`
- `analitzar_equitabilitat_costos`
- `_with_metric_descriptions`
- `_df_records`
- `_json_default`
- helpers de nivells i incidencies.

### Artefactes nous recomanats

A mes de `kpis_*.json`, generar:

`run_manifest.json`:

- id del run.
- input file.
- hash de l'input.
- fase.
- motor.
- versio/config del motor.
- data inici/final.
- durada total.
- durada per etapa.

`input_validation.json`:

- columnes detectades.
- columnes requerides.
- avisos.
- errors.
- files descartades si n'hi ha.
- valors no interpretables.

`home_away_resolution.json`:

- entitats amb peticions textuals.
- links calculats.
- preferencies de duples.
- dupla final assignada.
- equips afectats.

`solver_trace.json`:

- per categoria:
  - equips reals.
  - repartiment de grups.
  - slots totals.
  - dummies.
  - conflictes inicials.
  - conflictes finals.
  - cost inicial.
  - cost final si es pot calcular.
  - reparacions.
  - swaps acceptats.
  - temps de solver.

`constraints_report.json`:

- restriccions dures detectades.
- restriccions impossibles.
- preferencies no complertes.
- severitat.

`fairness_timeline.json`:

- cost acumulat per entitat despres de cada categoria.
- entitats mes perjudicades.
- cost normalitzat per equip.

`explanations.json`:

- per equip:
  - peticio original.
  - tipus de peticio.
  - numero esperat.
  - numero assignat.
  - grup.
  - diferencies de jornades.
  - motiu principal d'incidencia si es pot inferir.

`performance.json`:

- temps de lectura.
- temps resolucio CASA/FORA.
- temps CEEB.
- temps per categoria.
- temps Excel.
- categories mes lentes.

### Criteris d'acceptacio

- Els artefactes han de ser JSON estructurats i consumibles per Django.
- L'Excel continua sent sortida humana, no unica font de veritat.
- Si falta una dada d'auditoria, el camp pot ser `null` o buit; no ha de trencar
  el run.

### Subagent suggerit

`AGENT-07-analysis-audit`

Write-set:

- `calendaritzacions/analysis/**`
- tests associats.

## 14. Fase 8: reporting Excel, JSON i plots

### Objectiu

Separar presentacio de negoci.

### Fitxers desti

- `calendaritzacions/reporting/excel_writer.py`
- `calendaritzacions/reporting/json_writer.py`
- `calendaritzacions/reporting/plot_kpis.py`

### Que moure

De `main.py`:

- `_format_diffs_excel`
- `_col_letter`
- `_auto_fit_worksheet_columns`
- `_write_df_block`
- tot el bloc `pd.ExcelWriter(...)`.

De `scripts/plot_kpis.py`:

- es pot moure o reexportar com a modul de reporting.
- mantenir CLI compatible.

### Criteris d'acceptacio

- Mateixos noms de fulls Excel que abans.
- Mateixes columnes principals.
- Mateix JSON de KPIs o superconjunt compatible.
- `scripts/plot_kpis.py` continua funcionant.

### Subagent suggerit

`AGENT-08-reporting`

Write-set:

- `calendaritzacions/reporting/**`
- `scripts/plot_kpis.py` nomes per wrapper si cal.
- tests de reporting.

## 15. Fase 9: aplicacio, jobs i Django-readiness

### Objectiu

Fer que l'orquestracio del proces no depengui de FastAPI ni Redis.

### Fitxers desti

- `calendaritzacions/application/use_cases.py`
- `calendaritzacions/application/progress.py`
- `calendaritzacions/application/storage.py`
- `interfaces/fastapi_app.py`
- futur `django_app/tasks.py`

### Responsabilitats

`use_cases.py`:

- `process_calendarization(input_path, phase, engine, output_dir, progress)`.
- orquestra:
  - lectura.
  - validacio.
  - enriquiment segona fase.
  - motor.
  - analisi.
  - reporting.

`progress.py`:

- `ProgressReporter`.
- implementacions:
  - `NoopProgressReporter`
  - `RedisProgressReporter`
  - futura `DjangoJobProgressReporter`

`storage.py`:

- paths de sortida.
- evitar col·lisions.
- moure/copiar resultats.

`interfaces/fastapi_app.py`:

- migracio neta de `app.py`.
- sense logica de calendaritzacio.

### Django futur

El model Django hauria de guardar:

- fitxer d'entrada.
- fase.
- motor.
- estat.
- progres.
- paths dels artefactes.
- configuracio snapshot.
- durada.
- errors.

La task Django nomes hauria de fer:

```python
phase = phase_registry[job.phase]
engine = engine_registry[job.engine]
result = process_calendarization(
    input_path=job.input_file.path,
    phase=phase,
    engine=engine,
    output_dir=job.output_dir,
    progress=DjangoJobProgressReporter(job),
)
```

### Criteris d'acceptacio

- FastAPI queda com una interfici substituible.
- Django pot integrar el cas d'us sense importar `main.py`.
- Els jobs no coneixen detalls del solver.

### Subagent suggerit

`AGENT-09-application`

Write-set:

- `calendaritzacions/application/**`
- `interfaces/**`
- `app.py` nomes en una fase final de migracio.

## 16. Fase 10: variants de motor

### Objectiu

Un cop el legacy estigui encapsulat, permetre motors nous sense tocar la resta.

### Ubicacio

- `calendaritzacions/engine/variants/`

### Contracte

Cada variant ha de:

- implementar `CalendarizationEngine`.
- acceptar `NormalizedInput`.
- acceptar `EngineConfig`.
- retornar `EngineResult`.
- generar traça comparable amb legacy.

### Variants candidates

`greedy_fast`:

- motor rapid per previsualitzacions.
- no busca optimitzacio profunda.
- util per UI.

`legacy_plus`:

- mateix motor base que legacy amb millores opcionals activades per config.
- no substitueix legacy.

`cp_sat`:

- model de restriccions amb OR-Tools CP-SAT.
- separa restriccions dures de preferencies.

`milp`:

- model d'optimitzacio matematica si es vol una funcio objectiu global.

`hybrid`:

- solucio inicial legacy i postprocessat amb un solver nou.

### Criteris d'acceptacio

- Cap variant nova pot canviar `legacy`.
- Comparador de motors:
  - mateix input.
  - mateix reporting.
  - taula de qualitat.
  - durada.
  - incidencies.
  - fairness.

### Subagent suggerit

`AGENT-10-engine-variants`

Write-set:

- `calendaritzacions/engine/variants/**`
- tests propis.

No comencar aquesta fase fins que `legacy` tingui contracte estable.

## 17. Ordre recomanat de treball

Ordre segur:

1. Fase 0: caracteritzacio.
2. Fase 1: paquet i facanes.
3. Fase 2: domini pur.
4. Fase 3: ingesta.
5. Fase 4: CASA/FORA.
6. Fase 5: motor legacy per categoria.
7. Fase 6: segona fase.
8. Fase 7: analisi i auditoria.
9. Fase 8: reporting.
10. Fase 9: aplicacio i Django-readiness.
11. Fase 10: variants de motor.

Treball paralel possible:

- Fase 0 pot anar en paralel amb Fase 1.
- Fase 2 i Fase 3 poden anar en paralel si no editen `main.py`.
- Fase 7 i Fase 8 poden preparar esquelets mentre Fase 5 avanca.
- Fase 6 pot anar separada si usa mocks i no toca el motor.

No treballar en paralel:

- dos agents editant `assignacions.py`.
- dos agents editant el bloc Excel de `main.py`.
- variants de motor abans de tenir `EngineResult` estable.

## 18. Matriu de propietat per subagents

| Agent | Domini | Pot tocar | No pot tocar |
| --- | --- | --- | --- |
| AGENT-00 | Characterization | `tests/characterization`, `tests/fixtures` | motor/reporting |
| AGENT-01 | Package shell | `calendaritzacions/application`, `engine/base` | logica legacy |
| AGENT-02 | Domain | `calendaritzacions/domain` | Excel, API |
| AGENT-03 | Ingestion | `calendaritzacions/ingestion` | solver |
| AGENT-04 | CASA/FORA | `engine/legacy/home_away.py` | Excel, CEEB |
| AGENT-05A | Slots/grups | `group_sizing.py`, `slots.py` | costs/search |
| AGENT-05B | Costs/matrix | `costs.py`, `matrix.py` | reporting |
| AGENT-05C | Repairs | `repairs.py`, `hungarian.py` | local_search |
| AGENT-05D | Search/fairness | `local_search.py`, `fairness.py` | result_builder |
| AGENT-05E | Legacy service | `service.py`, `result_builder.py` | reporting Excel |
| AGENT-06 | Segona fase | `second_phase/**` | legacy core |
| AGENT-07 | Analysis/audit | `analysis/**` | Excel writer |
| AGENT-08 | Reporting | `reporting/**`, plot wrapper | solver |
| AGENT-09 | Application | `application/**`, `interfaces/**` | engine internals |
| AGENT-10 | Variants | `engine/variants/**` | legacy |

## 19. Guia de migracio de funcions actuals

### `main.py`

Cap a `domain/`:

- `_normalize_team_key`
- `parse_int`
- `normalize_seed_value`
- `_request_type`
- `_request_display_code`
- `_expected_seed`
- `_level_idx`
- `_level_letter`
- `_pairwise_avg_distance`

Cap a `ingestion/`:

- validacio de columnes.
- generacio d'IDs.
- lectura de `map_modalitat_nom.csv`.
- validacio CASA/FORA incompatible.

Cap a `engine/legacy/home_away.py`:

- construccio `entitats_links`.
- preferencies de duples.
- assignacio `equip_to_num_sorteig`.
- `entitats_assigned`.

Cap a `second_phase/`:

- consulta de classificacions.
- matching d'equips.
- missing classifications.
- unused classification teams.

Cap a `analysis/`:

- `_build_indicator_tables`.
- `analitzar_equitabilitat_costos`.
- construccio d'incidencies.
- resum nivells.

Cap a `reporting/`:

- `_format_diffs_excel`.
- helpers d'Excel.
- escriptura de fulls.
- export JSON.

Cap a `application/`:

- `process_excel`.
- orquestracio global de `processar_dades_2`.

### `assignacions.py`

Cap a `domain/phases.py`:

- dependencia de `primera_fase` ha de venir de `PhaseConfig`.

Cap a `engine/legacy/group_sizing.py`:

- `crear_grups_equilibrats`.

Cap a `engine/legacy/slots.py`:

- `build_slots`.
- `add_dummies`.

Cap a `engine/legacy/costs.py`:

- `cost_calc`.
- `build_disposicions`.
- `position_entropy`.
- `level_entropy`.
- `day_entropy`.
- `recalcular_costos_base_sense_factors`.

Cap a `engine/legacy/matrix.py`:

- `build_cost_matrix`.

Cap a `engine/legacy/repairs.py`:

- `check_feasibility_entity`.
- `build_groups_from_assignment`.
- `entity_conflicts`.
- `repair_by_hungarian_per_position`.

Cap a `engine/legacy/fairness.py`:

- `actualitzar_costos_entitat`.
- `rebuild_entitat_factor`.

Cap a `engine/legacy/local_search.py`:

- `homogeneitzar_nivell`.
- `homogeneitzar_costs`.

Cap a `engine/legacy/service.py`:

- `assignar_grups_hungares` com a facana.

### `logs.py`

Cap a `application/progress.py`:

- `push_log` com implementacio Redis de progres.

Cap a `application/storage.py` o infra futura:

- `_write_job`.
- `_read_job`.

Cap a `domain/phases.py`:

- `primera_fase`.
- `segona_fase`.

### `consulta_resultats.py`

Cap a `second_phase/ceeb_client.py`:

- `fetch_ceeb_async`.
- `fetch_async` si encara s'usa.

Cap a `second_phase/classifications.py`:

- `parse_team`.
- `parse_ceeb_xml`.
- `xml_to_dataframe`.

Cap a `second_phase/team_matching.py`:

- normalitzacio i matching amb equips d'input.

### `app.py`

Cap a `interfaces/fastapi_app.py`:

- endpoints.
- validacio de path.
- download.

Cap a `application/progress.py`:

- progres Redis.

Cap a `application/use_cases.py`:

- crida al processament.

## 20. Compatibilitat temporal

Durant la migracio, s'han de mantenir aquests punts:

- `from main import process_excel` continua funcionant.
- `from assignacions import assignar_grups_hungares` continua funcionant.
- `python main.py input.xlsx` continua funcionant si es considera part del
  contracte operatiu.
- `scripts/plot_kpis.py` continua funcionant com a script.

Quan una funcio es mogui, el fitxer antic pot quedar aixi:

```python
from calendaritzacions.engine.legacy.service import assignar_grups_hungares
```

o, si cal preservar compatibilitat exacta:

```python
def assignar_grups_hungares(*args, **kwargs):
    return legacy_assignar_grups_hungares(*args, **kwargs)
```

## 21. Gestio d'errors

La V1 usa `sys.exit()` en punts de negoci. No s'ha de canviar tot de cop, pero
la direccio ha de ser:

```python
class CalendarizationError(Exception): ...
class InputValidationError(CalendarizationError): ...
class InfeasibleCalendarizationError(CalendarizationError): ...
class ExternalClassificationError(CalendarizationError): ...
```

La capa d'aplicacio tradueix excepcions a:

- estat failed del job.
- missatge per usuari.
- entrada a `run_audit`.

El motor no hauria de saber res de FastAPI, Redis o Django.

## 22. Observabilitat i progres

El proces llarg necessita progres mes estructurat que missatges lliures.

Contracte recomanat:

```python
progress.emit(
    stage="legacy_solver.category",
    message="Processant categoria ...",
    pct=62,
    data={"category": categoria, "teams": len(df_cat)}
)
```

Etapes estandard:

- `input.read`
- `input.validate`
- `input.normalize`
- `home_away.resolve`
- `second_phase.fetch`
- `second_phase.match`
- `engine.start`
- `engine.category`
- `analysis.build`
- `reporting.excel`
- `reporting.json`
- `storage.finalize`

## 23. Decisions que NO s'han de prendre durant la desmonolititzacio

Per evitar regressions, deixar fora de la primera migracio:

- canviar pesos del solver.
- substituir l'hongares.
- fer fairness global no seqüencial.
- canviar duples CASA/FORA.
- eliminar dummies.
- canviar ordenacio final de grups.
- modificar noms de fulls Excel.
- canviar matching CEEB per fuzzy matching nou.

Aquestes millores poden venir despres com a variants de motor o opcions
configurables.

## 24. Definicio de "fet"

La desmonolititzacio es pot considerar completada quan:

- `main.py` ja no conte logica de negoci substancial, nomes compatibilitat o CLI.
- `assignacions.py` ja no conte el motor real, nomes wrapper legacy.
- `logs.py` no conte calendaris ni decisions de domini.
- El motor legacy es pot executar sense FastAPI, Redis ni Excel.
- El reporting es pot executar a partir d'un `EngineResult`.
- La primera i segona fase es decideixen per `PhaseConfig`.
- Hi ha artefactes d'auditoria per cada run.
- Django pot cridar `process_calendarization(...)` sense importar `main.py`.
- Existeix un registre de motors i `legacy` es un motor mes.

## 25. Primer paquet de treball recomanat

Per arrencar sense risc:

1. Crear `calendaritzacions/domain/phases.py` amb constants copiades.
2. Crear `calendaritzacions/application/compatibility.py` que delegui a
   `main.process_excel`.
3. Crear `calendaritzacions/engine/base.py` i `registry.py`.
4. Crear tests unitaris de patrons de fase i parsing de peticions.
5. Crear un fixture petit de caracteritzacio per una categoria.

Aquest primer paquet no hauria de canviar cap resultat i dona una base comuna
per a la resta de subagents.

## 26. Estat actual del codi

Actualitzat despres de la iteracio de particio de `assignacions.py`.

### 26.1. Ja fet

S'ha creat l'estructura base del paquet:

- `calendaritzacions/application/`
- `calendaritzacions/domain/`
- `calendaritzacions/engine/`
- `calendaritzacions/engine/legacy/`
- `calendaritzacions/ingestion/`

`assignacions.py` ja no conte la implementacio del motor. Ara es una facana
compatible que reexporta els simbols publics legacy.

La implementacio s'ha mogut a:

- `calendaritzacions/engine/legacy/utils.py`
- `calendaritzacions/engine/legacy/group_sizing.py`
- `calendaritzacions/engine/legacy/slots.py`
- `calendaritzacions/engine/legacy/costs.py`
- `calendaritzacions/engine/legacy/matrix.py`
- `calendaritzacions/engine/legacy/repairs.py`
- `calendaritzacions/engine/legacy/fairness.py`
- `calendaritzacions/engine/legacy/local_search.py`
- `calendaritzacions/engine/legacy/service.py`

També existeix:

- `calendaritzacions/engine/legacy/home_away.py`

Aquest modul conte una extraccio separada de la resolucio `CASA/FORA`, pero
encara no esta connectat al flux de `main.py`.

### 26.2. Compatibilitat preservada

Continuen funcionant els imports legacy:

```python
from assignacions import assignar_grups_hungares
import assignacions
```

`main.py` continua important `assignar_grups_hungares` des de `assignacions.py`,
pero ara aquesta funcio arriba des de `calendaritzacions.engine.legacy.service`.

No s'ha canviat encara l'orquestracio de `main.py`.

### 26.3. Verificacio executada

S'ha validat amb:

```powershell
docker compose run --rm app python -m unittest discover -s tests
```

Resultat:

```text
Ran 35 tests
OK
```

També s'ha executat un smoke d'import:

```powershell
docker compose run --rm app python -c "from assignacions import assignar_grups_hungares; import assignacions; import main; print('ok')"
```

Resultat:

```text
ok
```

### 26.4. Que queda pendent

La desmonolititzacio del motor legacy ja esta feta a nivell de fitxers. Despres
de la particio conservadora de `main.py`, la implementacio del pipeline legacy
viu a:

- `calendaritzacions/application/legacy_pipeline.py`

I `main.py` ha quedat com a facana compatible per preservar:

- `from main import process_excel`
- `import main`
- `python main.py ...`

Encara queda:

- moure KPIs i incidencies a `calendaritzacions/analysis/`;
- moure Excel/JSON a `calendaritzacions/reporting/`;
- moure segona fase/CEEB a `calendaritzacions/second_phase/`;
- fer que `process_calendarization(...)` orquestri el pipeline nou sense delegar
  directament al pipeline legacy complet;
- deixar `calendaritzacions/application/legacy_pipeline.py` nomes com a capa
  temporal o wrapper intern.

### 26.5. Riscos residuals

Els tests actuals cobreixen helpers, imports, resolucio `CASA/FORA`, un smoke
petit de `assignar_grups_hungares` i imports de la facana `main.py`, pero no
substitueixen una calendaritzacio real de 20 minuts. Abans de buidar
`legacy_pipeline.py` en moduls d'analisi/reporting/segona fase, cal mantenir
proves petites i afegir algun fixture de caracteritzacio de pipeline parcial.

## 27. Estat despres de partir `main.py`

### 27.1. Ja fet

`main.py` ja no conte la implementacio del pipeline. Ara conte una facana que:

- reexporta el contingut de `calendaritzacions.application.legacy_pipeline`;
- conserva imports historics com `from main import process_excel`;
- conserva l'execucio CLI amb `python main.py ...` mitjancant `runpy`.

La implementacio legacy de l'antic `main.py` s'ha mogut a:

- `calendaritzacions/application/legacy_pipeline.py`

`calendaritzacions/application/compatibility.py` ja no importa `main`. Ara
delega directament a `calendaritzacions.application.legacy_pipeline.process_excel`.

### 27.2. Verificacio executada

S'ha validat amb:

```powershell
docker compose run --rm app python -m unittest discover -s tests
```

Resultat:

```text
Ran 35 tests
OK
```

Smoke d'import:

```powershell
docker compose run --rm app python -c "from main import process_excel, processar_dades_2, crear_grups_equilibrats; import main; from calendaritzacions.application.compatibility import process_excel as compat; print('ok')"
```

Resultat:

```text
ok
```

### 27.3. Pendent real despres d'aquest punt

La capa grossa que queda no es `main.py` com a fitxer, sino
`calendaritzacions/application/legacy_pipeline.py` com a pipeline legacy complet.

Cal anar buidant aquest fitxer cap a:

- `calendaritzacions/second_phase/` per CEEB i classificacions;
- `calendaritzacions/analysis/` per KPIs, incidencies, fairness i auditoria;
- `calendaritzacions/reporting/` per Excel, JSON i plots;
- `calendaritzacions/application/use_cases.py` per l'orquestracio final.

## 28. Estat despres d'extreure helpers de `legacy_pipeline.py`

### 28.1. Ja fet

S'han mogut helpers top-level de l'antic `main.py`/`legacy_pipeline.py` a
moduls dedicats, sense canviar el flux intern de `processar_dades_2`.

Nous moduls:

- `calendaritzacions/analysis/indicators.py`
- `calendaritzacions/reporting/excel_writer.py`
- `calendaritzacions/second_phase/matching.py`
- `calendaritzacions/application/legacy_helpers.py`

Responsabilitats mogudes:

- `analysis/indicators.py`:
  - `_build_indicator_tables`
  - `analitzar_equitabilitat_costos`
  - helpers de peticions, nivells, JSON i descripcions de metriques

- `reporting/excel_writer.py`:
  - `_col_letter`
  - `_format_diffs_excel`
  - `_auto_fit_worksheet_columns`
  - `_write_df_block`

- `second_phase/matching.py`:
  - `_normalize_team_key`
  - `_get_team_position`

- `application/legacy_helpers.py`:
  - `llegir_csv`
  - `obtenir_entitat`
  - `crear_grups_equilibrats`
  - `_normalize_entity_name`

`main.py` continua sent facana, pero ara reexporta tambe els helpers amb `_`
per preservar compatibilitat historica.

### 28.2. Verificacio executada

S'ha validat amb:

```powershell
docker compose run --rm app python -m unittest discover -s tests
```

Resultat:

```text
Ran 35 tests
OK
```

Smoke d'import de helpers moguts:

```powershell
docker compose run --rm app python -c "from main import process_excel, _build_indicator_tables, _format_diffs_excel, _get_team_position; print('ok')"
```

Resultat:

```text
ok
```

### 28.3. Que queda dins `legacy_pipeline.py`

Encara hi queda el nucli legacy llarg:

- `processar_dades_2`
- `process_excel`
- el bloc principal de resolucio CASA/FORA dins `processar_dades_2`
- la branca de segona fase que consulta CEEB
- el bucle per categories
- el bloc gran d'escriptura Excel
- la generacio del JSON de KPIs
- el CLI legacy sota `if __name__ == "__main__"`

Aquest fitxer ja es pot considerar una capa legacy encapsulada, pero encara no
es un pipeline net d'aplicacio.

### 28.4. Proxima iteracio recomanada

La propera iteracio hauria de separar `processar_dades_2` en blocs funcionals:

- `second_phase/classifications.py` per consultes CEEB i matching complet;
- `analysis/kpi_payload.py` per muntar el JSON de KPIs;
- `reporting/legacy_excel_writer.py` per encapsular tot el `pd.ExcelWriter`;
- `application/storage.py` per moure/copiar resultat a `MEDIA_ROOT`;
- `application/use_cases.py` per substituir gradualment la delegacio al legacy.

## 29. Estat despres de separar storage i segona fase

### 29.1. Ja fet

S'ha separat una part mes del nucli que quedava a `legacy_pipeline.py`.

Nous moduls:

- `calendaritzacions/application/storage.py`
- `calendaritzacions/second_phase/classifications.py`

Responsabilitats mogudes:

- `application/storage.py`:
  - `finalize_result_path`
  - moure/copiar el resultat final a `MEDIA_ROOT`
  - evitar sobreescriptura amb sufix hash
  - mantenir els missatges legacy dins `logs`

- `second_phase/classifications.py`:
  - `enrich_second_phase_classifications`
  - consulta CEEB
  - parsing de classificacions
  - matching d'equips
  - emplenat de `Posicio Classificacio`
  - recollida d'equips no trobats i equips de classificacio no utilitzats

`legacy_pipeline.py` continua orquestrant el flux, pero ara delega:

- storage final a `finalize_result_path`;
- enriquiment de segona fase a `enrich_second_phase_classifications`.

### 29.2. Verificacio executada

S'ha validat amb:

```powershell
docker compose run --rm app python -m unittest discover -s tests
```

Resultat:

```text
Ran 36 tests
OK
```

Tambe s'ha validat un smoke d'import:

```powershell
docker compose run --rm app python -c "from main import process_excel, processar_dades_2; from calendaritzacions.second_phase.classifications import enrich_second_phase_classifications; from calendaritzacions.application.storage import finalize_result_path; print('ok')"
```

### 29.3. Que queda dins `legacy_pipeline.py`

Encara hi queda:

- preparacio inicial del DataFrame dins `processar_dades_2`;
- resolucio `CASA/FORA` encara duplicada respecte a `engine/legacy/home_away.py`;
- bucle per categories i crida al motor legacy;
- preparacio de validacions per Excel;
- bloc gran `pd.ExcelWriter`;
- construccio final de `kpis_payload`;
- CLI legacy.

### 29.4. Proxima iteracio recomanada

Separar el reporting gros:

- moure tot el bloc `pd.ExcelWriter` a `calendaritzacions/reporting/legacy_excel_writer.py`;
- moure la construccio de `kpis_payload` a `calendaritzacions/analysis/kpi_payload.py`;
- fer que `processar_dades_2` retorni o construeixi un objecte intermedi de run
  en lloc de tenir Excel i JSON incrustats.

# Baseline d'Inscripcions

## Objectiu
- Fixar una baseline local, repetible i backend-only per al modul d'inscripcions.
- Mesurar el cami real Django + PostgreSQL del projecte dins Docker.
- Comparar canvis futurs amb la mateixa configuracio i els mateixos escenaris.

## Limits
- Aquesta Fase 0 no mesura navegador, Lighthouse ni latencia de xarxa externa.
- Aquesta Fase 0 no afegeix observabilitat persistent al runtime del modul.
- Aquesta Fase 0 no posa llindars automatics de temps a tests o CI.

## Entorn de referencia
- Servei Django: contenidor `web`
- Base de dades: PostgreSQL al contenidor `db`
- Execucio recomanada: contenidors ja calents, sense reiniciar `db` entre runs acceptats
- Comparacions valides: mateix stack Docker, mateix volum de dades, mateix nombre de warmups i repeats

## Prerequisits
```powershell
docker compose up -d db redis web
docker compose exec web python manage.py migrate
```

## Datasets canonics
- `small`: 40 inscripcions
- `medium`: 240 inscripcions
- `large`: 720 inscripcions

Tots tres datasets:
- usen competicions benchmark estables amb nom `__bench_inscripcions_<dataset>__`
- generen aparells individuals i team actius
- inclouen grups inicials parcials
- inclouen context d'equips natiu i assignacions parcials
- inclouen camps `extra` sintetis per exercitar filtres i sorting
- no creen fitxers media reals en aquesta fase

## Generacio de dades
```powershell
docker compose exec web python manage.py generate_inscripcions_benchmark_data --dataset all --replace
```

Arguments disponibles:
- `--dataset small|medium|large|all`
- `--replace`
- `--seed <int>`

## Escenaris mesurats
### `get_list`
- GET `inscripcions_list`
- sense filtres addicionals

### `filter_values`
- POST `inscripcions_filter_values`
- payload:

```json
{
  "column_code": "entitat",
  "filters": {}
}
```

### `sort_apply`
- POST `inscripcions_sort_apply`
- payload:

```json
{
  "sort_key": "entitat",
  "sort_dir": "asc",
  "scope": "all",
  "filters": {},
  "group_by": []
}
```

### `groups_preview`
- POST `groups_preview`
- payload:

```json
{
  "action": "create",
  "scope": "filtered",
  "filters": {},
  "selected_ids": []
}
```

### `groups_workspace`
- POST `groups_workspace`
- payload:

```json
{
  "filters": {},
  "page": 1,
  "page_size": 40
}
```

### `equips_workspace`
- POST `inscripcions_equips_workspace`
- payload:

```json
{
  "context_code": "native",
  "filters": {},
  "page": 1,
  "page_size": 40
}
```

### `media_match_preview`
- POST `inscripcions_media_match_preview`
- payload sintetitzat a partir dels noms de les inscripcions
- sense upload real

## Politica de warmup i repeats
- Baseline oficial: `1` warmup + `5` runs mesurats
- Els warmups no entren al resum agregat
- La baseline acceptada s'ha de prendre amb contenidors ja calents
- Els cold starts nomes es documenten manualment si cal

## Execucio benchmark
```powershell
docker compose exec web python manage.py benchmark_inscripcions --dataset all --scenario all --warmup 1 --repeats 5 --format both --emit-doc-snippet
```

Arguments disponibles:
- `--dataset small|medium|large|all`
- `--scenario get_list|filter_values|sort_apply|groups_preview|groups_workspace|equips_workspace|media_match_preview|all`
- `--warmup <int>`
- `--repeats <int>`
- `--output-dir <path>`
- `--format table|json|both`
- `--emit-doc-snippet`

## Metriques capturades
- `elapsed_ms`
- `sql_count`
- `sql_time_ms`
- `response_bytes`
- `status_code`
- `dataset`
- `scenario`
- `run_index`
- `is_warmup`

## Estabilitat dels escenaris
- Els escenaris mutadors, com `sort_apply`, no corren sobre la competicio benchmark canonica.
- Abans de cada run mutador es crea una copia temporal de treball.
- El temps de clonacio i neteja queda fora de la mesura.

## Sortides
- Artefacte JSON a `var/benchmarks/inscripcions/<timestamp>.json`
- Resum tabular per stdout
- Snippet Markdown per enganxar a aquest document

## Objectius de millora prioritaris

| Cas critic | Baseline actual | Objectiu de la fase seguent |
| --- | ---: | ---: |
| `large:get_list` | 3835.468 ms | <= 2500 ms |
| `large:equips_workspace` | 4965.553 ms | <= 3000 ms |
| `large:media_match_preview` | 3926.480 ms | <= 2500 ms |
| `medium:get_list` | 1349.577 ms | <= 1000 ms |
| `medium:equips_workspace` | 1737.181 ms | <= 1200 ms |
| `large:groups_workspace` | 235.361 ms | <= 180 ms |

## Baseline acceptada actual
- Acceptada el `2026-04-10`
- Snapshot generat a `2026-04-10T16:24:50.075354+00:00`
- Entorn: `dev`, `postgresql`, `DEBUG=True`, `1` warmup i `5` runs mesurats
- Artefacte de referencia: `var/benchmarks/inscripcions/20260410_162652.json`
- Nota: els valors de `sql_count` i `sql_time_ms` s'han de llegir com a metrics aproximades. En datasets `medium` i `large`, diversos escenaris han quedat a `0` per l'avis de limit del query logging de Django durant la captura.

| Dataset | Scenario | Mean ms | Mean SQL count | Mean SQL ms | Mean response bytes | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| small | get_list | 304.845 | 242.000 | 14.400 | 1560497.000 | accepted |
| small | filter_values | 7.409 | 7.000 | 0.600 | 814.000 | accepted |
| small | sort_apply | 41.674 | 51.000 | 8.800 | 285.000 | accepted |
| small | groups_preview | 19.575 | 19.000 | 2.400 | 4442.000 | accepted |
| small | groups_workspace | 33.259 | 32.000 | 3.000 | 38006.000 | accepted |
| small | equips_workspace | 323.057 | 371.000 | 20.000 | 15443.000 | accepted |
| small | media_match_preview | 18.903 | 7.000 | 0.200 | 32156.000 | accepted |
| medium | get_list | 1349.577 | 427.200 | 27.800 | 2668537.000 | accepted |
| medium | filter_values | 11.460 | 0.000 | 0.000 | 820.000 | accepted |
| medium | sort_apply | 145.266 | 0.000 | 0.000 | 287.000 | accepted |
| medium | groups_preview | 28.506 | 0.000 | 0.000 | 18517.000 | accepted |
| medium | groups_workspace | 90.986 | 0.000 | 0.000 | 110534.000 | accepted |
| medium | equips_workspace | 1737.181 | 0.000 | 0.000 | 26305.000 | accepted |
| medium | media_match_preview | 406.042 | 0.000 | 0.000 | 193436.000 | accepted |
| large | get_list | 3835.468 | 0.000 | 0.000 | 5336664.000 | accepted |
| large | filter_values | 14.780 | 0.000 | 0.000 | 827.000 | accepted |
| large | sort_apply | 498.569 | 0.000 | 0.000 | 287.000 | accepted |
| large | groups_preview | 97.173 | 0.000 | 0.000 | 52314.000 | accepted |
| large | groups_workspace | 235.361 | 0.000 | 0.000 | 278656.000 | accepted |
| large | equips_workspace | 4965.553 | 0.000 | 0.000 | 51034.000 | accepted |
| large | media_match_preview | 3926.480 | 0.000 | 0.000 | 578042.000 | accepted |

## Futures comparatives
- Afegir aqui snapshots de baseline acceptades noves amb data i commit si cal.

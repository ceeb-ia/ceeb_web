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

## Baseline acceptada actual
- Pendent d'omplir

| Dataset | Scenario | Mean ms | Mean SQL count | Mean SQL ms | Mean response bytes | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| small | get_list | pending | pending | pending | pending | pending |
| small | filter_values | pending | pending | pending | pending | pending |
| small | sort_apply | pending | pending | pending | pending | pending |
| small | groups_preview | pending | pending | pending | pending | pending |
| small | groups_workspace | pending | pending | pending | pending | pending |
| small | equips_workspace | pending | pending | pending | pending | pending |
| small | media_match_preview | pending | pending | pending | pending | pending |
| medium | get_list | pending | pending | pending | pending | pending |
| medium | filter_values | pending | pending | pending | pending | pending |
| medium | sort_apply | pending | pending | pending | pending | pending |
| medium | groups_preview | pending | pending | pending | pending | pending |
| medium | groups_workspace | pending | pending | pending | pending | pending |
| medium | equips_workspace | pending | pending | pending | pending | pending |
| medium | media_match_preview | pending | pending | pending | pending | pending |
| large | get_list | pending | pending | pending | pending | pending |
| large | filter_values | pending | pending | pending | pending | pending |
| large | sort_apply | pending | pending | pending | pending | pending |
| large | groups_preview | pending | pending | pending | pending | pending |
| large | groups_workspace | pending | pending | pending | pending | pending |
| large | equips_workspace | pending | pending | pending | pending | pending |
| large | media_match_preview | pending | pending | pending | pending | pending |

## Futures comparatives
- Afegir aqui snapshots de baseline acceptades noves amb data i commit si cal.

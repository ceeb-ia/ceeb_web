# Instrumentacio De Timings D'Inscripcions

## Objectiu
- Exposar timings interns de benchmarking sense afectar el flux normal de produccio.

## Activacio
- El senyal s'activa nomes quan la request porta `X-Inscripcions-Timings: 1`.
- Opcionalment es pot activar per configuracio amb `INSCRIPCIONS_TIMING_ENABLED=True`.
- Sense aquest flag, el cost extra es nul o gairebe nul.

## Contracte De Resposta
- Quan l'instrumentacio esta activa, els endpoints rellevants afegeixen el header `X-Inscripcions-Timings`.
- El valor del header es JSON compactat amb:
- `enabled`: boolea.
- `sections`: llista ordenada de trams amb `name` i `elapsed_ms`.
- `total_ms`: suma dels trams registrats.

## Endpoints Coberts En Aquesta Fase
- `inscripcions_list`
- `inscripcions_equips_workspace`
- `inscripcions_media_match_preview`

## Ús En Benchmark
- El comando `benchmark_inscripcions` envia el flag automàticament i guarda el header parsejat dins cada resultat individual.

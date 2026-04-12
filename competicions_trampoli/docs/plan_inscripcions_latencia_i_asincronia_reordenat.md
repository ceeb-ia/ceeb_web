# Pla Reordenat De Latencia I Asincronia Del Modul D'Inscripcions

## Estatus Del Document
- Aquest document no substitueix `competicions_trampoli/docs/plans.md`.
- Aquest document reordena l'execucio del pla a partir de la baseline acceptada a `competicions_trampoli/docs/inscripcions_baseline.md`.
- Esta pensat perque subagents independents puguin executar fases o carrils sencers amb context minim.

## Motiu Del Replantejament
La baseline real mostra que el cost no esta repartit de manera uniforme pel modul. Els colls d'ampolla principals son:
- `get_list` del llistat principal.
- `inscripcions_equips_workspace`.
- `inscripcions_media_match_preview`.

En canvi:
- `filter_values` no es ara mateix un problema prioritari.
- `groups_preview` i `groups_workspace` son millorables, pero no son el primer focus.
- Eliminar `reloads` globals continua sent bo per UX, pero no resol per si sol els camins que ja estan entre 1.3 s i 5 s.

Per tant, aquest pla deixa de prioritzar fases massa amplies i passa a prioritzar camins critics reals.

## Baseline De Referencia
- Document: `competicions_trampoli/docs/inscripcions_baseline.md`
- Artefacte: `var/benchmarks/inscripcions/20260410_162652.json`
- Snapshot: `2026-04-10T16:24:50.075354+00:00`
- Entorn: `dev`, `postgresql`, `DEBUG=True`, `1` warmup i `5` runs mesurats

### Resum Operatiu De La Baseline
- `large:get_list` = `3835.468 ms`
- `large:equips_workspace` = `4965.553 ms`
- `large:media_match_preview` = `3926.480 ms`
- `large:groups_workspace` = `235.361 ms`
- `large:sort_apply` = `498.569 ms`
- `large:filter_values` = `14.780 ms`

### Consequencies
- El primer problema es la carrega inicial del llistat i el pes HTML/context.
- El segon problema es el workspace d'equips.
- El tercer problema es el preview de matching media.
- La part de filtres generals no s'ha de tractar com a focus principal a curt termini.

## Objectius D'Aquest Pla
- Reduir de manera visible la latencia percebuda en competicions grans abans d'introduir asincronia massiva.
- Fer que el `GET` inicial carregui nomes el minim imprescindible.
- Fer que `equips_workspace` i `media_match_preview` escalin millor amb volum alt.
- Mantenir la possibilitat de treballar en paral.lel per fronts independents.
- Deixar infraestructura suficient perque l'async futur sigui l'ultima opcio, no la primera.

## No Objectius
- No redissenyar visualment el modul.
- No canviar regles de negoci d'inscripcions, grups, equips o media.
- No reescriure tot el modul en una sola PR.
- No enviar a cua operacions petites que poden continuar sent sincronas.

## Mapa Minim Del Modul

### Entry points principals
- Vista principal: `competicions_trampoli/views/inscripcions/listing.py`
- Base del llistat: `competicions_trampoli/views/inscripcions/base.py`
- Sorting i filtres: `competicions_trampoli/views/inscripcions/sorting.py`
- Workspace equips: `competicions_trampoli/views/inscripcions/equips.py`
- Workspace grups: `competicions_trampoli/views/inscripcions/groups.py`
- Media: `competicions_trampoli/views/inscripcions/media.py`
- History: `competicions_trampoli/services/inscripcions/history.py`
- Queries compartides: `competicions_trampoli/services/inscripcions/queries.py`
- Matching media: `competicions_trampoli/services/inscripcions/media_matching.py`

### Frontend principal
- Shell: `competicions_trampoli/templates/competicio/inscripcions/inscripcions_page.html`
- Core JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_core.html`
- Table JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_table.html`
- Sorting JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_sorting.html`
- Groups JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_groups.html`
- Groups workspace JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_groups_workspace_script.html`
- Teams JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_teams.html`
- Teams workspace JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_team_workspace_script.html`
- Media JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_media.html`
- Series JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_series.html`
- Series workspace JS: `competicions_trampoli/templates/competicio/inscripcions/scripts/_series_workspace_script.html`

## Regles Per A Subagents Independents
- Cada subagent ha de treballar sobre un unic carril funcional o tecnic.
- Cada subagent ha de començar pel document de baseline i per aquesta seccio del pla, no per tot `plans.md`.
- Cada subagent ha de tocar el minim de fitxers possible i documentar el contracte que canvia.
- Si una fase depen d'una altra, no s'ha de bloquejar el carril parallel; cal desacoblar la PR o deixar mocks/flags.
- Les fases han d'acabar amb smoke test i rerun parcial del benchmark de l'escenari afectat.
- Cap subagent ha de reordenar el pla; nomes executar la fase assignada.

## Carrils Parallelitzables

### Carril A
- Llistat principal i `GET` inicial.
- Responsable de `listing.py`, `base.py`, templates del shell i qualsevol payload base.

### Carril B
- Workspace d'equips.
- Responsable de `equips.py`, `queries.py` quan afecti equips, i `_team_workspace_script.html`.

### Carril C
- Media matching preview i operacions media pesades.
- Responsable de `media.py`, `media_matching.py` i `_media.html`.

### Carril D
- UX incremental i render parcial d'operacions lleugeres.
- Responsable de `_core.html`, `_sorting.html`, `_table.html`, i respostes parcials associades.

### Carril E
- History delta, indexes i hardening final.
- Responsable de `history.py`, migrations d'indexos, comparatives i runbook final.

## Dependencia Global Recomanada
- Fase 0R abans de qualsevol altra.
- Despres es poden obrir en paral.lel Fase 1A, Fase 1B i Fase 1C.
- Fase 2 pot avancar en parallel amb la part final de Fase 1B/1C, pero no ha de bloquejar-les.
- Fase 3 depen parcialment de Fase 1A i Fase 1B.
- Fase 4 depen de resultats reals re-mesurats de Fases 1A-1C.
- Fase 5 depen de tenir ja el cami sincron prou afinat.

## Fase 0R. Refinament D'Instrumentacio

### Prioritat
- P0

### Pot Anar En Paral.lel Amb
- Res. Es prerequisit curt per a la resta.

### Objectiu
- Afegir mesura interna per trams als camins critics, no nomes timing final de request.

### Per Que Ara
- La baseline dona temps totals fiables, pero els `sql_count` i `sql_time_ms` de diversos casos `medium/large` han quedat limitats pel query logging.
- Abans d'optimitzar a cegues convé saber on es consumeix el temps dins `get_list`, `equips_workspace` i `media_match_preview`.

### Scope
- Timings interns condicionats per flag debug o benchmark mode.
- Separar almenys:
- construccio queryset base
- materialitzacio de registres
- agrupacio/tab merge
- construccio de context secundari
- serialitzacio o render
- matching media
- construccio payload workspace equips

### Fitxers Candidats
- `competicions_trampoli/views/inscripcions/listing.py`
- `competicions_trampoli/views/inscripcions/base.py`
- `competicions_trampoli/views/inscripcions/equips.py`
- `competicions_trampoli/views/inscripcions/media.py`
- `competicions_trampoli/services/inscripcions/baseline.py`

### Entregables
- Logs o traces de benchmark per trams.
- Document curt de lectura dels timings interns.
- Benchmark rerunnable amb trams visibles per aquests tres escenaris.

### Definition Of Done
- Es pot dir quin percentatge del temps va a render, context, matching o workspace.

### Handoff Per A Un Subagent
- No optimitzis res encara.
- Afegeix nomes instrumentacio segura, estable i apagable.
- Valida repetint `small`, `medium` i `large` per `get_list`, `equips_workspace` i `media_match_preview`.

## Fase 1A. Aprimar El GET Inicial Del Llistat

### Prioritat
- P0

### Carril
- A

### Pot Anar En Paral.lel Amb
- Fase 1B
- Fase 1C

### Objectiu
- Reduir dràsticament cost, mida de resposta i context del `GET` inicial.

### Problema Real A Resoldre
- `large:get_list` esta a `3835.468 ms`.
- La resposta HTML arriba a `5336664` bytes.
- Encara es materialitzen llistes i contextos que no son imprescindibles per pintar la primera vista.

### Scope
- Deixar el `GET` inicial amb shell, capcalera, toolbar, taula visible i boot payload minim.
- Posposar dades de sidebar i datasets no visibles.

### Fitxers Principals
- `competicions_trampoli/views/inscripcions/listing.py`
- `competicions_trampoli/views/inscripcions/base.py`
- `competicions_trampoli/templates/competicio/inscripcions/inscripcions_page.html`
- `competicions_trampoli/templates/competicio/inscripcions/_sidebar.html`
- `competicions_trampoli/templates/competicio/inscripcions/_groups_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_teams_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_series_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_media_panel.html`

### Tasques
- Identificar context imprescindible per al first paint.
- Treure del `GET` inicial:
- `equips_existing`
- `team_context_summary`
- `series_team_aparells` si no son visibles d'entrada
- qualsevol resum de workspace o dades de panell lateral no usades al primer render
- qualsevol mapa massiu no necessari per a files visibles
- Revisar si `group_member_totals` pot ser lazy.
- Revisar si la sidebar pot hidratar cada panell a la primera activacio.
- Revisar si la taula inicial necessita totes les files o si pot treballar amb finestra inicial quan hi ha agrupacio.
- Fer mes petit `inscripcions_page_boot`.

### Restriccions
- No canviar el contracte extern de rutes.
- No trencar l'obertura de panells.
- No reescriure sorting profund en aquesta fase.

### Benchmarks A Repetir
- `get_list` per `small`, `medium`, `large`.

### Definition Of Done
- `large:get_list` baixa clarament.
- La mida de resposta baixa de manera mesurable.
- El `GET` inicial no construeix dades de panells que encara no s'han obert.

### Handoff Per A Un Subagent
- El teu benchmark de sortida es `get_list`.
- No entris a optimitzar `equips_workspace` ni `media_match_preview`.
- Si necessites nous endpoints JSON per panells laterals, pots crear-los mentre no canviis la UX funcional.

## Fase 1B. Optimitzacio Del Workspace D'Equips

### Prioritat
- P0

### Carril
- B

### Pot Anar En Paral.lel Amb
- Fase 1A
- Fase 1C

### Objectiu
- Fer que `inscripcions_equips_workspace` deixi d'escalar fins a gairebe 5 segons en `large`.

### Problema Real A Resoldre
- `large:equips_workspace` = `4965.553 ms`
- `medium:equips_workspace` = `1737.181 ms`

### Scope
- Backend del workspace d'equips.
- Render i refresh del workspace.
- Resolucio de candidates, summary, teams i contexts.

### Fitxers Principals
- `competicions_trampoli/views/inscripcions/equips.py`
- `competicions_trampoli/services/inscripcions/queries.py`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_team_workspace_script.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_teams.html`

### Tasques
- Separar construccio de `summary`, `candidates`, `teams`, `filter_options` i `context meta`.
- Evitar materialitzar totes les candidates abans de paginar.
- Fer que la paginacio sigui real i aplicada abans de serialitzar.
- Revisar si la construccio de targetes d'equip es pot lazy-load o fer per detall.
- Evitar recalcular subconjunts repetits quan nomes canvia la pagina o un filtre menor.
- Si hi ha computs de context costosos, considerar cache curt de request o cache molt curta per context.
- Reduir mida del payload JSON retornat.

### No Objectius
- No passar encara aquest flux a async.
- No canviar regles de negoci de creacio, assignacio o contextos.

### Benchmarks A Repetir
- `equips_workspace` per `small`, `medium`, `large`.

### Definition Of Done
- `large:equips_workspace` baixa de forma visible i estable.
- El workspace continua funcional en accions manuals i paginacio.

### Handoff Per A Un Subagent
- El teu benchmark de sortida es `equips_workspace`.
- No toquis `get_list` excepte si necessites compartir helpers molt locals.
- Documenta qualsevol contracte nou entre backend i `_team_workspace_script.html`.

## Fase 1C. Optimitzacio Del Media Match Preview

### Prioritat
- P0

### Carril
- C

### Pot Anar En Paral.lel Amb
- Fase 1A
- Fase 1B

### Objectiu
- Reduir el cost del preview de matching media sense passar encara a cua asincrona.

### Problema Real A Resoldre
- `large:media_match_preview` = `3926.480 ms`
- `medium:media_match_preview` = `406.042 ms`
- El salt entre `medium` i `large` apunta a creixement massa agressiu.

### Scope
- Preview i matching heuristics.
- Carrega d'opcions candidates.
- Serialitzacio del resultat de preview.

### Fitxers Principals
- `competicions_trampoli/views/inscripcions/media.py`
- `competicions_trampoli/services/inscripcions/media_matching.py`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_media.html`

### Tasques
- Mesurar per separat:
- obtencio de candidates
- scoring
- construccio de `inscripcions_options`
- serialitzacio de files de preview
- Revisar si cal retornar totes les opcions o nomes top candidates.
- Revisar si `inscripcions_options` ha de ser complet sempre o pot ser lazy/condicional.
- Reduir treball redundant entre fitxers del mateix preview.
- Revisar estructures de dades per matching local en memori.
- Evitar payloads enormes si el front no consumeix totes les opcions d'entrada.

### No Objectius
- No canviar encara el flux d'upload o apply.
- No introduir Celery en aquesta fase.

### Benchmarks A Repetir
- `media_match_preview` per `small`, `medium`, `large`.

### Definition Of Done
- `large:media_match_preview` baixa de forma mesurable.
- El front continua podent revisar i aplicar el preview.

### Handoff Per A Un Subagent
- El teu benchmark de sortida es `media_match_preview`.
- No et desviis a optimitzar el `GET` del llistat ni equips.
- Si canvies el payload, deixa documentat el contracte nou per `_media.html`.

## Fase 2. UX Incremental I Render Parcial Selectiu

### Prioritat
- P1

### Carril
- D

### Pot Anar En Paral.lel Amb
- Fase 1B o 1C si els contractes backend ja estan estables.

### Objectiu
- Eliminar `reloads` globals de les operacions lleugeres i frequents.

### Per Que No Es P0
- Els `reloads` afecten UX, pero no expliquen els 3.8 s, 4.9 s o 3.9 s dels camins critics.
- Primer cal aprimar backend i payloads grossos.

### Scope
- `sort_apply`, `sort_remove`, `sort_clear`
- canvis de columnes
- undo/redo lleuger
- accions de media lleugeres
- accions locals de taula que no requereixin reconstruccio completa

### Fitxers Principals
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_core.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_sorting.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_table.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_media.html`
- endpoints a `listing.py`, `sorting.py`, `media.py`

### Tasques
- Catalogar on es fa `reloadWithUiState()` i `navigateWithUiState()`.
- Crear refresh parcial per:
- taula principal
- resum d'history
- panell concret afectat
- summary de capcalera si canvia
- Introduir fragments HTML o JSON minims per refrescar zones.
- Conservar seleccio, scroll i panell actiu quan sigui raonable.

### Definition Of Done
- Les accions lleugeres mes frequents deixen de fer reload complet.
- La UX es nota mes fluida encara que el backend sigui el mateix.

### Handoff Per A Un Subagent
- No intentis resoldre performance profunda aqui.
- Si una accio continua costant molt backend, accepta temporalment refresh parcial d'una zona, no de tota la pagina.

## Fase 3. Sorting I Llistat DB-First On Realment Importa

### Prioritat
- P1

### Carrils
- A i B segons l'impacte

### Objectiu
- Atacar el treball Python massiu que segueix viu en sorting i filtratge de camins calents.

### Replantejament Respecte El Pla Vell
- Aquesta fase no tracta `filter_values` com a focus principal.
- El focus passa a ser:
- `sort_apply`
- qualsevol cami de workspace que reutilitzi `_build_inscripcions_filtered_qs`
- qualsevol materialitzacio de llistats sencers per obtenir ids o tokens

### Fitxers Principals
- `competicions_trampoli/services/inscripcions/queries.py`
- `competicions_trampoli/views/inscripcions/sorting.py`
- qualsevol helper reutilitzat per `equips.py` o `groups.py`

### Tasques
- Separar camps natius, derivats i `extra`.
- Fer SQL-first per natius.
- Reavaluar quins `extra` mereixen lookup sobre JSON i quins no.
- Evitar `list(_build_sort_records_queryset(...))` en camins grans quan nomes calen ids o valors agregats.
- Reduir dobles passades `context + global` quan no aporten res.
- Mantenir exactitud funcional dels tokens especials i dels valors buits.

### Benchmarks A Repetir
- `sort_apply`
- `equips_workspace` si depen del mateix helper
- `groups_workspace` si depen del mateix helper

### Definition Of Done
- `sort_apply` baixa clarament.
- Els workspaces no es degraden per filtratge o sorting compartit.

## Fase 4. History Delta, Indexos I Caches Curtes

### Prioritat
- P1

### Carril
- E

### Objectiu
- Treure cost estructural recurrent un cop els camins critics ja s'han alleugerit.

### Scope
- History basat en deltes per a accions petites.
- Indexos justificats per consultes reals.
- Cache curta per resums o dades derivades si es demostra utilitat.

### Fitxers Principals
- `competicions_trampoli/services/inscripcions/history.py`
- migrations del modul
- punts de consulta detectats a `queries.py`, `equips.py`, `groups.py`, `listing.py`

### Tasques
- Introduir format de delta per history.
- Mantenir compatibilitat temporal amb snapshots globals.
- Revisar indexos compostos nomes on benchmark i traces ho justifiquin.
- Documentar per cada index quina consulta millora.

### Definition Of Done
- La majoria d'accions petites no capturen snapshot global.
- Existeix informe curt d'indexos i caches afegits.

## Fase 5. Async Massiu Selectiu

### Prioritat
- P2

### Objectiu
- Portar a cua nomes els fluxos que, despres de Fases 1-4, continuin sent massa cars.

### Candidats Probables
- auto-creacio massiva d'equips
- reassignacions massives
- algun rebuild pesat de media matching si encara no entra en pressupost sincron

### Fitxers I Patrons De Referencia
- `ceeb_web/celery.py`
- `ceeb_web/tasks.py`
- `ceeb_web/views.py`
- `designacions/views.py`
- `marbella_informes/views.py`

### Tasques
- Triar un patro de job estable.
- Encolar tasca.
- Retornar `task_id`.
- Polling o SSE.
- Progress visible.
- Refresh parcial de les zones afectades al final.

### Definition Of Done
- Hi ha almenys un flux massiu real passat a async amb bona UX.

## Fase 6. Tancament Operatiu

### Prioritat
- P2

### Objectiu
- Demostrar millora, deixar runbook i tancar regressions.

### Scope
- Rerun complet de baseline.
- Comparativa abans/despres.
- Runbook intern de regressions.
- Llista final de deutes pendents si n'hi ha.

### Entregables
- Nou snapshot de baseline.
- Taula comparativa sobre `get_list`, `equips_workspace`, `media_match_preview`, `sort_apply`, `groups_workspace`.
- Nota final dins docs amb guies de diagnosis.

## Ordre D'Execucio Recomanat
- Fase 0R
- Fase 1A, Fase 1B i Fase 1C en paral.lel
- Fase 2 en paral.lel parcial amb l'ultim tram de Fase 1
- Fase 3
- Fase 4
- Fase 5
- Fase 6

## Repartiment Recomanat Per Subagents
- Agent A: Fase 0R + suport de benchmark
- Agent B: Fase 1A
- Agent C: Fase 1B
- Agent D: Fase 1C
- Agent E: Fase 2
- Agent F: Fase 3
- Agent G: Fase 4
- Agent H: Fase 5 i Fase 6

## Criteris De Qualitat Transversals
- No barrejar reduccio de payload, refactor estructural i canvi de negoci en una mateixa PR.
- Cada fase ha d'indicar:
- fitxers tocats
- contractes nous o canviats
- benchmark re-executat
- riscos coneguts
- Cada fase ha de ser desplegable per separat.
- Cada fase ha de poder ser revisada sense necessitat de llegir totes les altres.

## Checklists De Sortida Per Cada Fase
- Smoke test manual del flux afectat.
- Test automatitzat nou o actualitzat si canvia contracte.
- Benchmark de l'escenari principal afectat.
- Nota curta al document de baseline o al PR intern amb resultat abans/despres.

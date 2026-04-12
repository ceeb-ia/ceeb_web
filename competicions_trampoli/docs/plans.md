# V1 Rols De Supervisor Amb Confirmació Per Bloc

## Resum
- Mantenir `ScoreEntry` i `TeamScoreEntry` com a font única de nota final confirmada.
- Afegir rols per `field_code` base i per token, no per usuari ni per QR global.
- Afegir una capa intermèdia de submissions per bloc: cada bloc agrupa tots els camps supervisats d’un `save_partial` per `source_token + supervisor_token + subjecte + exercici`.
- Els camps sense supervisor continuen amb flux directe legacy.
- El panell d’organització continua veient i consumint només valors finals; no entra a la capa de submissions.

## Canvis Clau
- Model de rols per camp:
  - Nova assignació de rol per `comp_aparell + judge_token + field_code_base`.
  - Rols v1: `standard`, `supervisor`.
  - Constraint: màxim un supervisor actiu per `comp_aparell + field_code_base`.
  - Validació v1: rebutjar cicles de supervisió dins del mateix aparell; per defecte es prohibeix qualsevol cicle al graf `source_token -> supervisor_token`.
- Model de submissions per bloc:
  - Nova entitat append-only amb doble forma de subjecte igual que les notes finals: `inscripcio` o `team_subject`.
  - Claus lògiques del bloc viu: `comp_aparell + subjecte + exercici + source_token + supervisor_token`.
  - Camps mínims: `submitted_patch`, `reviewed_patch`, `field_codes`, `status`, `supersedes`, `created_at`, `resolved_at`, `review_comment`.
  - Estats: `pending`, `approved`, `rejected`, `superseded`.
- Regla de construcció del bloc:
  - `judge_save_partial` divideix el patch en `directe` i `supervisat`.
  - El patch supervisat es reagrupa per supervisor destí.
  - Per cada supervisor destí es crea un bloc amb el snapshot complet dels camps supervisats visibles pel jutge en aquell moment, no només els camps tocats.
  - Per construir aquest snapshot, el backend pren per ordre: últim bloc `pending`, si no n’hi ha últim `rejected`, i si no n’hi ha els valors finals actuals d’aquells camps.
  - Si ja existeix un bloc `pending` viu per la mateixa clau lògica, el nou bloc no l’edita: el marca `superseded` i crea un bloc nou.
- Confirmació del supervisor:
  - La confirmació és per bloc, no per camp.
  - El supervisor pot editar el bloc abans d’aprovar; s’aplica `reviewed_patch` si existeix, si no `submitted_patch`.
  - L’aprovació bloqueja la fila final amb el mateix patró de `select_for_update`, fusiona només els camps del bloc aprovat sobre l’`entry` actual, recalcula i desa.
  - El rebuig no toca la nota final; genera avís estàndard de rebuig i admet comentari opcional.
- Flux de vídeo:
  - V1: `can_record_video=True` només si el token és supervisor d’almenys un camp del mateix aparell.
  - El vídeo continua lligat a l’entry final com ara; en aquesta fase només es canvia el gating, no el model de vídeo.
- Migració legacy:
  - Backfill de rol `supervisor` per cada `field_code` base que tingui en permisos un token actiu, no revocat, amb `can_record_video=True`.
  - Si per un mateix camp hi ha més d’un candidat legacy vàlid, no s’assigna supervisor automàticament a aquell camp i es deixa incidència de migració.
  - Si un camp queda sense supervisor després de migració, manté flux directe.

## Interfícies I Comportament
- Admin de tokens/QRs:
  - Afegir selector de rol a cada fila de permís.
  - Normalitzar i persistir el rol per `field_code` base; totes les files del mateix camp dins del mateix token han de compartir rol.
  - Mostrar resum de rols per camp al llistat de tokens.
  - Validar `can_record_video` contra els camps supervisor reals del token.
- `judge_save_partial`:
  - Manté l’entrada parcial concurrent segura.
  - Aplica immediatament només els camps directes.
  - Crea/substitueix blocs pendents per als camps supervisats.
  - Resposta ampliada amb dues capes: actualització final dels camps directes i estat dels blocs pendents creats o substituïts.
- Feed del jutge:
  - `judge_updates` es manté com a feed de valors finals confirmats.
  - Nou feed incremental de submissions rellevants per al token actual, amb direcció `outgoing` o `incoming`.
  - El portal del jutge usa `outgoing` per sobreposar la submission pendent o rebutjada sobre la nota final.
  - El mateix portal, si el token és supervisor, usa `incoming` per renderitzar la cua de blocs per revisar.
- Portal del jutge:
  - Si hi ha bloc `pending`, el jutge veu la submission, no el final, per als camps supervisats.
  - Si hi ha bloc `rejected`, veu l’últim bloc rebutjat amb avís estàndard i comentari opcional.
  - Quan el bloc passa a `approved`, desapareix la capa de submission i es mostra el valor final confirmat.
- Panell d’organització:
  - Sense canvis funcionals en el feed ni en la taula principal.
  - Continua consumint només `ScoreEntry` i `TeamScoreEntry`.

## Concurrència I Integritat
- Totes les escriptures finals van dins `transaction.atomic`.
- L’aplicació de camps directes i l’aprovació de blocs reutilitzen bloqueig pessimista sobre l’`entry` final.
- Dues aprovacions quasi simultànies sobre blocs diferents del mateix `entry` no es trepitgen: la segona espera el lock, rellegeix, fusiona el seu bloc i recalcula.
- Un supervisor que supervisa diversos camps o diversos blocs usa el mateix mecanisme; no hi ha camí que faci overwrite d’inputs aliens.
- Cap submission pendent s’edita in place; qualsevol reenviament crea un registre nou i `supersede` del pendent anterior.

## Proves
- Creació i edició de token amb rols per camp, incloent consistència entre files duplicades del mateix camp.
- Unicitat de supervisor per camp i validació de cicles de supervisió.
- `judge_save_partial` mixt:
  - camps directes entren a final
  - camps supervisats creen bloc pendent
  - coexistència de directes i supervisats al mateix `save_partial`
- Reenviament del mateix jutge abans de revisió: el pendent anterior passa a `superseded` i el nou bloc conserva l’últim snapshot complet.
- Aprovació del supervisor amb edició prèvia del bloc.
- Rebuig amb avís estàndard i comentari opcional.
- Dos supervisors o dos blocs aprovant quasi alhora sobre el mateix `entry` sense pèrdua de dades.
- Comportament individual i team-context, sempre sobre `field_code` base i cobrint `runtime_field_code` de membres.
- `judge_updates` i `scoring_updates` continuen emetent només finals.
- Feed de submissions del jutge mostra `outgoing` i `incoming` correctes.
- Validació `can_record_video` i backfill legacy de supervisors.

## Assumptions I Defaults
- Sense supervisor configurat per un camp, aquell camp manté flux directe.
- La unitat de revisió v1 és el bloc per supervisor destí, no el camp individual ni l’exercici complet.
- Si un mateix `save_partial` genera blocs per supervisors diferents, aquests blocs conviuen i es resolen de forma independent.
- V1 prohibeix cicles de supervisió per evitar dependències circulars de revisió.
- El vídeo no canvia de model en aquesta fase; només queda restringit a tokens amb almenys un camp supervisor.




# V2 Pla De Refactor I Rendiment Del Modul D'Inscripcions

## Objectiu
- Reduir de forma molt notable la latencia percebuda del modul d'inscripcions en competicions grans.
- Atacar primer la divisio del template gegant en peces petites i reutilitzables.
- Separar la carrega inicial de la pagina dels panells i calculs pesats.
- Reduir recalculs globals i reloads complets de pagina.
- Preparar el modul per treballar amb operacions asincrones reals quan el cost ja no sigui acceptable en sincron.

## Abast Functional
- Punt d'entrada principal: `inscripcions_list`.
- Vistes i serveis relacionats amb llistat, sorting, grups, equips, media i history.
- Templates principals i parcials del modul d'inscripcions.
- No inclou canvis de negoci sobre com funciona una inscripcio, un grup o un equip.
- No inclou redisseny visual gran; l'objectiu es arquitectura i rendiment mantenint UX i funcionalitat.

## Context Minim Per A Un Agent Extern
- El template principal actual es `competicions_trampoli/templates/competicio/inscricpions_list_new.html`.
- La vista principal actual es `competicions_trampoli/views/inscripcions/listing.py`, classe `InscripcionsListNewView`.
- La base del llistat i part de la logica comuna viu a `competicions_trampoli/views/inscripcions/base.py`.
- Sorting i filtres de columna viuen a `competicions_trampoli/views/inscripcions/sorting.py`.
- Queries i resolucions transversals viuen a `competicions_trampoli/services/inscripcions/queries.py`.
- Workspaces d'equips i grups viuen a `competicions_trampoli/views/inscripcions/equips.py` i `competicions_trampoli/views/inscripcions/groups.py`.
- L'undo/redo i snapshots viuen a `competicions_trampoli/services/inscripcions/history.py`.
- El projecte ja te Celery, Redis i patrons de polling/progress reutilitzables a `ceeb_web/celery.py`, `ceeb_web/tasks.py`, `ceeb_web/views.py`, `designacions/views.py` i `marbella_informes/views.py`.

## Problemes Detectats Que Aquest Pla Vol Resoldre
- Template monolitic massa gran i dificil de tocar sense regressions.
- Massa JS incrustat en una sola plantilla.
- Moltes accions AJAX acaben fent `reload` global de la pagina.
- La carrega inicial del llistat construeix massa context i massa col.leccions en memoria.
- Els filtres de columna i alguns calculs de sorting fan treball en Python sobre molts registres.
- El history snapshot actual es global i molt car per canvis petits.
- Els workspaces de grups i equips ja son AJAX, pero continuen fent resolucions massa grans abans de paginar o resumir.
- No hi ha una frontera clara entre operacions instantanies i operacions candidates a cua asincrona.

## Principis Del Pla
- Primer refactoritzar estructura i contractes, despres optimitzar logica, despres introduir async.
- Cada fase ha de deixar el sistema en un estat usable i desplegable.
- Cada fase ha de tenir criteris clars de completitud i proves minimes.
- Les operacions petites han de continuar sent sincronas i rapides.
- L'asincronia s'ha d'aplicar nomes a operacions realment pesades o massives.

## Fase 0. Baseline I Instrumentacio Minima

### Estat
- Tancada el `2026-04-10`.
- Snapshot acceptat documentat a `competicions_trampoli/docs/inscripcions_baseline.md`.
- Artefacte de referencia: `var/benchmarks/inscripcions/20260410_162652.json`.

### Prioritat
- P0

### Objectiu
- Mesurar abans de tocar.
- Crear un baseline per saber si les fases posteriors aporten millora real.

### Scope
- Afegir punts de mesura de temps a la vista principal i endpoints principals del modul.
- Documentar els casos de prova manuals i volum objectiu.
- Capturar SQL count aproximat, temps de render i mida de resposta per casos representatius.

### Casos De Prova A Cobrir
- Competicio petita amb menys de 50 inscripcions.
- Competicio mitjana amb entre 150 i 300 inscripcions.
- Competicio gran amb mes de 500 inscripcions.
- Carrega inicial del llistat.
- Aplicar sorting.
- Obrir filtre de valors de columna.
- Crear grups des de sorting.
- Obrir workspace de grups.
- Obrir workspace d'equips.

### Entregables
- Document curt dins `competicions_trampoli/docs` amb les mesures baseline.
- Helpers o logs temporals protegits per setting o flag de debug.
- Taula amb objectius de millora per cada cas critic.

### Definition Of Done
- Existeixen mesures comparables abans i despres.
- Qualsevol agent extern pot repetir els mateixos escenaris.

### Notes Per A L'Agent
- Aquesta fase no ha de canviar arquitectura.
- Si no hi ha dades voluminoses reals, crear fixtures o factories de volum.

## Fase 1. Divisio De Templates I Separacio De Responsabilitats

### Prioritat
- P0

### Objectiu
- Convertir el template gegant en una composicio clara de parcials HTML i scripts especialitzats.
- Deixar preparat el modul per actualitzacions parcials sense haver de tornar a renderitzar tota la pagina.

### Scope
- Partir `inscricpions_list_new.html` en bloc layout, toolbar, taula principal, modals, panells laterals, scripts compartits i scripts de cada workspace.
- Separar JS inline en fitxers o parcials de script tematics amb API clara.
- Fer que cada parcial rebi nomes el context que realment necessita.

### Estructura Recomanada
- `competicions_trampoli/templates/competicio/inscripcions/inscripcions_page.html`
- `competicions_trampoli/templates/competicio/inscripcions/_header.html`
- `competicions_trampoli/templates/competicio/inscripcions/_toolbar.html`
- `competicions_trampoli/templates/competicio/inscripcions/_table.html`
- `competicions_trampoli/templates/competicio/inscripcions/_table_rows.html`
- `competicions_trampoli/templates/competicio/inscripcions/_sorting_ui.html`
- `competicions_trampoli/templates/competicio/inscripcions/_media_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_groups_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_teams_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_series_panel.html`
- `competicions_trampoli/templates/competicio/inscripcions/_modals.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_core.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_sorting.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_groups.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_teams.html`
- `competicions_trampoli/templates/competicio/inscripcions/scripts/_media.html`

### Tasques
- Mapar totes les seccions actuals del template i agrupar-les per responsabilitat.
- Moure fragments sense canviar comportament.
- Crear un contracte de context per cada parcial.
- Eliminar dependencias ocultes entre fragments de DOM.
- Crear una capa JS `core` amb helpers comuns: `postJson`, cookies CSRF, alertes, estat UI, history state.
- Deixar els scripts de grups, equips, media i sorting consumint nomes APIs del `core`.

### Restriccions
- No optimitzar encara logica de negoci si no es necessari per fer el split.
- No canviar noms de rutes ni comportaments externs en aquesta fase.
- Mantenir tota la funcionalitat actual encara que internament es reorganitzi.

### Riscos
- Trencar handlers per ids o selectors de DOM.
- Trencar ordre de carrega de scripts.
- Duplicar helpers globals si no es defineix una frontera clara.

### Proves
- Smoke test complet de la pantalla principal.
- Obri i tanca modals.
- Sorting, custom sort, filters, history undo/redo.
- Crear, editar i eliminar grups/equips/media.

### Definition Of Done
- El template principal queda reduit a composicio d'includes i shell general.
- Cada area principal te un parcial propi i un script propi.
- Un agent extern pot tocar una area sense llegir 9000 linies de template.

### Handoff Per A Un Agent Extern
- Abans de tocar codi, llegir els parcials resultants i documentar el contracte de dades de cada un.
- No barregis refactor estructural amb canvis de rendiment profund en la mateixa PR.

## Fase 2. Contractes De Dades I Carrega Lazy Del Frontend

### Prioritat
- P0

### Objectiu
- Fer que la carrega inicial porti nomes el minim necessari.
- Posposar panells, modals i datasets globals fins que l'usuari els obri o els necessiti.

### Scope
- Redefinir el context de `InscripcionsListNewView` en dos nivells: `base page payload` i `deferred payloads`.
- Carregar per separat valors de filtres, opcions massives de media, previews de workspaces i estadistiques que ara entren de cop.

### Tasques
- Identificar quins camps del context son imprescindibles per pintar la primera vista.
- Moure la resta a endpoints JSON o parcials HTML sota demanda.
- No calcular `media_match_inscripcions_options` en el GET inicial.
- No calcular buckets de sort o auto-group si l'usuari no ha obert el panell.
- No construir `media_map` complet si la UI no mostra realment aquell bloc.
- Retornar una estructura clara de `page boot payload`.

### Candidates A Carrega Lazy
- Opcions globals de media matching.
- Buckets i previews de group creation.
- Resums de teams.
- Filter values d'una columna.
- Custom sort detected values.
- Dades detallades de modals de grup i equip.

### Proves
- Carrega inicial visual intacta.
- Els panells deferits es resolen correctament a la primera obertura.
- Errors de xarxa en un panell deferit no trenquen la resta de la pagina.

### Definition Of Done
- El GET inicial del llistat no construeix datasets globals no visibles.
- Existeix llista documentada de context base i endpoints deferits.

### Handoff Per A Un Agent Extern
- Aquesta fase ja pot ser feta sense tocar sorting profund.
- La clau es reduir `get_context_data`, no reescriure tota la logica del modul.

## Fase 3. Eliminacio De Reloads Globals I Render Parcial

### Prioritat
- P0

### Objectiu
- Substituir `window.location.reload()` i redireccions internes per actualitzacions parcials del DOM.

### Scope
- Operacions de sorting.
- Undo/redo.
- Save columns.
- Rename group.
- Accions de media.
- Accions d'equips i grups que avui fan reload complet.

### Tasques
- Catalogar totes les accions que criden `reloadWithUiState()` o `navigateWithUiState()`.
- Definir per cada accio quin fragment s'ha de refrescar.
- Crear endpoints o respostes ampliades que retornin el minim per actualitzar el fragment afectat.
- Refrescar nomes taula, resum, capcalera de grup o panell concret.
- Conservar l'estat UI local sense haver-lo de persistir per reload.

### Estrategia Recomanada
- Introduir helpers de `refreshMainTable`, `refreshGroupPanel`, `refreshTeamPanel`, `refreshMediaPanel`, `refreshSummary`.
- Si una operacio toca diverses zones, refrescar nomes aquestes zones.
- Si una operacio es massa transversal, fer fallback temporal a recarregar nomes el fragment principal del llistat, no la pagina sencera.

### Proves
- Cada accio continua funcionant sense reload complet.
- L'estat de drawer, scroll intern, seleccio activa i modals no es perd innecessariament.

### Definition Of Done
- Les principals accions del modul deixen de fer reload global.
- La latencia percebuda baixa clarament encara abans de tocar la logica de BD.

### Handoff Per A Un Agent Extern
- Aquesta fase es pot fer area per area.
- Un agent extern pot agafar nomes sorting o nomes equips, sempre que respecti l'API comuna de refresh parcial.

## Fase 4. Optimitzacio Del GET Principal I Del Llistat

### Prioritat
- P1

### Objectiu
- Reduir la feina total del `GET` principal i del render del llistat.

### Scope
- `InscripcionsListView.get_context_data`.
- `InscripcionsListNewView.get_context_data`.
- Construccio de `records_grouped`, counts i datasets visibles.

### Tasques
- Evitar materialitzar tots els registres si nomes calen ids o comptatges.
- Revisar `count()` repetits i consolidar-los.
- Revisar si `group_member_totals` es pot servir des d'un endpoint o cache curt.
- Revisar si `records_grouped` pot construir-se sobre finestra visible o pestanya activa.
- Reintroduir algun tipus de paginacio o finestra visible quan hi ha `group_by`.
- Estudiar virtualitzacio de files al frontend si el nombre de registres visibles continua sent molt alt.

### Canvis Esperats
- Menys `list(queryset)` globals.
- Menys `.only(...)` seguits de passades Python sobre centenars de registres.
- Reduccio del pes HTML servit.

### Proves
- Mateix comportament funcional.
- Mateixos ordres i agrupacions visibles.
- Sense regressio en scroll, drag and drop o accions contextuals.

### Definition Of Done
- La carrega inicial del llistat es mes lleugera en memori, temps i mida de resposta.

## Fase 5. Reescriptura De Filtres I Sorting Per Fer-los Mes DB-First

### Prioritat
- P1

### Objectiu
- Moure el maxim de feina possible a base de dades i reduir resolucions Python sobre col.leccions grans.

### Scope
- `_build_inscripcions_filtered_qs`.
- Resolucio de `column_filters`.
- Endpoints `inscripcions_filter_values`, `inscripcions_sort_apply`, `inscripcions_sort_custom_values`, `inscripcions_sort_custom_save`.

### Tasques
- Separar clarament camps natius, camps derivats i camps `extra`.
- Resoldre filtres de camps natius amb `Q()` i SQL.
- Si es PostgreSQL, usar lookups sobre `JSONField` per a `extra` quan sigui viable.
- Si alguns camps d'Excel son molt usats per filtres o sorting, estudiar normalitzacio o indexacio funcional.
- Evitar llegir tots els registres per obtenir valors de filtre d'una columna si es pot fer amb `values`, `annotate` o query dedicada.
- Revisar custom sort per no fer doble passada `context + global` si no cal.

### Decisio Arquitectonica Necessaria
- Triar una estrategia per a camps `extra`:
- Opcio A: mantenir JSON i optimitzar consultes JSON a PostgreSQL.
- Opcio B: materialitzar camps d'alta frequencia.
- Opcio C: model auxiliar d'atributs indexables.

### Proves
- Filters i sorting donen exactament els mateixos resultats.
- Valors buits, `(Sense valor)` i aliases legacy continuen funcionant.

### Definition Of Done
- Els camins critics de filtres i sorting deixen de dependre d'una materialitzacio Python massiva en la majoria de casos.

### Handoff Per A Un Agent Extern
- Aquesta fase necessita llegir be `queries.py`.
- No tocar frontend fins tenir tancat el contracte de resultats.

## Fase 6. Redisseny De History I Undo/Redo Basat En Deltes

### Prioritat
- P1

### Objectiu
- Fer que les accions petites deixin de pagar el cost d'un snapshot global complet.

### Scope
- `capture_inscripcions_history_snapshot`.
- `record_inscripcions_history_entry`.
- Operacions de reorder, sort, groups, teams, media i configuracio lleugera.

### Estrategia Recomanada
- Mantenir compatibilitat amb snapshot global temporalment.
- Introduir un format de history entry per deltes.
- Fer que cada tipus d'accio pugui generar i revertir el seu delta.
- Reservar snapshot complet nomes per operacions massives o punts de checkpoint.

### Deltas Candidats
- Reorder: ids afectats + ordre antic/nou.
- Sort apply/remove: stack abans/despres + ids afectats si cal.
- Group assign/unassign: ids + grup origen/desti.
- Team assign/unassign: ids + equip/context origen/desti.
- Table columns, group names, derived config: config abans/despres.

### Proves
- Undo/redo sobre accions petites sense regressio.
- Undo/redo mixt amb accions antigues snapshot-based durant la transicio.

### Definition Of Done
- La majoria d'accions frequents ja no capturen l'estat complet de tota la competicio.

## Fase 7. Workspaces De Grups I Equips Mes Lleugers

### Prioritat
- P1

### Objectiu
- Fer que els workspaces AJAX siguin realment eficients i paginats de debò.

### Scope
- `_build_workspace_payload` d'equips.
- `_build_group_workspace_payload`.
- Endpoints `equips_workspace` i `groups_workspace`.

### Tasques
- Evitar construir totes les candidates abans de paginar.
- Separar `filter_options`, `summary`, `candidates` i `cards` en consultes dedicades si convé.
- Retornar nomes el page chunk necessari per la llista central.
- Lazy-load del detall de team/group cards si no son visibles.
- Consolidar helpers per no recalcular el mateix conjunt amb filtres semblants.

### Proves
- Mateixes dades visibles.
- Canvi de pagina i filtres sense penalitzacio exagerada.

### Definition Of Done
- Els workspaces deixen de fer materialitzacions completes innecessaries.

## Fase 8. Indexacio, SQL Review I Caches Curtes

### Prioritat
- P1

### Objectiu
- Donar suport de base de dades als patrons reals de consulta del modul.

### Scope
- Revisio de models i migrations.
- Indexos nous.
- Potencial cache curta per resums i valors derivats.

### Candidats A Estudi
- Index compost `competicio, ordre_sortida`.
- Index compost `competicio, grup, ordre_sortida`.
- Index compost per cerques frequents `competicio, entitat`.
- Trigram index per `nom_i_cognoms`, `document`, `entitat` si el volum i l'ús ho justifiquen.
- Cache curta per `group_member_totals`, valors de filtre i datasets de suport.

### Restriccions
- No afegir indexes sense justificar-los amb consultes reals.
- Mesurar cost d'escriptura abans d'afegir massa indexes.

### Definition Of Done
- Existeix informe curt d'indexes afegits, perque s'han afegit i quina consulta milloren.

## Fase 9. Operacions Asincrones Massives

### Prioritat
- P2

### Objectiu
- Portar a cua les operacions que continuen sent pesades despres de les fases anteriors.

### Scope
- Creacio massiva de grups des de sorting.
- Auto-creacio d'equips.
- Reassignacions massives de grups/equips.
- Rebuilds de caches o valors derivats cars.

### Infraestructura Reutilitzable
- Celery disponible.
- Redis disponible.
- Patrons de `task_status_view`, polling i SSE ja existents al projecte.

### Estrategia Recomanada
- Crear model de job propi del modul d'inscripcions o reutilitzar un patro consistent de `task_id + payload + status + progress + result`.
- La UI ha de poder:
- encolar tasca,
- rebre `task_id`,
- fer polling d'estat,
- mostrar progress i resultat,
- refrescar nomes les zones afectades quan la tasca acaba.

### Operacions Que NO Han D'Anar A Cua
- Canvis d'una sola inscripcio.
- Rename simple.
- Reorder curt local.
- Petites assignacions que poden respondre en temps curt.

### Proves
- La UI no queda bloquejada.
- Reintents i errors de tasca es mostren be.
- Si la tasca finalitza, la pagina es refresca parcialment, no completa.

### Definition Of Done
- Existeix almenys un flux massiu real passat a async amb estat visible i UX correcta.

### Handoff Per A Un Agent Extern
- Llegir primers els patrons de `designacions` i `marbella_informes`.
- No inventar un sistema nou si el projecte ja te un patro suficient.

## Fase 10. Hardening, Observabilitat I Tancament

### Prioritat
- P2

### Objectiu
- Tancar el refactor amb seguretat operativa i dades de millora.

### Scope
- Logs de timings.
- Metrica de consultes lentes.
- Comparativa abans/despres.
- Runbook de regressions.

### Tasques
- Afegir logs estructurats de temps per endpoints critics.
- Documentar flags o modes debug.
- Actualitzar tests i manual intern del modul si canvia el flux UX.

### Definition Of Done
- Es pot demostrar amb dades que la latencia ha baixat.
- L'equip te guies per diagnosticar regressions futures.

## Ordre Recomanat D'Execucio
- Fase 0
- Fase 1
- Fase 2
- Fase 3
- Fase 4
- Fase 5
- Fase 6
- Fase 7
- Fase 8
- Fase 9
- Fase 10

## Dependencies Entre Fases
- La Fase 1 facilita molt la Fase 2 i la Fase 3.
- La Fase 3 dona guany UX immediat encara sense haver reescrit consultes.
- La Fase 5 i la Fase 6 son les fases que mes redueixen cost de CPU i BD.
- La Fase 9 nomes te sentit un cop el cami sincron ja esta prou afinat.

## Repartiment Recomanat Per Agents Externs
- Agent A: Fase 1.
- Agent B: Fase 2 i Fase 3.
- Agent C: Fase 4 i Fase 5.
- Agent D: Fase 6.
- Agent E: Fase 7 i Fase 8.
- Agent F: Fase 9 i Fase 10.

## Criteris De Qualitat Transversals
- No barrejar refactor estructural i canvi de comportament si no es imprescindible.
- Tota fase ha d'incloure smoke tests i una nota de riscos.
- Tota fase ha de documentar quins fitxers toca i quins contractes canvia.
- Evitar PRs o lots massa grans; millor lliuraments petits i validables.

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




PLA 2:

# Separació de `competicions_trampoli/tests.py` en paquet `tests/`

## Resum
Refactor estructural, sense canvis funcionals, per substituir [`competicions_trampoli/tests/`](/c:/Users/Guillem Merino/Desktop/ceeb_web/competicions_trampoli/tests/__init__.py) com a nou punt d’entrada dels tests amb fitxers per domini. L’objectiu és mantenir `manage.py test competicions_trampoli.tests` estable i preservar al màxim els labels antics via reexports a `tests/__init__.py`.

## Canvis principals
- Convertir `competicions_trampoli.tests` de mòdul únic a paquet:
  - eliminar el fitxer únic i crear `competicions_trampoli/tests/__init__.py`
  - moure `_BaseTrampoliDataMixin` a `competicions_trampoli/tests/base.py`
  - mantenir noms de classes i noms de tests exactament iguals en aquesta fase

- Fer la partició per domini, amb aquest layout:
  - `test_templates_and_sort_basics.py`
    - `CompeticioBackgroundTemplateTagTests`
    - `ScoringEngineAliasResolutionTests`
    - `CustomSortOrderFallbackTests`
  - `test_inscripcions_sort_groups.py`
    - `InscripcionsSortFlowTests`
    - `GroupNameSyncTests`
    - `ProgrammedGroupReconfigurationTests`
    - `GroupManagerV1Tests`
  - `test_inscripcions_forms_media.py`
    - `InscripcioManualFormViewTests`
    - `InscripcioAparellExclusioModelTests`
    - `InscripcionsSetAparellsViewTests`
    - `InscripcionsMediaFlowTests`
  - `test_scoring_judge.py`
    - `ScoringMediaPlaybackContextTests`
    - `ScoringAndJudgeExclusionFlowTests`
    - `JudgeVideoApiTests`
    - `JudgeMessagingFlowTests`
    - `ScoringUpdatesCursorTests`
  - `test_rotacions.py`
    - `RotationOrderingDisplayTests`
  - `test_classificacions.py`
    - `ClassificacioMatrixScalarTests`
    - `ClassificacioFilterSemanticsTests`
    - `ClassificacionsExportExcelTests`
    - `ClassificacioTemplateFlowTests`
    - `GlobalClassificacioTemplateManagementTests`
    - `LiveClassificacionsRedisCacheTests`
  - `test_access_and_catalog.py`
    - `CompetitionAccessControlTests`
    - `AparellOwnershipIsolationTests`
    - `PublicLiveTokenViewsTests`
  - `test_equips_context.py`
    - `EquipContextFlowTests`
    - `EquipPreviewUiTests`
    - `EquipContextClassificacioTests`
    - `EquipContextHistorySnapshotTests`
    - `BaseTeamContextAuditCommandTests`
  - `test_team_scoring.py`
    - `TeamMemberTreatmentSchemaTests`
    - `TeamContextScoringFlowTests`

- Mantenir compatibilitat forta:
  - `tests/__init__.py` importarà i reexportarà totes les classes `TestCase`
  - això manté estable `manage.py test competicions_trampoli.tests`
  - també manté, en la pràctica, la majoria de labels antics per classe sota `competicions_trampoli.tests.<Classe>`
  - no es reanomenarà cap classe ni cap mètode de test en aquesta passada

- Estructuració interna:
  - només s’extrauran helpers clarament globals a `base.py`
  - els helpers locals de cada classe es quedaran al seu fitxer per evitar barrejar responsabilitats en el mateix refactor
  - no s’aprofitarà aquesta passada per deduplicar proves ni canviar assertions

- Ajustos col·laterals mínims:
  - actualitzar qualsevol documentació interna que encara referenciï `competicions_trampoli/tests.py`, com [desplegament_autenticacio_i_accessos.md](/c:/Users/Guillem Merino/Desktop/ceeb_web/competicions_trampoli/docs/desplegament_autenticacio_i_accessos.md#L264)
  - no tocar altres apps del projecte en aquesta fase

## Interfícies i compatibilitat
- El contracte estable de descoberta de tests serà:
  - `manage.py test competicions_trampoli.tests`
  - labels nous per fitxer, per exemple `competicions_trampoli.tests.test_classificacions`
- El contracte de compatibilitat a preservar serà:
  - import de `competicions_trampoli.tests`
  - accés a les classes reexportades des de `tests/__init__.py`
- No es garantirà compatibilitat amb paths antics basats en números de línia ni amb referències documentals a un fitxer únic.

## Pla de validació
- Verificar discovery global:
  - `manage.py test competicions_trampoli.tests`
- Verificar compatibilitat per classe antiga:
  - almenys una classe de cada domini via label antic reexportat
- Verificar labels nous per mòdul:
  - un fitxer de cada domini via `competicions_trampoli.tests.test_*`
- Comprovar que no hi ha imports circulars:
  - `tests/__init__.py` només agrega i reexporta
  - `base.py` no importa cap mòdul de tests
- Confirmar que el recompte de classes i tests es manté igual abans i després del refactor

## Assumptions
- Aquesta passada és només estructural; no inclou neteja de tests obsolets ni creació de nous tests.
- Es prioritza risc baix i compatibilitat màxima per sobre d’una arquitectura de helpers més agressiva.
- La resta d’apps poden continuar amb `tests.py` monolític; no s’alinearan ara.




# Tancament de la fase d’`inscripcions`

## Resum
La fase només es donarà per tancada quan es compleixin tres coses alhora: `equips_context` verd, `views.py` i `inscripcions_list_new.py` reduïts a façana real, i smoke estable de rutes/render/payloads d’`inscripcions`.

Decisió de contracte adoptada per aquest pla:
- El contracte oficial d’aplicació és `native` autoassegurat pel servei/model quan el flux funcional entra al domini.
- Les eines d’auditoria han de llegir estat persistent cru i no poden introduir side effects.
- Els tests s’han d’alinear amb aquesta separació: fluxos normals reutilitzen helper/servei; auditories validen estat cru explícitament preparat pel test.

## Implementació de tancament
### 1. Tancar la regressió d’`equips_context`
- Abans de tocar la lògica, documentar i fer explícita la regla anterior dins del codi i dels tests rellevants.
- Revisar `views_equips.py` a `equips_assign`, `equips_workspace` i `equips_preview` perquè el comportament sigui coherent amb equips contextuals, equips base i dades legacy.
- Garantir que un equip usat en context custom es resol de forma consistent amb el seu `context`, i que els fluxos no depenen accidentalment d’equips creats al context base.
- Reconciliar `resolve_inscripcio_equip`, `get_equips_for_context`, workspace, preview i classificacions perquè `assignment_source.mode="context"` amb `fallback="native"` torni a separar correctament equip contextual i equip base.
- Ajustar `audit_base_team_context` i els seus tests perquè l’auditoria inspeccioni estat cru sense auto-crear `native`, però sense contradir el contracte general del runtime.
- No canviar URLs, payloads ni contractes UI mentre es corregeix aquest bloc.

### 2. Deixar `views.py` i `inscripcions_list_new.py` com a façana real
- Fer una cerca prèvia de consumidors interns, tests i `patch()` sobre `views.py` i `inscripcions_list_new.py` abans de buidar-los.
- Migrar qualsevol test o `patch()` que encara depengui d’aquests mòduls com a implementació real, cap als entrypoints nous o serveis estables.
- Un cop els consumidors estiguin identificats, eliminar de `views.py` tota la lògica activa d’`inscripcions` que avui està duplicada.
- Eliminar d’`inscripcions_list_new.py` la implementació activa de listing/groups/media i deixar només compatibilitat mínima temporal si encara hi ha imports residuals.
- Mantenir intactes noms públics, exports necessaris, URLs, plantilles i shapes de payloads AJAX.

### 3. Consolidar la validació de tancament d’`inscripcions`
- Deixar smoke d’imports dels mòduls `views_inscripcions_listing`, `views_inscripcions_sorting`, `views_inscripcions_groups`, `views_inscripcions_media` i `inscripcions_views_shared`.
- Deixar smoke de `reverse()/resolve()` de totes les rutes d’`inscripcions`.
- Deixar render smoke de `inscricpions_list_new.html` validant `200`, plantilla correcta i context mínim esperat.
- Afegir comprovacions de contracte per payloads AJAX de sorting, groups i media, validant claus i forma pública, no implementació interna.
- Mantenir la validació mínima obligatòria com a seqüència curta i repetible per pre-merge; en execució Docker no interactiva, usar `--keepdb`.

### 4. Criteri de tancament de fase
- `python manage.py check`
- `python manage.py test competicions_trampoli.tests.test_inscripcions_sort_groups --keepdb`
- `python manage.py test competicions_trampoli.tests.test_inscripcions_forms_media --keepdb`
- `python manage.py test competicions_trampoli.tests.test_equips_context --keepdb`
- `python manage.py test competicions_trampoli.tests.test_inscripcions_backend_smoke --keepdb`
- smoke d’imports, rutes i render d’`inscripcions`
- cap `views_inscripcions_*` importa `views.py` o `inscripcions_list_new.py`
- `inscripcions_views_shared.py` no importa `views.py`
- `views.py` no conté lògica activa d’`inscripcions`
- `inscripcions_list_new.py` no conté implementació activa del domini

## Passos futurs per a un altre agent
### 1. Backend de `classificacions`
- Convertir en reals `views_classificacions_builder`, `views_classificacions_live`, `views_classificacions_templates` i `views_classificacions_export`.
- Substituir la dependència efectiva de `views_classificacions.py`.
- Començar a eliminar reexports des de `services_classificacions_2.py` cap a serveis nous estables.
- Mantenir `validation.py` com a font de veritat per mètriques i `error_details`.
- Migrar en paral·lel tests i `patch()` que encara apunten a `views_classificacions.py` o `services_classificacions_2.py`.

### 2. Frontend d’`inscripcions`
- Un cop el backend estigui verd, consolidar bootstrap JSON de la pantalla en un únic punt coherent.
- Extreure el JS inline principal i scripts auxiliars a `static/js`.
- No tocar DOM, selectors, `data-*`, URLs ni payloads.

### 3. Frontend de `classificacions`
- Mateix patró que `inscripcions`: bootstrap estable, JS extern, contracte HTML intacte.
- Els tests han de validar contracte de dades i càrrega d’assets, no implementació inline.

### 4. Neteja final i professionalització
- Eliminar façanes sense consumidors.
- Reduir imports legacy residuals.
- Afegir runbook curt de verificació i contribució.
- Definir subset mínim obligatori de CI i subset extens de regressió.
- Tancar amb un criteri formal de `done`: imports nets, contractes estables, suite del domini verda i documentació actualitzada.

## Test plan
- Primer: `python manage.py check`
- Després: `python manage.py test competicions_trampoli.tests.test_equips_context --keepdb`
- Després: `python manage.py test competicions_trampoli.tests.test_inscripcions_sort_groups --keepdb` i `python manage.py test competicions_trampoli.tests.test_inscripcions_forms_media --keepdb`
- Després: `python manage.py test competicions_trampoli.tests.test_inscripcions_backend_smoke --keepdb`
- Després: smoke d’imports, `reverse()/resolve()`, render i payloads AJAX d’`inscripcions`
- Quan entri a `classificacions`: suite curta específica per builder/live/templates/export abans de buidar monòlits

## Assumptions i defaults
- No es toquen URLs, plantilles ni shapes de payloads en aquesta fase.
- `native` continua sent únic per competició.
- El runtime autoassegura `native`; l’auditoria inspecciona estat cru sense side effects.
- La fase actual només cobreix backend d’`inscripcions`; `classificacions`, frontend i professionalització són treball posterior.

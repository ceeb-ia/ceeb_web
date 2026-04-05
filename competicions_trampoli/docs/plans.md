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





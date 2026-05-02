# Pla Per Afegir Confirmacio De Notes I Mode Competicio Guiat Al Portal De Jutges

## Estatus Del Document
- Document operatiu per subagents.
- Objectiu: guiar una implementacio orquestrada per un agent principal.
- Abast funcional:
  - confirmacio abans de desar notes per exercici
  - mode competicio guiat, entrant i sortint des de qualsevol participant/exercici
  - auto-avanc controlat entre camps de puntuacio
  - continuacio automatica cap al seguent participant/exercici segons ordre de competicio
- Aquest pla assumeix el portal de jutges ja desmonolititzat en:
  - `competicions_trampoli/templates/judge/portal/`
  - `competicions_trampoli/templates/judge/portal/scripts/`

## Resum Executiu
El portal actual ja te una base adequada:
- el backend construeix grups en ordre de competicio
- el mode `competition_order` ja renderitza primer tots els exercicis 1, despres tots els exercicis 2, etc.
- el client te `DRAFTS` i `DIRTY_BY_ENTRY`
- `saveNow(insId, exercici)` envia un `inputs_patch` per un exercici concret
- el servidor revalida permisos, camps, jutge, rang d'items i crash abans de persistir

La implementacio recomanada es mantenir el contracte actual de guardat i afegir:
1. un modal comu de confirmacio abans de qualsevol POST
2. una cua client-side d'entrades en ordre competitiu
3. un modal de Mode Competicio que reutilitzi el renderer d'editors actual
4. auto-avanc tolerant amb decimals i sempre reversible amb Enter/Tab

## Objectius
- Donar seguretat al jutge abans d'enviar una nota.
- Accelerar l'entrada de notes sense perdre control.
- Permetre entrar al Mode Competicio des de qualsevol participant/exercici.
- Permetre sortir del Mode Competicio i tornar a revisar el portal normal.
- Permetre reentrar al Mode Competicio des de:
  - la posicio actual
  - un participant/exercici concret
  - el primer pendent del grup actiu
- Reaprofitar l'endpoint actual `judge_save_partial`.
- Mantenir compatibilitat amb:
  - mode compacte
  - mode ordre competicio
  - context individual
  - context equip
  - permisos de QR
  - video
  - polling d'updates

## No Objectius
- No canviar el model de dades.
- No canviar la semantica de puntuacio.
- No substituir `judge_save_partial`.
- No crear una SPA nova.
- No canviar el sistema de permisos.
- No eliminar les visualitzacions actuals.
- No automatitzar el desat sense confirmacio explicita.
- No fer auto-avanc agressiu que pugui impedir escriure decimals.

## Mapa Actual Relevant

### Backend
- `competicions_trampoli/views/judge/portal.py`
  - construeix `group_blocks`
  - construeix `out_of_program_group_blocks`
  - calcula `exercicis`
  - resol `portal_display_mode`
  - envia `subjects_payload_json` i `scores_payload_json`
- `competicions_trampoli/views/judge/save.py`
  - endpoint `judge_save_partial`
  - valida token
  - resol subjecte
  - sanititza patch per permisos
  - calcula amb `ScoringEngine`
  - desa `ScoreEntry` o `TeamScoreEntry`
- `competicions_trampoli/views/judge/updates.py`
  - polling incremental d'updates

### Templates
- `competicions_trampoli/templates/judge/portal/_header.html`
  - capcalera i controls generals
- `competicions_trampoli/templates/judge/portal/_group_panes.html`
  - render dels grups
- `competicions_trampoli/templates/judge/portal/modes/_group_competition_order.html`
  - ordre competitiu actual per exercici
- `competicions_trampoli/templates/judge/portal/modes/_entry_card_compact.html`
  - targeta en mode compacte
- `competicions_trampoli/templates/judge/portal/modes/_entry_card_competition_order.html`
  - targeta per `subjecte + exercici`
- `competicions_trampoli/templates/judge/portal/modes/_exercise_panel.html`
  - accions de desar i contenidor d'editor

### Scripts
- `competicions_trampoli/templates/judge/portal/scripts/_00_bootstrap.js.html`
  - constants globals i JSON inicial
- `competicions_trampoli/templates/judge/portal/scripts/_10_store.js.html`
  - `SCORES`, `DRAFTS`, navegacio d'inputs, helpers de focus
- `competicions_trampoli/templates/judge/portal/scripts/_20_permissions.js.html`
  - resolucio de permisos i `updateDraftValue`
- `competicions_trampoli/templates/judge/portal/scripts/_50_exercises.js.html`
  - obertura de panells i estat visual d'exercicis
- `competicions_trampoli/templates/judge/portal/scripts/_60_navigation.js.html`
  - grups, drawer i focus de targetes
- `competicions_trampoli/templates/judge/portal/scripts/_70_editor_render.js.html`
  - render dels inputs segons schema/permisos
- `competicions_trampoli/templates/judge/portal/scripts/_80_save_updates.js.html`
  - `buildPatchFromCard`, `saveNow`, polling d'updates
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`
  - inicialitzacio global

## Contractes Que No Es Poden Trencar

### Contracte De Guardat
`judge_save_partial` ha de continuar rebent el mateix payload:

```json
{
  "subject_kind": "inscripcio",
  "subject_id": 123,
  "inscripcio_id": 123,
  "exercici": 1,
  "inputs_patch": {}
}
```

Per context equip:

```json
{
  "subject_kind": "team_unit",
  "subject_id": 456,
  "exercici": 1,
  "inputs_patch": {}
}
```

### Contracte Client
- `DRAFTS[entryKey(insId, exercici)]` continua sent la font dels canvis locals.
- `DIRTY_BY_ENTRY[entryKey(insId, exercici)]` continua indicant canvis pendents.
- `SCORES[domId].exercises[ex]` continua sent la font del valor desat.
- `subjectForId(insId)` continua resolent subjectes individuals i d'equip.
- `buildPatchFromCard(insId, exercici)` continua generant el patch que s'envia.
- `saveNow(insId, exercici)` pot canviar internament, pero ha de mantenir la signatura global.

### Contracte DOM
- No canviar ids existents sense adaptar tots els consumidors:
  - `editor-inner-{insId}-{exercici}`
  - `status-{insId}-{exercici}`
  - `data-exercise-panel`
  - `data-ins-id`
  - `data-exercici`
  - `data-group-pane`
- Els nous modals han d'usar ids nous i prefixats, per exemple:
  - `scoreConfirmModal`
  - `competitionModeModal`
  - `competitionModeEditorHost`

## Principis D'Implementacio
- Primer fer confirmacio comuna, despres Mode Competicio.
- El Mode Competicio ha de reutilitzar les funcions actuals quan sigui possible.
- El desat real sempre passa pel mateix endpoint i les mateixes validacions.
- El modal de competicio no ha de destruir drafts del portal normal.
- Sortir del modal no ha de perdre canvis pendents.
- Els salts automatics han de ser assistits, no obligatoris.
- Enter sempre ha de funcionar com a avanc explicit.
- Tab i Shift+Tab han de seguir sent previsibles.
- La navegacio per cua ha de ser client-side mentre no calgui un endpoint nou.

## Riscos Globals
- Duplicar ids `editor-inner-*` si es renderitza el mateix editor dins d'un modal.
- Fer auto-salt massa aviat en decimals com `1.5`.
- Enviar valors no revisats si la confirmacio es pot saltar accidentalment.
- Perdre drafts en tancar el modal.
- Confondre el jutge si el modal i la targeta de fons mostren estats diferents.
- Trencar context equip si el subjecte del modal no conserva `subject_kind`.
- Trencar video o updates si el modal intenta controlar panells que no li pertoquen.
- Crear conflictes entre subagents tocant els mateixos scripts.

## Arquitectura Objectiu

### Confirmacio De Desat
Afegir una capa intermedia:
- `saveNow(insId, exercici)` construeix el patch.
- si hi ha patch, obre modal de confirmacio.
- el modal mostra un resum llegible dels valors.
- en confirmar, crida una funcio interna de POST, per exemple `performSave(insId, exercici, patch, opts)`.
- en cancelar, deixa el draft intacte.

### Mode Competicio
Afegir un estat client-side:

```js
const COMPETITION_MODE = {
  active: false,
  queue: [],
  index: 0,
  current: null,
  autoAdvanceEnabled: true,
  pendingAutoAdvanceTimer: null,
};
```

Cada item de cua:

```json
{
  "insId": "123",
  "exercici": "1",
  "groupTarget": "group-7",
  "groupLabel": "Grup 7",
  "name": "Nom participant",
  "orderLabel": "Ordre 3"
}
```

### Reutilitzacio Del Renderer
Evitar duplicar tota la logica de `renderPermissionBlock`.
Opcions acceptables:
- refactor petit per permetre renderitzar dins un host arbitrari
- o crear un wrapper de modal amb ids propis i una funcio especifica que reutilitzi `renderPermissionBlock`

No es recomana clonar manualment el renderer sencer.

## Fase 0. Baseline I Decisio Final De UX

### Prioritat
- P0

### Objectiu
Fixar el comportament exacte abans de tocar fluxos critics.

### Ownership Recomanat
- Agent principal

### Tasques
- Confirmar textos de botons i estats:
  - `Mode competicio`
  - `Comencar des d'aqui`
  - `Confirmar i desar`
  - `Desar i seguent`
  - `Sortir`
- Decidir si el boto de Mode Competicio apareix:
  - a la capcalera
  - a cada panell d'exercici
  - a les dues ubicacions
- Decidir comportament per defecte en obrir des de capcalera:
  - primer pendent del grup actiu
  - primera entrada del grup actiu
- Decidir si les entrades ja desades es poden saltar automaticament o nomes marcar com desades.

### Definition Of Done
- Hi ha decisions UX escrites al PR o issue.
- Cap codi canviat encara, excepte si es documenta.

### Handoff Per Subagent
- No implementis.
- Entrega nomes decisions i dubtes.

## Fase 1. Modal Comu De Confirmacio De Desat

### Prioritat
- P0

### Objectiu
Fer que qualsevol `Desa` mostri un resum abans d'enviar al servidor.

### Ownership Recomanat
- Agent A

### Fitxers Candidats
- `competicions_trampoli/templates/judge/portal/modes/_exercise_panel.html`
- `competicions_trampoli/templates/judge/portal/_group_panes.html` o un nou parcial:
  - `competicions_trampoli/templates/judge/portal/_score_confirm_modal.html`
- `competicions_trampoli/templates/judge/portal/scripts/_80_save_updates.js.html`
- si cal formatar valors:
  - `competicions_trampoli/templates/judge/portal/scripts/_20_permissions.js.html`
  - `competicions_trampoli/templates/judge/portal/scripts/_70_editor_render.js.html`

### Tasques
- Crear markup del modal de confirmacio.
- Separar `saveNow` en dues parts:
  - preparar patch i obrir confirmacio
  - executar POST real
- Afegir helper per construir resum del patch:
  - camp
  - label del camp
  - jutge
  - item o rang
  - membre, si aplica
  - valor nou
- Mostrar crash si forma part del patch.
- Mantenir el draft si el jutge cancela.
- Evitar doble submit mentre el POST esta en curs.
- Despres de guardar, mantenir el comportament actual:
  - actualitzar `SCORES`
  - netejar draft i dirty
  - rerender editor
  - refrescar estats
  - status `Desat`

### Tests
- Test funcional JS manual o browser si hi ha infraestructura disponible:
  - escriure valor
  - premer Desa
  - veure modal
  - cancelar
  - comprovar draft pendent
  - confirmar
  - comprovar que es desa
- Test backend no necessari si no canvia endpoint.

### Definition Of Done
- Cap nota es desa des del portal normal sense confirmacio.
- Cancelar no perd canvis.
- Confirmar usa el mateix endpoint actual.
- Errors del servidor es mostren com abans.

### Handoff Per Subagent
- No toquis Mode Competicio.
- No canviis permisos ni backend.
- Lliura els fitxers modificats i una llista de casos provats.

## Fase 2. Infraestructura De Cua Del Mode Competicio

### Prioritat
- P0

### Objectiu
Construir una cua client-side d'entrades ordenada segons el grup actiu i l'ordre competitiu actual.

### Ownership Recomanat
- Agent B

### Fitxers Candidats
- `competicions_trampoli/templates/judge/portal/scripts/_60_navigation.js.html`
- nou script parcial:
  - `competicions_trampoli/templates/judge/portal/scripts/_65_competition_mode_queue.js.html`
- `competicions_trampoli/templates/judge/portal.html` nomes integrador
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`

### Tasques
- Afegir funcio `buildCompetitionModeQueue(groupTarget)`.
- La cua ha de respectar:
  - grup actiu
  - ordre DOM actual en mode `competition_order`
  - si el portal esta en mode compacte, reconstruir equivalent: exercici 1 per tots, exercici 2 per tots, etc.
- Afegir helper `findCompetitionQueueIndex(queue, insId, exercici)`.
- Afegir helper `firstPendingCompetitionQueueIndex(queue)`.
- Afegir helper `competitionQueueItemState(item)`:
  - `empty`
  - `dirty`
  - `saved`
- Afegir entrada des de qualsevol participant/exercici:
  - `openCompetitionModeFromEntry(insId, exercici)`
- Afegir entrada des de capcalera:
  - `openCompetitionModeFromCurrentGroup()`
- No renderitzar encara modal d'entrada si la fase 3 no esta feta.

### Tests
- Unit test JS no disponible probablement; fer verificacio manual guiada.
- Comprovar cues en:
  - mode compacte
  - mode ordre competicio
  - diversos exercicis
  - grups fora de programa
  - context equip si aplica

### Definition Of Done
- La cua generada es correcta i estable.
- Es pot calcular l'index inicial des de qualsevol targeta.
- No hi ha canvis visuals obligatoris encara.

### Handoff Per Subagent
- No implementis modal ni auto-avanc.
- Mantingues funcions petites i globals si el portal segueix aquest patro.
- Documenta exemples de cua esperada.

## Fase 3. Modal Del Mode Competicio I Navegacio Entrar/Sortir

### Prioritat
- P0

### Objectiu
Crear el modal de Mode Competicio i permetre entrar/sortir sense perdre context.

### Ownership Recomanat
- Agent C

### Fitxers Candidats
- nou parcial:
  - `competicions_trampoli/templates/judge/portal/_competition_mode_modal.html`
- `competicions_trampoli/templates/judge/portal/_header.html`
- `competicions_trampoli/templates/judge/portal/modes/_exercise_panel.html`
- nou script parcial:
  - `competicions_trampoli/templates/judge/portal/scripts/_66_competition_mode_modal.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_90_init.js.html`
- `competicions_trampoli/templates/judge/portal.html` nomes integrador

### Tasques
- Afegir boto global a la capcalera.
- Afegir boto contextual a cada panell d'exercici per comencar des d'aquella entrada.
- Crear modal amb:
  - nom participant/equip
  - grup
  - exercici
  - posicio `n / total`
  - estat actual
  - host d'editor
  - botons `Anterior`, `Seguent`, `Desar`, `Sortir`
- Obrir modal en una posicio concreta de la cua.
- Tancar modal sense netejar drafts.
- En sortir, opcionalment enfocar la targeta corresponent al portal normal.
- Navegar anterior/seguent sense desar nomes si:
  - no hi ha dirty
  - o el jutge confirma que vol deixar canvis pendents
- No fer encara auto-avanc entre inputs si la fase 4 no esta feta.

### Risc Principal
El renderer actual depen de ids `editor-inner-{insId}-{exercici}`. El modal no pot duplicar aquests ids.

### Estrategia Recomanada
- Afegir una funcio nova de render d'editor a host arbitrari:
  - `renderEditorInto(wrap, insId, exercici, opts)`
- Fer que `renderEditor(insId, exercici, opts)` sigui un wrapper que localitza l'element existent i delega a `renderEditorInto`.
- El modal pot tenir un host amb id propi i cridar `renderEditorInto(host, insId, exercici, { force: true, competitionMode: true })`.

### Tests
- Obrir des de capcalera.
- Obrir des d'un participant concret.
- Sortir i revisar portal normal.
- Reentrar des d'un altre participant.
- Confirmar que drafts pendents no desapareixen.

### Definition Of Done
- El Mode Competicio es pot obrir i tancar.
- Es pot entrar des de qualsevol participant/exercici.
- No hi ha ids duplicats.
- El portal normal continua funcionant.

### Handoff Per Subagent
- Coordina't amb Agent B per noms de funcions de cua.
- No canviis el POST de desat si Agent A ja l'ha separat.
- No implementis heuristiques d'auto-avanc encara.

## Fase 4. Auto-Avanc Controlat Entre Camps

### Prioritat
- P1

### Objectiu
Fer que el jutge pugui entrar valors mes rapidament sense que el sistema salti massa aviat.

### Ownership Recomanat
- Agent D

### Fitxers Candidats
- `competicions_trampoli/templates/judge/portal/scripts/_10_store.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_70_editor_render.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_66_competition_mode_modal.js.html`

### Regles D'Auto-Avanc
- Enter sempre avanca si el valor actual es acceptable.
- Tab i Shift+Tab mantenen comportament esperat.
- En Mode Competicio, input valid pot auto-avancar despres d'un retard curt.
- Retard recomanat: 300 ms.
- Si el jutge continua escrivint abans del retard, cancelar i reprogramar.
- No auto-avancar amb valor buit.
- No auto-avancar amb valor no numeric.
- No auto-avancar amb text acabat en separador decimal:
  - `1.`
  - `1,`
- Per decimals:
  - `1` es valid si el camp admet decimals
  - `0` es valid si el camp admet decimals
  - `1.0`, `0.0`, `8.5` son valids
  - no exigir sempre decimals explicits
- Per enters:
  - nomes valors enters
  - si el camp te `decimals` 0 o absent, `1.5` no ha d'auto-avancar
- Si el schema defineix min/max en el futur o ja existeix en alguns camps, respectar-los si son presents.
- El boto de crash no ha de disparar auto-avanc numeric.

### Helper Recomanat
Afegir funcio pura:

```js
function scoreInputCompletionState(input, field){
  return {
    complete: true,
    valid: true,
    reason: "",
  };
}
```

### Tasques
- Marcar inputs del modal de competicio amb context `competitionMode`.
- Afegir listener d'input que nomes auto-avanci si el Mode Competicio esta actiu.
- Reutilitzar `focusNextEditableInput` si pot treballar dins el modal.
- Si l'ultim camp queda complet, enfocar boto `Desar` o mostrar estat `Llest per desar`.
- Afegir toggle per activar/desactivar auto-avanc dins el modal.

### Tests
- Camps enters:
  - `1` avanca
  - `1.5` no avanca si decimals 0
- Camps decimals:
  - `1` avanca despres del retard
  - `0` avanca despres del retard
  - `1.` no avanca
  - `1.5` avanca despres del retard
  - escriure `1.5` no queda interromput pel salt en `1`
- Enter avanca sempre quan el valor es valid.
- Backspace o edicio manual no deixa focus en estat incoherent.

### Definition Of Done
- Auto-avanc nomes funciona en Mode Competicio.
- El portal normal conserva la navegacio Enter/Tab actual.
- Decimals enters com `1` i `0` son tractats com valors valids.
- No hi ha salts prematurs amb `1.`.

### Handoff Per Subagent
- No canviis validacions backend.
- No assumeixis que tots els camps tenen min/max.
- Prioritza control sobre velocitat.

## Fase 5. Desar, Confirmar I Avancar Automaticament A La Seguent Entrada

### Prioritat
- P0 despres de fases 1-4

### Objectiu
Connectar el Mode Competicio amb el flux de confirmacio i passar automaticament a la seguent entrada despres d'un desat correcte.

### Ownership Recomanat
- Agent E

### Fitxers Candidats
- `competicions_trampoli/templates/judge/portal/scripts/_80_save_updates.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_66_competition_mode_modal.js.html`
- `competicions_trampoli/templates/judge/portal/scripts/_65_competition_mode_queue.js.html`

### Tasques
- Fer que el boto `Desar` del Mode Competicio cridi el mateix flux de confirmacio.
- Passar opcions al guardat:
  - `source: "competition_mode"`
  - `advanceOnSuccess: true`
- Despres de confirmacio i POST correcte:
  - actualitzar estat com al portal normal
  - refrescar estat de la cua
  - carregar seguent item
- Si no hi ha seguent item:
  - mostrar estat `Grup completat` o `Final de la cua`
  - permetre sortir o tornar a primer pendent
- Si el POST falla:
  - quedar-se al mateix item
  - mostrar error
  - no perdre draft
- Si no hi ha canvis pendents:
  - permetre `Seguent`
  - o mostrar `No hi ha canvis pendents`

### Tests
- Desar i avancar a seguent participant.
- Desar ultim participant d'exercici 1 i passar a primer participant d'exercici 2.
- Error backend no avanca.
- Cancelar confirmacio no avanca.
- Entrades ja desades es mostren com a desades.

### Definition Of Done
- Mode Competicio permet flux complet: introduir, desar, confirmar, seguent.
- El portal normal veu l'estat actualitzat.
- La confirmacio es comuna i no duplicada.

### Handoff Per Subagent
- Coordina't amb Agent A per la API interna del guardat.
- No dupliquis codi de fetch.
- Lliura casos manuals provats.

## Fase 6. Poliment UX, Accessibilitat I Resiliencia

### Prioritat
- P1

### Objectiu
Fer el mode usable en situacio real de competicio.

### Ownership Recomanat
- Agent F

### Fitxers Candidats
- `competicions_trampoli/templates/judge/portal/_styles.html`
- `competicions_trampoli/templates/judge/portal/_competition_mode_modal.html`
- `competicions_trampoli/templates/judge/portal/_score_confirm_modal.html`
- scripts del Mode Competicio

### Tasques
- Assegurar focus inicial correcte.
- Afegir `aria` basic als modals.
- Bloquejar scroll de fons si cal.
- Evitar que els botons canviin de mida amb textos d'estat.
- Mostrar clarament:
  - participant/equip
  - exercici
  - camp/jutge/items
  - estat pendent/desat
- Afegir opcio d'auto-avanc on/off.
- Afegir avis si hi ha canvis pendents en tancar.
- Revisar responsive en mobil/tablet.

### Tests
- Prova en viewport mobil.
- Prova amb teclat.
- Prova amb teclat numeric virtual si possible.
- Prova amb molts items de matrix.

### Definition Of Done
- El modal es usable amb teclat.
- Els textos no se solapen.
- Els controls son clars i estables.
- Tancar amb canvis pendents no es accidental.

### Handoff Per Subagent
- No facis refactors funcionals.
- Mantingues estils acotats a classes noves del mode.

## Fase 7. Tests Automatitzats I Regressio

### Prioritat
- P0 abans de merge final

### Objectiu
Cobrir el comportament critic amb tests.

### Ownership Recomanat
- Agent G

### Fitxers Candidats
- `competicions_trampoli/tests/scoring/judge/`
- `competicions_trampoli/tests/browser/` si la infraestructura ho permet
- tests existents de portal/save si n'hi ha d'aplicables

### Tasques
- Afegir tests backend si s'ha tocat backend.
- Si no s'ha tocat backend, ampliar tests de contracte del portal quan sigui practic:
  - markup dels nous modals present
  - controls presents
  - contracte JSON intacte
- Afegir test browser si viable:
  - omplir camp
  - obrir confirmacio
  - cancelar
  - confirmar
  - verificar desat
- Afegir test o comprovacio manual documentada per:
  - mode compacte
  - mode ordre competicio
  - context equip
  - decimals `1`, `0`, `1.0`, `1.5`, `1.`

### Definition Of Done
- Tests rellevants passen.
- Hi ha una checklist manual per allò que no es pugui automatitzar.

### Handoff Per Subagent
- No arreglis funcionalitat fora de l'abast sense avisar.
- Si detectes bug, informa amb fitxer/linia i escenari minim.

## Sequencia Recomanada D'Orquestracio

### Onada 1
- Agent A: confirmacio de desat.
- Agent B: cua client-side del Mode Competicio.

Aquestes tasques poden anar en paral.lel si no editen els mateixos fitxers. L'integrador ha de reservar-se `portal.html` si cal incloure nous parcials.

### Onada 2
- Agent C: modal de Mode Competicio.
- Agent D: auto-avanc controlat.

Agent D pot preparar helpers purs mentre Agent C integra el modal, pero la connexio final amb inputs del modal s'ha de fer despres.

### Onada 3
- Agent E: desar-confirmar-seguent.
- Agent F: poliment UX/accessibilitat.

### Onada 4
- Agent G: tests i regressio.
- Agent principal: revisio final, resolucio de conflictes i prova completa.

## Write Scopes Recomanats

### Agent A
- Pot editar:
  - `_80_save_updates.js.html`
  - nou `_score_confirm_modal.html`
  - `_group_panes.html` o wrapper d'inclusio acordat
- No ha d'editar:
  - scripts de cua
  - modal de Mode Competicio

### Agent B
- Pot editar:
  - nou `_65_competition_mode_queue.js.html`
  - `_60_navigation.js.html` si cal exposar helpers
- No ha d'editar:
  - `_80_save_updates.js.html`
  - `_70_editor_render.js.html`

### Agent C
- Pot editar:
  - nou `_competition_mode_modal.html`
  - nou `_66_competition_mode_modal.js.html`
  - `_header.html`
  - `_exercise_panel.html`
  - `_70_editor_render.js.html` nomes per `renderEditorInto`
- No ha d'editar:
  - logica de POST real

### Agent D
- Pot editar:
  - `_10_store.js.html`
  - `_70_editor_render.js.html`
  - `_66_competition_mode_modal.js.html`
- No ha d'editar:
  - backend
  - confirmacio de desat

### Agent E
- Pot editar:
  - `_80_save_updates.js.html`
  - `_66_competition_mode_modal.js.html`
  - `_65_competition_mode_queue.js.html`
- No ha d'editar:
  - renderer de camps excepte bug bloquejant

### Agent F
- Pot editar:
  - `_styles.html`
  - modals nous
  - petits ajustos de classes noves
- No ha d'editar:
  - backend
  - contracte de guardat

### Agent G
- Pot editar:
  - tests
  - docs/checklists
- No ha d'editar:
  - implementacio funcional excepte fixes molt petits acordats

## Checklist Final De Regressio
- Portal carrega en mode compacte.
- Portal carrega en mode ordre competicio.
- Selector de visualitzacio continua funcionant.
- Navegacio de grups continua funcionant.
- Drawer d'inscripcions continua funcionant.
- Suport/SOS continua funcionant.
- Video continua funcionant si esta habilitat.
- Es pot desar una nota normal amb confirmacio.
- Cancelar confirmacio conserva draft.
- Error de servidor conserva draft.
- Mode Competicio obre des de capcalera.
- Mode Competicio obre des de participant/exercici.
- Sortir del Mode Competicio no perd canvis.
- Reentrar des d'un altre participant funciona.
- Auto-avanc funciona amb enters.
- Auto-avanc funciona amb decimals escrits com enters: `1`, `0`.
- Auto-avanc no salta amb `1.`.
- Desar en Mode Competicio confirma i passa al seguent.
- Ultima entrada mostra final de cua.
- Context equip conserva membres i subjecte correcte.
- Polling d'updates no trepitja drafts locals.

## Criteri D'Acceptacio Global
- Cap guardat de nota es fa sense confirmacio previa.
- El Mode Competicio es reversible: entrar, sortir, revisar i reentrar.
- El Mode Competicio es agil: focus inicial, auto-avanc controlat i seguent automatic despres de desar.
- El backend continua sent la font d'autoritat de permisos i validacio.
- No hi ha migracions ni canvi de model.
- Tests o checklist manual cobreixen els casos critics.

# Pla D'Implementacio De La Fragmentacio Del Builder De Classificacions Per Subagents

## Objectiu
- Fragmentar `competicions_trampoli/templates/competicio/classificacions_builder_v2.html` en un conjunt de fitxers petits i tractables.
- Mantenir exactament el mateix comportament, HTML renderitzat, contracte DOM, contracte JSON, ids, textos, ajudes i ordre d'execucio del JS.
- Fer-ho de manera que diversos subagents en paral.lel, sense context previ del modul, puguin completar la feina amb write scopes disjunts i handoffs clars.

## Regla Principal
- Aquesta feina es una refactoritzacio estructural, no funcional.
- No es pot canviar cap comportament del builder.
- No es pot canviar cap endpoint, cap `id`, cap `data-help-key`, cap nom de funcio JS, cap text comprovat per tests ni cap path d'entrada consumit per les vistes.
- No es poden deduplicar helpers ni "netejar" duplicats de JS en aquesta fase.
- No es pot moure el JS inline a `static/js` en aquesta fase.

## Punt D'Entrada I Consumidors

### Template canonic
- `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`

### Includes ja existents que s'han de preservar
- `competicions_trampoli/templates/classificacions/puntuacio.html`
- `competicions_trampoli/templates/classificacions/_puntuacio_script.html`

### Vistes consumidores
- `competicions_trampoli/views/classificacions/builder.py`
- `competicions_trampoli/views/classificacions/global_templates.py`

### Modes que han de continuar funcionant
- Builder de competicio
- Builder global de plantilles

## Guardrails De No Regressio

### Paths i contractes que no es poden tocar
- El template d'entrada ha de continuar sent `competicio/classificacions_builder_v2.html`.
- El builder de competicio i el builder global han de continuar renderitzant aquest mateix path.
- S'han de mantenir els includes de:
  - `classificacions_builder_help.css`
  - `classificacions_builder_help.js`
  - `classificacions/puntuacio.html`
  - `classificacions/_puntuacio_script.html`

### Contracte DOM que ha de continuar existint
- `id="can-manage-global-templates"`
- `id="builder-save-url"`
- `id="builder-delete-url-pattern"`
- `id="builder-preview-url-pattern"`
- `id="builder-enable-template-library"`
- `id="builder-can-preview"`
- `id="victoryConfigBox"`
- `id="sVictoryModeCamps"`
- `id="sVictoryModeExercicis"`
- `id="puntuacioSummaryText"`
- `id="candidateScopeHint"`
- `id="classifHelpDrawer"`
- `id="classif-builder-back-to-top"`
- `id="appStaleBanner"`
- `id="previewBox"`
- `id="detailConfigAlert"`
- `id="eqAssignmentContextHint"`
- `id="saveMsg"`

### Contracte JS que ha de continuar renderitzat exactament al HTML final
- Ha d'existir exactament una ocurrencia de `function buildTieAppScopeOptionsHTML(`.
- Han de continuar apareixent al HTML final aquestes signatures:
  - `function pruneSchemaAppReferences(schema, allowedIds)`
  - `function renderAppStaleWarningBanner(schema, selectedIds)`
  - `function filterRawColumnsByAllowedApps(rawCols, allowedIds)`
  - `function pruneDetailSectionsByAllowedApps(rawSections, allowedIds)`
  - `function runSafeHydrationRender(label, renderFn)`
  - `function _buildPretractamentSegment(punt, perAppEntries)`
  - `function _buildScoreSelectionSegment({`
  - `function _buildVictoriesComparisonSegment(victoriesCfg)`
  - `function previewRenderTeamRawDetailCell(v, col)`

### Textos i decisions de producte que no es poden tocar
- No pot reapareixer l'opcio HTML `<option value="entitat">Per entitat</option>`.
- No es poden alterar textos de copy i ajuda ja comprovats pels tests.
- No es poden alterar textos de resum de puntuacio ni variants legacy renderitzades.

## Arbre Objectiu

```text
competicions_trampoli/templates/
  competicio/
    classificacions_builder_v2.html

  classificacions/
    puntuacio.html
    _puntuacio_script.html

    builder/
      _styles.html
      _page_chrome.html
      _json_contract.html
      _help_drawer.html

      sections/
        _meta.html
        _particions.html
        _desempat.html
        _filtres_detail.html
        _presentacio.html

      scripts/
        _00_bootstrap.js.html
        _10_core_ui.js.html
        _20_team_templates_apps.js.html
        _40_ties_and_teams.js.html
        _50_columns_detail_preview.js.html
        _60_particions.js.html
        _70_hydration_sync.js.html
        _80_actions_init.js.html
```

## Criteri Arquitectonic D'Aquesta Fase
- `classificacions_builder_v2.html` ha de quedar com a facade estable.
- Els fitxers nous han de ser, tant com sigui possible, extraccions literals del monolit actual.
- Els dos fitxers de `puntuacio` ja existents s'han de conservar com a unitat estable en aquesta fase.
- L'ordre d'inclusio dels blocs JS ha de preservar l'ordre d'avaluacio actual.

## Estrategia D'Orquestracio

### Regla d'execucio
- Els agents creen fitxers nous amb write sets disjunts.
- Un unic agent d'integracio modifica `classificacions_builder_v2.html`.
- No es permet que dos agents editin el mateix fitxer.
- No es permet que cap agent "millori" el codi mentre l'extreu.

### Fases
- Fase A: extraccio de parcials HTML nous en paral.lel.
- Fase B: extraccio de parcials JS nous en paral.lel.
- Fase C: integracio del facade principal.
- Fase D: verificacio final i correccio d'encaixos.

## Paquets De Feina Per Subagents

## Agent A1. Styles

### Objectiu
- Extreure el bloc `<style>` inline actual a `competicions_trampoli/templates/classificacions/builder/_styles.html`.

### Write set
- `competicions_trampoli/templates/classificacions/builder/_styles.html`

### Input exacte
- Copiar literalment el bloc `<style>` del template monolitic.

### Restriccions
- No convertir a CSS static.
- No reordenar regles.
- No canviar selectors ni comentaris.

### Output esperat
- Un fitxer que contingui exclusivament el bloc `<style>...</style>`.

## Agent A2. Chrome I Shell

### Objectiu
- Extreure l'estructura de pagina i shell principal a `competicions_trampoli/templates/classificacions/builder/_page_chrome.html`.

### Write set
- `competicions_trampoli/templates/classificacions/builder/_page_chrome.html`

### Input exacte
- Toolbar superior
- Selector de plantilles
- `saveMsg`
- `saveErrorsBox`
- columna esquerra `cfgList`
- shell `editorEmpty` / `editorBody`
- navegacio interna
- inclusio dels blocs de seccio
- boto `classif-builder-back-to-top`

### Restriccions
- No absorbir dins d'aquest fitxer ni `json_script`, ni help drawer, ni `<script>`.
- El fitxer pot incloure altres parcials via `{% include %}`.

## Agent A3. Seccio Meta

### Write set
- `competicions_trampoli/templates/classificacions/builder/sections/_meta.html`

### Input exacte
- Bloc `section-meta`
- `classifStatusBox`
- `fNom`
- `fSlug`
- `fTipus`
- `fActiva`
- `equipMetaBox`
- `eqAssignmentContext`
- `eqTeamMode`
- `eqCompatBanner`

### Restriccions
- No tocar cap condicional de `is_global_builder`.

## Agent A4. Seccio Particions

### Write set
- `competicions_trampoli/templates/classificacions/builder/sections/_particions.html`

### Input exacte
- Bloc `section-particions`
- `particionsFieldsBox`
- `particionsCustomBox`
- `particionsDerivedBox`
- `birthYearRangeConfigBox`
- `equipCfgBox`
- `eqIncludeSenseEquip`
- `btnEqManualAdd`
- `eqManualRows`

### Restriccions
- Preservar tots els `data-*` i ids.
- No tocar textos, hints ni ordre intern.

## Agent A5. Seccio Desempat

### Write set
- `competicions_trampoli/templates/classificacions/builder/sections/_desempat.html`

### Input exacte
- Bloc `section-desempat`
- taula de `tieBody`
- `btnTieAdd`
- `btnTieCloneFromPuntuacio`
- textarea `tDesempat`

## Agent A6. Seccions Filtres I Presentacio

### Write set
- `competicions_trampoli/templates/classificacions/builder/sections/_filtres_detail.html`
- `competicions_trampoli/templates/classificacions/builder/sections/_presentacio.html`

### Input exacte
- Bloc `section-filtres`
- Bloc `detailConfigBox`
- textarea `tFiltres`
- Bloc `section-presentacio`
- `iTopN`
- `cEmpats`
- `btnPreview`
- `columnsBox`
- `previewBox`
- `advancedJson`

### Restriccions
- Preservar tots els loops de `filter_choices`.

## Agent A7. Contracte JSON I Help Drawer

### Write set
- `competicions_trampoli/templates/classificacions/builder/_json_contract.html`
- `competicions_trampoli/templates/classificacions/builder/_help_drawer.html`

### Input exacte
- Tots els `json_script` actuals
- Bloc `classifHelpDrawer`
- include final de `classificacions_builder_help.js`

### Restriccions
- Els `json_script` han de conservar exactament els mateixos ids i condicionals.

## Agent B1. Bootstrap JS

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_00_bootstrap.js.html`

### Scope funcional
- `parseJsonScript`
- totes les constants de dades del backend
- constants de mode i URLs
- `DEFAULT_SCHEMA`

### Restriccions
- El fitxer ha de contenir nomes JS, sense etiqueta `<script>`.
- No reordenar constants respecte de les dependencies posteriors.

## Agent B2. Core UI JS

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_10_core_ui.js.html`

### Scope funcional
- `els`
- `state`
- `advancedDirty`
- navegacio interna
- `getCookie`
- `esc`
- `currentCfg`
- mapping d'errors i feedback de save

### Funcions minimes esperades
- `setActiveBuilderNav`
- `updateBuilderNavFromScroll`
- `syncBuilderBackToTopButton`
- `syncBuilderBackToTopButtonPosition`
- `initBuilderSectionNav`
- `registerStaticErrorPaths`
- `clearBuilderSaveFeedback`
- `showBuilderSaveSuccessFeedback`
- `setSaveButtonBusy`
- `builderSectionIdFromErrorPath`
- `normalizeSaveErrorDetails`
- `findBestErrorNode`
- `appendErrorNote`

## Agent B3. Team, Templates I Compatibilitat D'Aparells

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_20_team_templates_apps.js.html`

### Scope funcional
- normalitzacio de tipus i context
- `getCfgStatus`
- `getEquipsUiState`
- copy contextual
- llistat de plantilles globals
- compatibilitat d'aparells
- sanejat de referencies stale
- render i rebuild dels checkboxes d'aparell

### Funcions guardrail
- `pruneSchemaAppReferences`
- `renderAppStaleWarningBanner`
- `filterRawColumnsByAllowedApps`
- `pruneDetailSectionsByAllowedApps`
- `runSafeHydrationRender`

## Agent B4. JS De Desempat I Equips

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`

### Scope funcional
- ties principals
- victory ties
- participants del tie
- equips manuals
- schema d'equips
- lligam entre canvis de tipus/equip i rerender de ties

### Restriccions
- No tocar res del bloc de `puntuacio`.

## Agent B5. JS De Columnes, Detall I Preview

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_50_columns_detail_preview.js.html`

### Scope funcional
- columnes principals
- detall desplegable
- render de files raw
- preview de cel.les i particions

### Funcions guardrail
- `previewRenderTeamRawDetailCell`
- helpers de `previewRenderCellHTML`
- tot el cicle `renderColumnsUI` / `readColumnsUI`
- tot el cicle `renderDetailSectionsUI` / `readDetailSectionsUI`

## Agent B6. JS De Particions

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_60_particions.js.html`

### Scope funcional
- stack de particions
- custom groups
- Sortable
- configuracio de forquilles de naixement

### Restriccions
- Preservar literalment l'us de `Sortable`.
- Preservar l'avisos si `Sortable` no esta carregat.

## Agent B7. JS D'Hydration I Sync

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_70_hydration_sync.js.html`

### Scope funcional
- sanejat per hidratar
- `normalizeForHydration`
- sync de schema des de UI
- sync de UI des de schema
- `selectCfg`

### Funcions guardrail
- `syncAdvancedFromUI`
- `syncUIFromSchema`
- `selectCfg`
- `renderBuilderSaveErrors`

## Agent B8. JS D'Accions I Init

### Write set
- `competicions_trampoli/templates/classificacions/builder/scripts/_80_actions_init.js.html`

### Scope funcional
- `postJson`
- check/apply/save de plantilles
- save/delete/preview
- binding final dels listeners globals
- init final

### Restriccions
- No canviar els missatges ni els fluxos de confirmacio.
- No canviar la sequencia final:
  - `initBuilderSectionNav()`
  - `registerStaticErrorPaths()`
  - `relocateDetailConfigBox()`
  - `buildAparellChecks()`
  - `buildParticioFieldChecks()`
  - `renderList()`

## Agent C1. Integracio Del Facade Principal

### Objectiu
- Convertir `classificacions_builder_v2.html` en facade estable a partir dels fitxers creats pels altres agents.

### Write set
- `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`

### Responsabilitats
- Conservar:
  - `{% extends "base.html" %}`
  - `{% load static_extras %}`
  - `block title`
  - `block content`
  - include del CSS d'ajuda
  - CDN de `Sortable`
  - include final de `classificacions_builder_help.js`
- Substituir:
  - `<style>` per `{% include "classificacions/builder/_styles.html" %}`
  - shell HTML per `{% include "classificacions/builder/_page_chrome.html" %}`
  - `json_script` per `{% include "classificacions/builder/_json_contract.html" %}`
  - help drawer per `{% include "classificacions/builder/_help_drawer.html" %}`
  - cos del `<script>` per includes JS en aquest ordre:
    1. `_00_bootstrap.js.html`
    2. `_10_core_ui.js.html`
    3. `_20_team_templates_apps.js.html`
    4. `classificacions/_puntuacio_script.html`
    5. `_40_ties_and_teams.js.html`
    6. `_50_columns_detail_preview.js.html`
    7. `_60_particions.js.html`
    8. `_70_hydration_sync.js.html`
    9. `_80_actions_init.js.html`

### Restriccions
- Mantenir un unic `<script>` inline per aquests includes.
- No moure el CDN de `Sortable` sota l'script inline.
- No canviar el path d'aquest template.

## Agent D1. Verificacio I Ajust Fins

### Write set
- Qualsevol fitxer tocat pels agents anteriors, excepte si entra en conflicte amb una decisio encara no integrada.

### Objectiu
- Validar que la fragmentacio manté el contracte extern.

### Verificacions minimes
- Render de builder de competicio.
- Render de builder global.
- Presencia de tots els ids crítics.
- Presencia de les signatures JS comprovades pels tests.
- No aparicio de l'opcio `entitat`.
- El recompte de `function buildTieAppScopeOptionsHTML(` continua sent 1 al HTML final.

## Ordre De Merge Recomanat

### Batch 1 en paral.lel
- A1
- A2
- A3
- A4
- A5
- A6
- A7
- B1
- B2
- B3
- B4
- B5
- B6
- B7
- B8

### Batch 2
- C1

### Batch 3
- D1

## Contracte De Handoff Entre Agents

### Cada agent ha d'entregar
- Llista exacta de fitxers creats o editats.
- Llista exacta de funcions o seccions extretes.
- Confirmacio explicita que no ha canviat:
  - ids
  - textos
  - ordre de funcions
  - paths
  - nom de funcions

### Cada agent no ha de fer
- No ha de reformatar massivament.
- No ha de fer "small cleanup".
- No ha d'eliminar duplicats.
- No ha de fusionar responsabilitats alienes al seu paquet.

## Checklist D'Acceptacio Final
- `classificacions_builder_v2.html` ja no es un monolit HTML+JS, sino una facade d'includes.
- Els fitxers `classificacions/puntuacio.html` i `classificacions/_puntuacio_script.html` continuen vius i funcionals.
- El builder segueix funcionant en mode competicio i en mode global.
- Els tests de contracte del builder segueixen passant.
- No hi ha canvis de funcionalitat observables.

## Comandes De Verificacio Recomanades
- `docker compose run --rm web python manage.py test competicions_trampoli.tests.classificacions.test_templates_competition --verbosity 1`
- `docker compose run --rm web python manage.py test competicions_trampoli.tests.classificacions.test_templates_global --verbosity 1`
- `docker compose run --rm web python manage.py test competicions_trampoli.tests.classificacions --verbosity 1`

## Notes Finals Per Al Coordinador
- Si hi ha un sol dubte sobre en quin fitxer cau una funcio, prioritza preservar l'ordre d'execucio actual per sobre de la "neteja" conceptual.
- Si algun include nou obliga a tocar comportament o contracte, s'ha triat malament el tall i s'ha de rebaixar l'abast.
- La integracio final no ha d'intentar millorar arquitectura mes enlla de deixar el monolit partit.

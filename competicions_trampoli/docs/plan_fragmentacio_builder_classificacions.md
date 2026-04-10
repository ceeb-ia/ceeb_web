# Pla D'Implementacio De Fragmentacio Del Builder De Classificacions Per Subagents Paral.lels

## Objectiu
- Fragmentar `competicions_trampoli/templates/competicio/classificacions_builder_v2.html` en un conjunt de parcials mes petits i tractables.
- No canviar absolutament res de la funcionalitat actual.
- No canviar el contracte renderitzat que consumeixen la vista de competicio, la vista de plantilles globals i els tests.
- Deixar el treball prou paquetitzat perque diversos subagents, sense context previ, puguin treballar en paral.lel i convergir sense regressions.

## Regla Mes Important
- Aquesta tasca es un refactor estructural, no una millora funcional.
- No es pot canviar:
  - cap id de DOM
  - cap `data-help-key`
  - cap text renderitzat que els tests o la UI actual consumeixen
  - cap nom de funcio JS que avui apareix al HTML renderitzat
  - cap ordre d'avaluacio del JS inline
  - cap `template_name` de les vistes actuals
  - cap endpoint, cap `json_script`, cap URL, cap variable de context

## Context Minim Per A Qualsevol Agent

### Consumidors del builder
- Vista de competicio:
  - `competicions_trampoli/views/classificacions/builder.py`
  - usa `template_name = "competicio/classificacions_builder_v2.html"`
- Vista de plantilles globals:
  - `competicions_trampoli/views/classificacions/global_templates.py`
  - tambe usa `template_name = "competicio/classificacions_builder_v2.html"`

### Fitxer monolitic actual
- Entrada principal:
  - `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`
- Mida aproximada:
  - 8.6k linies
- Contingut:
  - CSS inline gran
  - shell HTML del builder
  - 5 seccions HTML grans dins del monolit
  - `json_script` backend -> frontend
  - un `<script>` inline gegant
  - drawer d'ajuda
  - script static d'ajuda

### Parcials ja existents que s'han de preservar en aquesta fase
- `competicions_trampoli/templates/classificacions/puntuacio.html`
- `competicions_trampoli/templates/classificacions/_puntuacio_script.html`

### Contractes de no regressio confirmats pels tests
- `competicions_trampoli/tests/classificacions/test_templates_competition.py`
- `competicions_trampoli/tests/classificacions/test_templates_global.py`
- Aquests tests verifiquen, entre altres:
  - presencia d'ids concrets com `can-manage-global-templates`, `builder-save-url`, `builder-delete-url-pattern`, `builder-preview-url-pattern`
  - presencia d'ids UI com `victoryConfigBox`, `sVictoryModeCamps`, `sVictoryModeExercicis`, `puntuacioSummaryText`, `candidateScopeHint`, `classifHelpDrawer`, `classif-builder-back-to-top`, `previewBox`, `detailConfigAlert`, `eqAssignmentContextHint`, `saveMsg`
  - presencia de strings concretes dins del JS renderitzat
  - presencia de funcions concretes dins del JS renderitzat
  - que `function buildTieAppScopeOptionsHTML(` aparegui exactament una sola vegada
  - presencia dels assets `classificacions_builder_help.css` i `classificacions_builder_help.js`
  - contractes textuals del copy contextual de filtres, detall, equips i preview

## Resultat Final Esperat
- El path d'entrada continua sent:
  - `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`
- Aquest fitxer queda reduit a facade:
  - `extends`
  - `block title`
  - includes de parcials
  - CDN Sortable
  - un unic `<script>` inline que inclou parcials JS en ordre estricte
  - drawer d'ajuda
  - static help script
- `puntuacio.html` i `_puntuacio_script.html` es mantenen on son en la primera iteracio.
- La resta del builder queda fragmentada sota un nou directori `templates/classificacions/builder/`.

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

## Regles D'Arquitectura Per Aquesta Refactoritzacio

### Regla 1. No moure JS a `static/`
- Els tests miren strings de funcions dins del HTML renderitzat.
- Per tant, en aquesta fase el JS ha de continuar sent inline.
- La fragmentacio s'ha de fer amb `{% include %}` dins d'un unic `<script>`.

### Regla 2. No moure `puntuacio` en aquest primer tall
- `puntuacio` ja esta parcialment separada.
- Moure-la de lloc i reordenar-la alhora afegeix risc sense retorn clar.
- El monolit principal simplement continuara fent:
  - `{% include "classificacions/puntuacio.html" %}`
  - `{% include "classificacions/_puntuacio_script.html" %}`

### Regla 3. Conservar l'ordre actual del JS
- No es poden reordenar blocs de funcions per "neteja".
- Hi ha helpers i redefinicions que depenen de l'ordre actual.
- El wrapper final ha de carregar els parcials en el mateix ordre logic que avui.

### Regla 4. No deduplicar helpers en aquesta fase
- Si hi ha una funcio definida mes d'una vegada a la sortida renderitzada, no es resol ara.
- Primer es copia l'estructura tal com es avui.
- Les neteges semantiques, si algun dia es fan, han d'anar en una fase posterior amb proves propies.

### Regla 5. Un sol integrador toca el wrapper final
- Per evitar conflictes de merge, nomes l'agent integrador ha d'editar:
  - `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`
- Els altres agents creen o omplen noms nous sota `templates/classificacions/builder/`.

## Tall Natural Del HTML

### `builder/_styles.html`
- Tot el bloc `<style>` inline actual.
- No s'ha de convertir a CSS static.
- No s'ha de reordenar ni "netejar" el CSS.

### `builder/_page_chrome.html`
- Shell general de la pagina:
  - capcalera
  - toolbar
  - selector de plantilles
  - `saveMsg`
  - `saveErrorsBox`
  - sidebar `cfgList`
  - `editorEmpty`
  - `editorBody`
  - navegacio interna
  - inclusio de seccions
  - boto `classif-builder-back-to-top`

### `builder/sections/_meta.html`
- Bloc `section-meta`
- Inclou:
  - `classifStatusBox`
  - `fNom`
  - `fSlug`
  - `fTipus`
  - `fActiva`
  - `equipMetaBox`
  - `eqAssignmentContext`
  - `eqAssignmentContextHint`
  - `eqTeamModeWrap`
  - `eqTeamMode`
  - `eqTeamModeHint`
  - `eqCompatBanner`

### `builder/sections/_particions.html`
- Bloc `section-particions`
- Inclou:
  - `particionsFieldsBox`
  - `particionsCustomBox`
  - `particionsDerivedBox`
  - `birthYearRangeConfigBox`
  - `equipCfgBox`
  - `eqIncludeSenseEquip`
  - `btnEqManualAdd`
  - `eqManualRows`

### `classificacions/puntuacio.html`
- Es preserva tal com esta.
- No s'edita en aquesta fase excepte si apareix algun canvi minim d'indentacio imposat pel wrapper final.

### `builder/sections/_desempat.html`
- Bloc `section-desempat`
- Inclou:
  - `tieParticipantsHead`
  - `tieBody`
  - `btnTieAdd`
  - `btnTieCloneFromPuntuacio`
  - `tDesempat`

### `builder/sections/_filtres_detail.html`
- Bloc `section-filtres`
- Inclou:
  - `fEntitats`
  - `fCategories`
  - `fSubcategories`
  - `fGrups`
  - `detailConfigBox`
  - `detailScopeHint`
  - `detailEnabled`
  - `detailDefaultOpen`
  - `detailSectionType`
  - `btnDetailSectionAdd`
  - `detailConfigAlert`
  - `detailSectionsBox`
  - `tFiltres`

### `builder/sections/_presentacio.html`
- Bloc `section-presentacio`
- Inclou:
  - `iTopN`
  - `cEmpats`
  - `btnPreview`
  - `btnColAddBuiltin`
  - `btnColAddRaw`
  - `columnsRawContextualCopy`
  - `columnsBox`
  - `previewBox`
  - `advancedJson`

### `builder/_json_contract.html`
- Tots els `json_script` actuals, sense canvis de nom.
- Ha de continuar renderitzant exactament els mateixos ids:
  - `cfgs-data-v2`
  - `aparells-data-v2`
  - `equips-data-v2`
  - `equip-contexts-data-v2`
  - `particio-fields-data-v2`
  - `particio-value-choices-data-v2`
  - `aparell-field-options-data`
  - `competicio-id`
  - `builder-mode`
  - `builder-save-url`
  - `builder-delete-url-pattern`
  - `builder-preview-url-pattern`
  - `builder-enable-template-library`
  - `builder-can-preview`
  - `builder-selected-id`
  - `builder-auto-add-new`
  - `can-manage-global-templates`
  - `team-context-capabilities-data-v2`
  - `cfg-statuses-data-v2`

### `builder/_help_drawer.html`
- `classifHelpDrawer`
- `classifHelpTitle`
- `classifHelpBody`

## Tall Natural Del JS

### Ordre final obligatori dins del `<script>`
1. `builder/scripts/_00_bootstrap.js.html`
2. `builder/scripts/_10_core_ui.js.html`
3. `builder/scripts/_20_team_templates_apps.js.html`
4. `classificacions/_puntuacio_script.html`
5. `builder/scripts/_40_ties_and_teams.js.html`
6. `builder/scripts/_50_columns_detail_preview.js.html`
7. `builder/scripts/_60_particions.js.html`
8. `builder/scripts/_70_hydration_sync.js.html`
9. `builder/scripts/_80_actions_init.js.html`

### `scripts/_00_bootstrap.js.html`
- Ha de contenir nomes:
  - `parseJsonScript`
  - constants `COMPETICIO_ID`, `CFGS`, `APARELLS`, `EQUIPS`, `EQUIP_CONTEXTS`, `PARTICIO_FIELDS`, `PARTICIO_VALUE_CHOICES`, `APARELL_FIELD_OPTIONS`
  - flags `CAN_MANAGE_GLOBAL_TEMPLATES`, `BUILDER_MODE`, `SAVE_URL`, `DELETE_URL_PATTERN`, `PREVIEW_URL_PATTERN`, `TEMPLATE_LIBRARY_ENABLED`, `CAN_PREVIEW`, `INITIAL_SELECTED_ID`, `AUTO_ADD_NEW`, `TEAM_CONTEXT_CAPABILITIES`, `CFG_STATUSES`
  - constants de domini com `BIRTH_YEAR_RANGE_PARTITION_CODE`, `TEAM_MODE_DERIVED`, `TEAM_MODE_NATIVE`
  - `TEMPLATE_LIST_URL`, `TEMPLATE_SAVE_URL`, `TEMPLATE_VALIDATE_URL`, `TEMPLATE_APPLY_URL`
  - `DEFAULT_SCHEMA`

### `scripts/_10_core_ui.js.html`
- Helpers i estat general:
  - `els`
  - `state`
  - `advancedDirty`
  - navegacio interna
  - `getCookie`
  - `esc`
  - `currentCfg`
  - `registerStaticErrorPaths`
  - feedback i render d'errors de guardat

### `scripts/_20_team_templates_apps.js.html`
- Context d'equips, copy contextual, templates globals i compatibilitat d'aparells.
- Funcions clau que hi han d'anar:
  - normalitzadors de tipus/context/filtres
  - `getTeamContextCapability`
  - `getCfgStatus`
  - `getEquipsUiState`
  - `renderFiltersContextualCopy`
  - `renderColumnsRawContextualCopy`
  - `renderEquipsModeControls`
  - `ensureLegacyTipusOption`
  - `setTipusValue`
  - `selectedTemplateId`
  - `renderTemplateSelect`
  - `loadTemplateList`
  - `templateNameById`
  - `summarizeTemplateValidation`
  - `renderList`
  - tot el bloc de compatibilitat d'aparells:
    - `getSchemaReferencedAppIds`
    - `getSchemaSelectedAppIds`
    - `getCurrentBuilderAppIds`
    - `getCompatibleAppIds`
    - `sanitizeCompatibleAppIds`
    - `getSingleCompatibleAppId`
    - `getDefaultCompatibleAppId`
    - `filterPerAppMapByCompatibleIds`
    - `filterRawColumnsByAllowedApps`
    - `pruneSelectableAppScope`
    - `pruneTieCriteriaAppReferences`
    - `pruneDetailSectionsByAllowedApps`
    - `renderAppStaleWarningBanner`
    - `pruneSchemaAppReferences`
    - `rememberHydrationIssue`
    - `runSafeHydrationRender`
    - `getAppChoices`
    - `buildAparellChecks`
    - `rebuildAparellChecksPreservingSelection`
    - `selectedAparellIdsFromUI`

### `classificacions/_puntuacio_script.html`
- S'ha de preservar com a bloc existent.
- No deduplicar contra helpers definits abans o despres.
- No canviar l'ordre respecte els altres parcials JS.

### `scripts/_40_ties_and_teams.js.html`
- Tot el domini de desempat i equips posterior a `puntuacio`.
- Inclou:
  - participants/tie pipeline helpers
  - `renderTieUI`
  - `readTieUI`
  - `renderVictoryTieUI`
  - `readVictoryTieUI`
  - `addDefaultTieCriterion`
  - `renderEquipContextOptions`
  - `renderEquipManualRows`
  - `readEquipManualRows`
  - `readEquipsSchemaUI`
  - `syncEquipUIFromSchema`

### `scripts/_50_columns_detail_preview.js.html`
- Domini de columnes, detall i preview.
- Inclou:
  - `defaultDisplayColumns`
  - `normalizeColumnsFromSchema`
  - tot el domini `detail*`
  - `renderColumnsUI`
  - `readColumnsUI`
  - `renderDetailColumnsUI`
  - `readDetailColumnsUI`
  - `renderDetailSectionsUI`
  - `readDetailSectionsUI`
  - `previewColClass`
  - `previewFallbackCellValue`
  - `previewFormatCellText`
  - `previewRenderJudgeRowsCell`
  - `previewRenderTeamRawDetailCell`
  - `previewRenderCellHTML`
  - `previewRenderDetailHTML`
  - `formatPartitionTitle`

### `scripts/_60_particions.js.html`
- Domini de particions i drag-and-drop.
- Inclou:
  - normalitzadors de codis/values/entries
  - `renderParticioStackUI`
  - `buildParticioFieldChecks`
  - `renderParticionsCustomUI`
  - `readParticionsCustomUI`
  - `initParticionsCustomSortables`
  - `normalizeBirthYearRangePartitionConfig`
  - `normalizeParticionsConfig`
  - `readBirthYearRangePartitionConfigUI`
  - `readParticionsConfigUI`
  - `renderDerivedPartitionConfigUI`

### `scripts/_70_hydration_sync.js.html`
- Sincronitzacio schema <-> UI.
- Inclou:
  - `sanitizeMainCampsPerAparell`
  - `sanitizeTieItemForUI`
  - `sanitizeRawColumnsForUI`
  - `normalizeForHydration`
  - `syncAdvancedFromUI`
  - `syncUIFromSchema`
  - `selectCfg`

### `scripts/_80_actions_init.js.html`
- Tots els listeners finals, CRUD, template actions, preview i init.
- Inclou:
  - bloc d'events generals
  - listeners de particions
  - listeners de filtres avançats i detail
  - listeners de tie/victory tie/columnes/detail
  - listeners de meta/equips
  - `postJson`
  - `fallbackModeLabel`
  - `buildFallbackWarning`
  - `checkSelectedTemplate`
  - `applySelectedTemplate`
  - `saveCurrentCfgAsTemplate`
  - listeners `btnTemplateRefresh`, `btnTemplateCheck`, `btnTemplateApply`, `btnTemplateSave`
  - listeners `btnSave`, `btnDelete`, `btnPreview`
  - bloc final `// init`

## Estrategia De Treball En Paral.lel

### Regla De Branching
- Tots els subagents han de crear branca des del mateix commit base.
- Cada subagent ha d'editar nomes els fitxers que el seu paquet autoritza.
- Nomes l'integrador edita el wrapper final.
- Els canvis s'han de cherry-pickar o fusionar en aquest ordre:
  1. parcials nous
  2. wrapper final
  3. verificacio

### Paquets De Feina Recomanats

#### Paquet 0. Integrador
- Responsable de:
  - crear el directori nou `templates/classificacions/builder/`
  - crear el wrapper final
  - col.locar els `{% include %}` en ordre correcte
  - verificar render final i tests
- Fitxers permesos:
  - `competicions_trampoli/templates/competicio/classificacions_builder_v2.html`
  - qualsevol fitxer nou sota `competicions_trampoli/templates/classificacions/builder/`
- Fitxers prohibits:
  - `views/classificacions/builder.py`
  - `views/classificacions/global_templates.py`
  - `templates/classificacions/puntuacio.html`
  - `templates/classificacions/_puntuacio_script.html`
- No ha de canviar cap logica.

#### Paquet 1. HTML shell i parcials visuals
- Objectiu:
  - extreure CSS, shell HTML, sections HTML, json contract i help drawer.
- Fitxers permesos:
  - `competicions_trampoli/templates/classificacions/builder/_styles.html`
  - `competicions_trampoli/templates/classificacions/builder/_page_chrome.html`
  - `competicions_trampoli/templates/classificacions/builder/_json_contract.html`
  - `competicions_trampoli/templates/classificacions/builder/_help_drawer.html`
  - `competicions_trampoli/templates/classificacions/builder/sections/_meta.html`
  - `competicions_trampoli/templates/classificacions/builder/sections/_particions.html`
  - `competicions_trampoli/templates/classificacions/builder/sections/_desempat.html`
  - `competicions_trampoli/templates/classificacions/builder/sections/_filtres_detail.html`
  - `competicions_trampoli/templates/classificacions/builder/sections/_presentacio.html`
- Fitxers prohibits:
  - el wrapper final
  - `puntuacio.html`
  - qualsevol fitxer Python
- Definition of done:
  - tots els blocs HTML existeixen com a parcials nous
  - `_page_chrome.html` documenta amb comentaris quins includes espera
  - no hi ha canvis semantico-funcionals

#### Paquet 2. JS bootstrap i core pre-puntuacio
- Objectiu:
  - extreure el bloc JS previ a `_puntuacio_script.html`.
- Fitxers permesos:
  - `competicions_trampoli/templates/classificacions/builder/scripts/_00_bootstrap.js.html`
  - `competicions_trampoli/templates/classificacions/builder/scripts/_10_core_ui.js.html`
  - `competicions_trampoli/templates/classificacions/builder/scripts/_20_team_templates_apps.js.html`
- Fitxers prohibits:
  - `_puntuacio_script.html`
  - wrapper final
- Definition of done:
  - el bloc pre-puntuacio queda repartit exactament en aquests 3 fitxers
  - no es perd cap funcio usada per `puntuacio`
  - no s'introdueixen dependencias circulars noves

#### Paquet 3. JS ties i equips
- Objectiu:
  - extreure el domini post-puntuacio de desempat i equips.
- Fitxer permess:
  - `competicions_trampoli/templates/classificacions/builder/scripts/_40_ties_and_teams.js.html`
- Fitxers prohibits:
  - wrapper final
  - `_puntuacio_script.html`
  - fitxers de particions o detail
- Definition of done:
  - `renderTieUI`, `renderVictoryTieUI`, `readTieUI`, `readVictoryTieUI`, `readEquipsSchemaUI`, `syncEquipUIFromSchema` viuen en aquest parcial

#### Paquet 4. JS columns, detail i preview
- Objectiu:
  - extreure el domini de columnes, detall desplegable i preview.
- Fitxer permess:
  - `competicions_trampoli/templates/classificacions/builder/scripts/_50_columns_detail_preview.js.html`
- Fitxers prohibits:
  - wrapper final
  - fitxers de particions
  - `_puntuacio_script.html`
- Definition of done:
  - tot el domini `detail*`, `columns*` i `preview*` viu aqui

#### Paquet 5. JS particions
- Objectiu:
  - extreure el domini de particions, custom groups i birth year ranges.
- Fitxer permess:
  - `competicions_trampoli/templates/classificacions/builder/scripts/_60_particions.js.html`
- Fitxers prohibits:
  - wrapper final
  - fitxers de columns/detail
- Definition of done:
  - `renderParticioStackUI`, `renderParticionsCustomUI`, `initParticionsCustomSortables`, `renderDerivedPartitionConfigUI` viuen aqui

#### Paquet 6. JS hydration, events, CRUD i init
- Objectiu:
  - extreure la sincronitzacio schema/UI i la capa final d'accions.
- Fitxers permesos:
  - `competicions_trampoli/templates/classificacions/builder/scripts/_70_hydration_sync.js.html`
  - `competicions_trampoli/templates/classificacions/builder/scripts/_80_actions_init.js.html`
- Fitxers prohibits:
  - wrapper final
  - `_puntuacio_script.html`
- Definition of done:
  - `syncAdvancedFromUI`, `syncUIFromSchema`, `selectCfg`, `postJson`, `save/delete/preview/init` queden escindits aqui

#### Paquet 7. Verificador final
- Objectiu:
  - comprovar que la sortida renderitzada continua complint el contracte.
- Fitxers permesos:
  - tests si cal fer ajustos de comentaris o afegir docs de validacio
  - preferiblement no tocar codi
- Fitxers prohibits:
  - logica del builder
- Definition of done:
  - els tests contracte passen
  - la resposta renderitzada continua contenint els ids i funcions exigides

## Ordre Recomanat D'Integracio

### Pas 1
- Fusionar Paquets 1, 2, 3, 4, 5 i 6 sense tocar el wrapper encara.
- Objectiu:
  - tenir tots els nous parcials disponibles al repo.

### Pas 2
- L'integrador reescriu `competicions_trampoli/templates/competicio/classificacions_builder_v2.html` com a facade.
- El fitxer final ha de quedar amb aquesta forma logica:

```django
{% extends "base.html" %}
{% load static_extras %}
{% block title %}...{% endblock %}
{% block content %}

<link rel="stylesheet" href="{% staticv 'css/classificacions_builder_help.css' %}">
{% include "classificacions/builder/_styles.html" %}
{% include "classificacions/builder/_page_chrome.html" %}
{% include "classificacions/builder/_json_contract.html" %}

<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
<script>
{% include "classificacions/builder/scripts/_00_bootstrap.js.html" %}
{% include "classificacions/builder/scripts/_10_core_ui.js.html" %}
{% include "classificacions/builder/scripts/_20_team_templates_apps.js.html" %}
{% include "classificacions/_puntuacio_script.html" %}
{% include "classificacions/builder/scripts/_40_ties_and_teams.js.html" %}
{% include "classificacions/builder/scripts/_50_columns_detail_preview.js.html" %}
{% include "classificacions/builder/scripts/_60_particions.js.html" %}
{% include "classificacions/builder/scripts/_70_hydration_sync.js.html" %}
{% include "classificacions/builder/scripts/_80_actions_init.js.html" %}
</script>

{% include "classificacions/builder/_help_drawer.html" %}
<script src="{% staticv 'js/classificacions_builder_help.js' %}" defer></script>
{% endblock %}
```

### Pas 3
- Executar la validacio.
- Nomes si passa, considerar la tasca tancada.

## Checklist De No Regressio

### HTML
- Existeix `id="classifHelpDrawer"`.
- Existeix `id="classif-builder-back-to-top"`.
- Existeix `id="puntuacioSummaryText"`.
- Existeix `id="candidateScopeHint"`.
- Existeix `id="appStaleBanner"`.
- Existeix `id="detailConfigAlert"`.
- Existeix `id="eqAssignmentContextHint"`.
- Existeix `id="previewBox"`.
- Existeix `id="saveMsg"`.

### JS renderitzat
- Existeix `function pruneSchemaAppReferences(schema, allowedIds)`.
- Existeix `function renderAppStaleWarningBanner(schema, selectedIds)`.
- Existeix `function filterRawColumnsByAllowedApps(rawCols, allowedIds)`.
- Existeix `function pruneDetailSectionsByAllowedApps(rawSections, allowedIds)`.
- Existeix `function runSafeHydrationRender(label, renderFn)`.
- Existeix `function _buildPretractamentSegment(punt, perAppEntries)`.
- Existeix `function _buildScoreSelectionSegment({`.
- Existeix `function _buildVictoriesComparisonSegment(victoriesCfg)`.
- Existeix `function previewRenderTeamRawDetailCell(v, col)`.
- `function buildTieAppScopeOptionsHTML(` apareix exactament una vegada.

### Copy renderitzat
- Es mantenen els textos contextuals de filtres.
- Es mantenen els textos contextuals de detall d'equips.
- Es mantenen els textos de resum de puntuacio que avui vigilen els tests.

### Assets
- Es manten `classificacions_builder_help.css`.
- Es manten `classificacions_builder_help.js`.
- Es manten el CDN de SortableJS.

## Proves Recomanades

### Proves minim obligatories
- `docker compose run --rm web python manage.py test competicions_trampoli.tests.classificacions.test_templates_competition --verbosity 1`
- `docker compose run --rm web python manage.py test competicions_trampoli.tests.classificacions.test_templates_global --verbosity 1`

### Proves recomanades si el temps ho permet
- `docker compose run --rm web python manage.py test competicions_trampoli.tests.classificacions --verbosity 1`

## Coses Que No S'Han De Fer En Aquesta Tasca
- No canviar `builder.py` ni `global_templates.py`.
- No migrar a moduls ES.
- No moure `puntuacio.html` ni `_puntuacio_script.html`.
- No aprofitar per "netejar" texts, traduccions o accents.
- No canviar selectors, ids, `name`, `data-k`, `data-app-id`, `data-part-*` o atributs equivalents.
- No deduplicar helpers.
- No tocar CSS static global.
- No canviar el model de dades ni la logica de validacio de classificacions.

## Senyals Que Un Subagent Ha Sortit Del Scope
- Ha tocat un fitxer Python.
- Ha canviat textos visibles.
- Ha mogut `_puntuacio_script.html`.
- Ha creat un JS static nou.
- Ha tocat l'ordre del script o ha dividit el JS en multiples contexts diferents del wrapper acordat.
- Ha intentat simplificar o fusionar funcions duplicades.

## Handoff Curt Per A Cada Subagent
- Llegeix aquest document sencer.
- Llegeix nomes el teu paquet i el fitxer monolitic font.
- No improvisis una estructura alternativa.
- No toquis fitxers fora del teu paquet.
- Quan acabis, deixa el codi en parcials nous, sense cablejar-lo si no ets l'integrador.
- L'integrador es l'unic responsable del wrapper final i de la validacio final.

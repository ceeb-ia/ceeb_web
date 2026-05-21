# Pla De Desmonolititzacio De Rotacions Amb Subagents

## Objectiu
- Separar el template monolitic de rotacions en dominis petits, llegibles i mantenibles.
- Aplicar una UI tematica propia de Rotacions sense alterar la logica funcional existent.
- Fer que el centre visual de la pantalla sigui la taula de franges i estacions.
- Conservar intactes els contractes que afecten notes, portal de jutges, exports, franges i assignacions.

## Fitxer De Partida
- `competicions_trampoli/templates/competicio/rotacions_planner.html`

Aquest fitxer conte aproximadament:
- CSS inline del planner.
- HTML de capcalera, resum, drawers, taula, export, ajuda i modals.
- JSON embegut per inicialitzar l'estat JavaScript.
- JavaScript inline per drag and drop, CRUD de franges, export, drawers i filtres.

## Principis De Refactor
- Primer separar, despres redissenyar.
- No canviar IDs, classes `.js-*`, `data-*` ni noms dels scripts JSON sense actualitzar i provar el JavaScript.
- No canviar payloads AJAX ni endpoints Django.
- No barrejar `ordre` competitiu amb `ordre_visual`.
- No tocar models ni views si l'objectiu de la fase es nomes template/UI.
- Mantenir la taula `franges x estacions` com a superficie principal.
- Usar el patro visual de Fases: shell tematic, drawer lateral dret, botons open/close amb imatges, nav interna i selectors estilitzats.

## Contractes Funcionals Que No Es Poden Trencar

### JSON Inicial
Han de continuar existint aquests nodes:
- `grid-data`
- `group-labels-data`
- `group-sidebar-data`
- `station-modes-data`
- `franja-order-modes-data`
- `franja-default-colors-data`
- `export-meta-data`
- `export-participant-fields-data`

### Taula I Drag And Drop
Selectors obligatoris:
- `table.rot`
- `.js-col-h[data-estacio]`
- `.js-cell[data-franja][data-estacio]`
- `.franja-row-competitive[data-franja-row][data-franja-visual-row]`
- `.franja-row-global[data-franja-visual-row]`
- `.js-franja-visual-target`
- `.chip[draggable][data-key]`
- `.js-pill-remove[data-franja][data-estacio][data-key]`

### Accions De Franja I Estacio
Selectors obligatoris:
- `.js-edit-fr[data-url][data-titol][data-hi][data-hf][data-tipus][data-color]`
- `.js-insert-after[data-fr]`
- `.js-clear-franja[data-fr]`
- `.js-extrapolar[data-fr]`
- `.js-del-fr[data-fr]`
- `.js-del-es[data-es]`
- `.js-franja-order-mode[data-fr]`

### Drawer, Filtres I Programables
IDs i data attributes obligatoris:
- `planner-left-toggle`
- `planner-export-toggle`
- `planner-left-backdrop`
- `planner-export-backdrop`
- `planner-left-drawer`
- `planner-export-drawer`
- `programSearch`
- `activeStationBox`
- `activeStationMeta`
- `clearActiveStation`
- `[data-drawer-panel-target]`
- `[data-drawer-panel]`
- `[data-program-placement]`
- `[data-program-kind]`
- `[data-program-non-empty]`

### Inputs De Franges
IDs obligatoris:
- `ftype`
- `hi`
- `hf`
- `ft`
- `fcolor`
- `btnResetFranjaColor`
- `btnAddFranja`
- `auto_hi`
- `auto_hf`
- `auto_int`
- `auto_tb`
- `auto_clear`
- `btnAutoFranges`
- `autoStatus`

### Export
IDs i classes obligatoris:
- `exportExcelDropdown`
- `.js-export-dd-toggle`
- `exportTitle`
- `exportVenue`
- `exportDate`
- `exportFieldsList`
- `exportLogoFile`
- `btnExportLogoUpload`
- `btnExportLogoClear`
- `btnExportMetaSave`
- `exportMetaStatus`
- `exportLogoPreviewWrap`
- `exportLogoPreview`
- `.js-export-field-check`

### Modals
IDs obligatoris:
- `editFrModal`
- `editFrTitol`
- `editFrTipus`
- `editFrHi`
- `editFrHf`
- `editFrColor`
- `btnEditFrColorReset`
- `btnEditFrSave`
- `franjaReorderModal`
- `franjaReorderOrigin`
- `franjaReorderList`
- `btnFranjaReorderAccept`

## Endpoints I Payloads A Preservar

### Guardar Graella
- URL: `rotacions_save`
- Payload actual: `{ cells: [{ franja, estacio, items }] }`
- `items` conserva ordre i usa claus:
  - `g:<id>` per grups
  - `s:<id>` per series d'equip
  - `pu:<id>` per unitats programables

### Franges
- `rotacions_franja_create`
- `rotacions_franja_update_inline`
- `rotacions_franja_insert_after`
- `rotacions_franja_delete`
- `rotacions_franges_auto_create`
- `rotacions_franges_reorder`
- `rotacions_franges_reorder_visual`
- `rotacions_franja_order_mode_set`
- `rotacions_extrapolar`

Payloads importants:
- `hora_inici`
- `hora_fi`
- `titol`
- `tipus`
- `color_fons`
- `preview_only`
- `confirm_reorder`
- `dragged_id`
- `target_id`
- `position`
- `mode`

### Estacions
- `rotacions_estacio_descans_create`
- `rotacions_estacio_delete`
- `rotacions_estacions_reorder`
- Payload reorder: `{ order: [ids...] }`

### Export
- `rotacions_export_meta_save`
- `rotacions_export_logo_upload`
- `rotacions_export_logo_clear`
- `rotacions_franges_export_excel?mode=participants`
- `rotacions_franges_export_excel?mode=groups`

Payloads importants:
- `title`
- `venue`
- `date`
- `participant_fields`
- `logo` en `FormData`

### Fora De Programa
- `rotacions_out_of_program_visibility_save`
- Payload: `{ value: boolean }`
- Aquesta opcio afecta notes i portal de jutges, no nomes el planner.

## Paleta Visual De Rotacions
Aplicar els colors definits a `docs/frontend-style-guide.md`:

```css
--rotation-base: #B45309;
--rotation-base-hover: #92400E;
--rotation-soft: #FFF7ED;
--rotation-border: #FED7AA;
--rotation-text: #7C2D12;
--rotation-bg: #F8FAFC;
--rotation-surface: #FFFFFF;
--rotation-neutral-border: #E2E8F0;
--rotation-muted: #64748B;
--rotation-text-main: #0F172A;
```

Regles visuals:
- El color amber de Rotacions ha de ser accent, no una capa tenyida a tota la pantalla.
- La taula ha de tenir fons neutre, headers clars, separadors fins i hover discret.
- Les franges poden usar accent amber i els colors propis de cada franja.
- Els controls de formulari i selectors han de seguir el patro de Fases, amb border tematic, focus clar i fletxa CSS custom.
- Evitar cards dins de cards.
- Evitar text massa gran dins del drawer.
- El drawer ha de servir per eines; la taula ha de seguir sent el focus.

## Estructura Final Recomanada

`rotacions_planner.html` ha de quedar com a orquestrador:

```django
{% extends "base.html" %}
{% load static static_extras %}
{% block title %}Rotacions{% endblock %}

{% block content %}
  {% include "competicio/rotacions/_styles.html" %}

  <div class="rotation-dashboard-shell rotation-page-shell" id="rotation-page-shell">
    {% include "competicio/rotacions/_header.html" %}
    {% include "competicio/rotacions/_summary.html" %}
    {% include "competicio/rotacions/_drawer_toggles.html" %}

    <div class="rotation-workspace">
      <main class="rotation-dashboard-main">
        {% include "competicio/rotacions/_grid.html" %}
      </main>
      {% include "competicio/rotacions/_left_drawer.html" %}
      {% include "competicio/rotacions/_export_drawer.html" %}
    </div>
  </div>

  {% include "competicio/rotacions/_help_drawer.html" %}
  {% include "competicio/rotacions/_modals.html" %}
  {% include "competicio/rotacions/_json_data.html" %}
  {% include "competicio/rotacions/scripts/_planner.html" %}
{% endblock %}
```

## Partials A Crear

### Arrel
- `competicio/rotacions/_styles.html`
- `competicio/rotacions/_header.html`
- `competicio/rotacions/_summary.html`
- `competicio/rotacions/_drawer_toggles.html`
- `competicio/rotacions/_left_drawer.html`
- `competicio/rotacions/_grid.html`
- `competicio/rotacions/_export_drawer.html`
- `competicio/rotacions/_help_drawer.html`
- `competicio/rotacions/_modals.html`
- `competicio/rotacions/_json_data.html`

### Drawer
- `competicio/rotacions/drawer/_nav.html`
- `competicio/rotacions/drawer/_programables.html`
- `competicio/rotacions/drawer/_franges.html`
- `competicio/rotacions/drawer/_globals.html`

### Graella
- `competicio/rotacions/grid/_header.html`
- `competicio/rotacions/grid/_row_competitive.html`
- `competicio/rotacions/grid/_row_global.html`
- `competicio/rotacions/grid/_empty.html`

### Estils
- `competicio/rotacions/styles/_theme.html`
- `competicio/rotacions/styles/_layout.html`
- `competicio/rotacions/styles/_drawer.html`
- `competicio/rotacions/styles/_table.html`
- `competicio/rotacions/styles/_components.html`
- `competicio/rotacions/styles/_responsive.html`

### Scripts
- `competicio/rotacions/scripts/_planner.html`

En una fase posterior, el JS inline es pot moure a static, pero no s'ha de fer dins el primer tall si augmenta el risc.

## Fase 0. Preparacio I Baseline

Objectiu:
- Tenir una fotografia clara abans de tocar el monolit.

Tasques:
- Executar tests de rotacions.
- Guardar llista dels selectors funcionals que apareixen al template.
- Revisar que el render actual de `rotacions_planner` no te errors.

Comandes recomanades:
```powershell
py -3 manage.py test competicions_trampoli.tests.rotacions --verbosity 1
```

Criteri d'acceptacio:
- Tests actuals passen o es documenten fallades preexistents.
- Cap canvi de codi funcional.

## Fase 1. Split Mecanic Del Template

Objectiu:
- Separar el monolit en partials sense canviar comportament ni disseny.

Tasques:
- Crear carpeta `templates/competicio/rotacions/`.
- Moure blocs HTML a partials equivalents.
- Moure els scripts JSON a `_json_data.html`.
- Moure modals a `_modals.html`.
- Moure el JS inline complet a `scripts/_planner.html`.
- Deixar `rotacions_planner.html` com a orquestrador.

No fer:
- No canviar classes visuals.
- No reordenar el JS.
- No canviar textos excepte correccions evidents d'encoding si no afecten tests.
- No canviar endpoints ni payloads.

Criteri d'acceptacio:
- El diff es majoritariament moviment de blocs.
- El render HTML conserva els selectors del contracte.
- Tests de rotacions passen.

## Fase 2. Tema Visual De Rotacions

Objectiu:
- Introduir variables i estil base de Rotacions amb la paleta amber.

Tasques:
- Crear `_styles.html` que inclogui partials de CSS com fa Fases.
- Crear `.rotation-dashboard-shell` i variables `--rotation-*`.
- Portar el fons global a neutres comuns.
- Estilitzar capcalera amb logo `static/dock/rotacions.png`.
- Afegir stats compactes de pantalla si el context ja dona dades suficients.
- Adaptar botons primaris i outline dins del shell.

No fer:
- No redissenyar encara la taula profundament.
- No canviar layout dels drawers.

Criteri d'acceptacio:
- Rotacions te identitat visual propia.
- El color amber no domina tota la pantalla.
- No hi ha regressio funcional.

## Fase 3. Taula Com A Centre De Pantalla

Objectiu:
- Fer que la taula sigui la superficie principal de treball.

Tasques:
- Donar a `rotation-dashboard-main` l'espai principal.
- Estilitzar `table.rot` amb headers sticky, separadors fins i fons neutre.
- Fer mes llegibles les capcaleres d'estacio `.js-col-h`.
- Fer mes compactes i professionals les cel.les `.js-cell`.
- Redissenyar pills mantenint `.pill` i `.js-pill-remove`.
- Fer visibles accions de franja de manera compacta sense desplacaments bruscos.
- Diferenciar files competitives i globals sense trencar els colors de franja (`--franja-bg`, `--franja-fg`, `--franja-border`).

No fer:
- No canviar `table.rot`.
- No canviar `data-franja` ni `data-estacio`.
- No substituir la taula per divs.

Criteri d'acceptacio:
- La taula es el primer focus visual.
- Drag and drop de cel.les, columnes i franges continua operatiu.
- Export continua respectant l'ordre visual.

## Fase 4. Drawer Unificat Amb Patro De Fases

Objectiu:
- Convertir el menu lateral a un drawer coherent amb Fases.

Tasques:
- Portar el patro de `phase-actions-toggle` a `rotation-actions-toggle`.
- Usar imatges per obrir/tancar:
  - Preferencia: crear `static/rotacions/accions/open.png` i `close.png`.
  - Alternativa temporal: reutilitzar `static/fases/accions/open.png` i `close.png` si son neutrals.
- Drawer dret amb capcalera, marca, kicker i boto de tancar.
- Nav interna amb `Programables`, `Franges`, `Operacions globals`.
- Estilitzar selectors i inputs del drawer amb variables `--rotation-*`.
- Mantenir `planner-left-toggle`, `planner-left-drawer` i `data-drawer-panel-*` o adaptar el JS en el mateix canvi.

No fer:
- No eliminar el drawer d'export si encara te funcionalitat propia.
- No canviar els IDs que llegeix el JS sense actualitzar el JS.

Criteri d'acceptacio:
- El drawer obre/tanca amb icones.
- Escape i backdrop tanquen correctament.
- Els panells interns canvien amb els mateixos `data-drawer-panel-target`.

## Fase 5. Export I Dropdowns

Objectiu:
- Donar format tematic a export, dropdown Excel i selector de camps sense tocar el contracte.

Tasques:
- Estilitzar `exportExcelDropdown` i `.js-export-dd-toggle`.
- Mantenir el dropdown manual actual si evita conflictes Bootstrap.
- Estilitzar `exportFieldsList` com llista densa i arrossegable.
- Polir upload/preview de logo.
- Mantenir links GET amb `mode=participants` i `mode=groups`.

No fer:
- No canviar `participant_fields`.
- No canviar noms dels camps de FormData.

Criteri d'acceptacio:
- Export participants i export grups segueixen funcionant.
- L'ordre dels camps de participants es desa i es recupera.

## Fase 6. Neteja Del JavaScript Inline

Objectiu:
- Fer el JS mes llegible sense canviar comportament.

Tasques:
- Separar el JS inline en blocs dins `scripts/_planner.html` amb comentaris de domini.
- Eliminar definicions duplicades si es confirma que son sobreescriptures mortes:
  - `renderAll()`
  - `renderGroupBuckets()`
- Agrupar funcions per:
  - config i CSRF
  - estat inicial
  - render de graella
  - programables i filtres
  - franges i reordenacio
  - export
  - drawers
  - init

No fer:
- No moure a fitxer static en aquesta fase si aixo obliga a resoldre URLs Django d'una altra manera.
- No canviar noms de funcions que siguin usats en handlers existents fins haver-ho verificat.

Criteri d'acceptacio:
- Un sol punt d'inicialitzacio clar.
- No hi ha regressio als tests de rotacions.

## Fase 7. Verificacio Final

Objectiu:
- Confirmar que el redisseny no ha trencat logica critica.

Tests recomanats:
```powershell
py -3 manage.py test competicions_trampoli.tests.rotacions --verbosity 1
py -3 manage.py test competicions_trampoli.tests.scoring.judge --verbosity 1
py -3 manage.py test competicions_trampoli.tests.fases.test_basic_planner_contract --verbosity 1
```

Fluxos manuals recomanats:
- Obrir planner de rotacions.
- Crear franja manual.
- Generar franges automatiques.
- Arrossegar grup a una cel.la.
- Arrossegar serie d'equip a estacio d'equip.
- Arrossegar unitat programable `pu:*`.
- Buidar cel.la.
- Reordenar estacions.
- Reordenar franges competitives.
- Moure franja global visual.
- Editar color de franja.
- Activar/desactivar fora de programa a notes i jutges.
- Exportar participants.
- Exportar grups.
- Pujar i treure logo d'export.

Criteri d'acceptacio:
- La UI es mes clara i tematica.
- La taula es el centre real de la pantalla.
- Notes, jutges i exports mantenen ordre i contingut.
- No hi ha canvis de model ni migracions.

## Assignacio Recomanada Per Subagents

### Agent A. Split Mecanic
Responsabilitat:
- Crear partials i moure blocs sense canviar markup funcional.

Write set:
- `competicions_trampoli/templates/competicio/rotacions_planner.html`
- `competicions_trampoli/templates/competicio/rotacions/**`

Sortida esperada:
- Llista de partials creats.
- Confirmacio que selectors contracte continuen presents.

### Agent B. Tema I Layout
Responsabilitat:
- Crear CSS tematic de Rotacions i adaptar shell/capcalera.

Write set:
- `competicions_trampoli/templates/competicio/rotacions/_styles.html`
- `competicions_trampoli/templates/competicio/rotacions/styles/**`
- `competicions_trampoli/templates/competicio/rotacions/_header.html`

Sortida esperada:
- Variables `--rotation-*`.
- Capcalera amb logo i estil coherent amb Fases.

### Agent C. Taula I Components
Responsabilitat:
- Fer que la graella sigui la superficie principal.

Write set:
- `competicions_trampoli/templates/competicio/rotacions/_grid.html`
- `competicions_trampoli/templates/competicio/rotacions/grid/**`
- `competicions_trampoli/templates/competicio/rotacions/styles/_table.html`
- `competicions_trampoli/templates/competicio/rotacions/styles/_components.html`

Sortida esperada:
- Taula tematica i llegible.
- Contracte DnD intacte.

### Agent D. Drawer I Export
Responsabilitat:
- Adaptar drawers i dropdown export al patro visual de Fases.

Write set:
- `competicions_trampoli/templates/competicio/rotacions/_drawer_toggles.html`
- `competicions_trampoli/templates/competicio/rotacions/_left_drawer.html`
- `competicions_trampoli/templates/competicio/rotacions/drawer/**`
- `competicions_trampoli/templates/competicio/rotacions/_export_drawer.html`
- `competicions_trampoli/templates/competicio/rotacions/styles/_drawer.html`

Sortida esperada:
- Toggle amb icones open/close.
- Drawer amb nav interna i controls estilitzats.
- Export usable i tematic.

### Agent E. Verificacio
Responsabilitat:
- Revisar contractes i executar tests.

Write set:
- Cap, excepte tests nous si detecta buit clar.

Sortida esperada:
- Resultat de tests.
- Llista de regressions o riscos residuals.

## Notes De Risc
- El monolit te funcions JS duplicades que se sobreescriuen. No eliminar-les fins haver validat quin bloc es l'actiu.
- El dropdown Excel te logica manual per conflictes Bootstrap; no substituir-lo sense prova manual.
- `ordre_visual` governa la presentacio i export visual; `ordre` governa sequencia competitiva. No confondre'ls.
- La visibilitat fora de programa afecta notes i portal de jutges.
- Les claus `g:`, `s:` i `pu:` son part del contracte actual.
- El primer refactor ha de ser reversible i mecanic.

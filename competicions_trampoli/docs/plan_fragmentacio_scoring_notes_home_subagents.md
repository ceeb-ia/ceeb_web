# Pla de fragmentacio de `scoring_notes_home.html` per subagents

## Estatus

- Estat: planificacio, sense canvis de codi aplicats.
- Fitxer objectiu principal: `competicions_trampoli/templates/scoring/scoring_notes_home.html`.
- Objectiu de la futura iteracio: dividir el monolit en parcials de template i blocs de JavaScript inclosos, mantenint exactament el comportament actual del panell de notes.
- Context minim necessari: aquest document ha de ser suficient per repartir la feina entre subagents sense recuperar la conversa original.

## Resum executiu

`scoring_notes_home.html` ha crescut fins a ser un fitxer molt gran, amb HTML, CSS, dades JSON, estat global, renderitzadors, sincronitzacio, panell multimedia, avisos i navegacio lazy en el mateix lloc. La migracio recomanada no ha de ser una reescriptura funcional: primer s'ha de fer una extraccio mecanica i verificable en parcials petits, preservant IDs, atributs `data-*`, noms globals de JavaScript i ordre d'execucio.

La proposta separa el fitxer en dominis:

- Estructura HTML i CSS.
- Contracte de dades JSON del template cap al client.
- Bootstrap, estat i helpers.
- API i persistencia de notes.
- Multimedia i reproduccio.
- Presencia de jutges i visibilitat de columnes.
- Avisos locals i avisos globals validables.
- Renderitzadors de taules individuals i equips.
- Navegacio lazy, filtres i inicialitzacio.

El criteri clau es reduir risc: cada fase ha de moure codi amb el minim canvi semantic possible, executar comprovacions i deixar el panell usable abans de continuar.

## Objectius

- Fer `scoring_notes_home.html` llegible i mantenible.
- Permetre que diversos subagents treballin en dominis separats amb poca probabilitat de conflicte.
- Conservar el comportament actual del panell de notes.
- Facilitar futures millores d'avis, validacions, rendiment i UI sense tocar un monolit de milers de linies.
- Fer explicit el contracte entre backend Django, template i JavaScript.

## No objectius

- No canviar el model de dades.
- No modificar endpoints ni noms de rutes.
- No redissenyar visualment el panell.
- No canviar la logica de calcul de notes o avisos.
- No eliminar encara el mode legacy si continua sent necessari com a fallback.
- No convertir el JavaScript a bundler, TypeScript o modul ES en aquesta migracio. Aixo seria una fase posterior.

## Estat actual del monolit

El fitxer actual combina aquests blocs aproximats:

- CSS inline al principi del template.
- Capcalera del panell, alerta d'inscripcions fora de programa, toolbar i contenidor principal lazy.
- Blocs legacy ocults: tabs i panes per grup.
- Drawer multimedia.
- Blocs `json_script` amb dades de backend.
- Bloc `extra_scripts` molt extens amb tota la logica client.
- Segon bloc de CSS dins `extra_scripts` que duplica part de l'estil.
- Inicialitzacio final en `DOMContentLoaded`.

Funcions i dominis rellevants detectats:

- Dades i estat: `SCHEMAS`, `LOGICAL_SCHEMAS`, `SCORES`, `INS`, `SUBJECTS_BY_ID`, `NOTES_STATE`, `keyFor`, `getScore`, `setScore`, `rememberSubjects`.
- Multimedia: `PLAYBACK_STATE`, `renderPlaybackPanel`, `loadPlaybackContext`, drawer i botons de video.
- Presencia i matrius de jutges: `presenceKey`, helpers de jutge, recompte i cel.les.
- Columnes visibles: panell de columnes, `localStorage`, selectors i toggles.
- Guardat i actualitzacions: `saveEntry`, `scheduleSave`, polling d'updates, focus descriptors.
- Avisos: avisos locals de cel.la, avisos globals, validacio d'avis.
- Renderitzadors: capcalera, cos de taula, equips, participants, totals i estats visuals.
- Navegacio: tabs legacy, selector de franja/unitat/grup, cerca, carrega lazy de taula.

## Estructura objectiu

La carpeta proposada:

```text
competicions_trampoli/templates/scoring/
  scoring_notes_home.html
  notes/
    _styles.html
    _page_header.html
    _out_of_program_alert.html
    _toolbar.html
    _main_shell.html
    _legacy_tabs.html
    _legacy_group_panes.html
    _media_drawer.html
    _json_contract.html
    scripts/
      _00_bootstrap.js.html
      _05_dom_helpers.js.html
      _10_store.js.html
      _15_api.js.html
      _20_playback.js.html
      _30_judge_presence.js.html
      _35_column_visibility.js.html
      _40_save_and_updates.js.html
      _45_focus_and_navigation.js.html
      _50_score_warnings.js.html
      _60_team_renderer.js.html
      _70_table_renderer.js.html
      _80_legacy_navigation.js.html
      _85_lazy_panel.js.html
      _90_global_warnings.js.html
      _99_init.js.html
```

`scoring_notes_home.html` hauria de quedar com a orquestrador:

```django
{% extends "base.html" %}
{% load static %}

{% block content %}
  {% include "scoring/notes/_styles.html" %}
  {% include "scoring/notes/_page_header.html" %}
  {% include "scoring/notes/_out_of_program_alert.html" %}
  {% include "scoring/notes/_toolbar.html" %}
  {% include "scoring/notes/_main_shell.html" %}
  {% include "scoring/notes/_legacy_tabs.html" %}
  {% include "scoring/notes/_legacy_group_panes.html" %}
  {% include "scoring/notes/_media_drawer.html" %}
  {% include "scoring/notes/_json_contract.html" %}
{% endblock %}

{% block extra_scripts %}
  {% include "scoring/notes/scripts/_00_bootstrap.js.html" %}
  ...
  {% include "scoring/notes/scripts/_99_init.js.html" %}
{% endblock %}
```

## Contractes que no es poden trencar

### Contracte de rutes

Mantenir els mateixos noms i usos de URL:

- `scoring_notes_manifest`
- `scoring_notes_table`
- `scoring_notes_warnings`
- `scoring_notes_warning_validate`
- `scoring_save_partial`
- `scoring_updates`
- `scoring_media_context`

Si una ruta no existeix en una branca concreta, el subagent ha d'aturar-se i documentar-ho. No ha d'inventar noms nous durant aquesta migracio.

### Contracte JSON

Els blocs `json_script` han de conservar IDs i forma de dades. No moure la responsabilitat de serialitzar dades al JavaScript.

IDs que cal preservar, segons el template actual:

- `schemas-data`
- `logical-schemas-data`
- `scores-data`
- `inscripcions-data`
- Dades de media counts.
- Dades de presencia de videos de jutges.
- Mapes de rotacio.
- Cursor inicial d'updates.

Si durant la revisio apareix algun ID addicional, s'ha d'afegir a `_json_contract.html` sense canviar-ne el nom.

### Contracte DOM

Preservar IDs, classes i atributs `data-*` que el JavaScript consulta:

- `data-scoring-table`
- `data-notes-main-table`
- `data-notes-*`
- Selectors de franja, unitat, grup i avisos.
- Contenidors del drawer multimedia.
- Contenidors de warnings globals.
- Cel.les i inputs que participen en guardat parcial.

Una extraccio de template no ha de canviar cap selector observable.

### Contracte JavaScript

El JavaScript actual funciona amb globals compartits. La fase de fragmentacio ha de conservar-los.

Globals importants:

- `SCHEMAS`
- `LOGICAL_SCHEMAS`
- `SCORES`
- `INS`
- `SUBJECTS_BY_ID`
- `NOTES_STATE`
- `PLAYBACK_STATE`

L'ordre d'inclusio dels scripts es part del contracte. Un subagent no ha de moure una funcio a un fitxer que s'inclou abans que les seves dependencies.

### Contracte funcional

La pantalla ha de continuar suportant:

- Carrega lazy de taules per franja/unitat/grup.
- Filtres i mode avisos globals.
- Guardat parcial de notes.
- Actualitzacions per polling.
- Avisos locals de cel.la.
- Avisos globals agregats i validables.
- Drawer multimedia i context de reproduccio.
- Presencia de jutges i columnes configurables.
- Renderitzat d'individuals i equips.
- Mode legacy ocult si encara s'usa com a fallback.

## Ordre d'inclusio JavaScript

Ordre recomanat i dependencies:

1. `_00_bootstrap.js.html`
   - Llegeix JSON scripts.
   - Defineix constants globals, endpoints i configuracio.

2. `_05_dom_helpers.js.html`
   - Helpers DOM purs, formatadors, parsejadors i utilitats sense estat fort.

3. `_10_store.js.html`
   - `NOTES_STATE`, `keyFor`, `getScore`, `setScore`, `rememberSubjects`, indexos de subjectes i scores.

4. `_15_api.js.html`
   - `fetch` helpers, CSRF, endpoints, errors comuns.

5. `_20_playback.js.html`
   - Estat i UI del drawer multimedia.

6. `_30_judge_presence.js.html`
   - Helpers de presencia de jutges, matrius, comptadors i disponibilitat.

7. `_35_column_visibility.js.html`
   - Panell de columnes, `localStorage`, toggles i aplicacio de visibilitat.

8. `_40_save_and_updates.js.html`
   - Guardat parcial, debounce, polling, aplicacio d'updates rebuts.

9. `_45_focus_and_navigation.js.html`
   - Focus descriptors, moviment entre inputs, restauracio de focus.

10. `_50_score_warnings.js.html`
    - Avisos locals de cel.la i helpers compartits amb avisos globals.

11. `_60_team_renderer.js.html`
    - Renderitzat especific d'equips.

12. `_70_table_renderer.js.html`
    - Capcalera, cos de taula, participants individuals, totals i repaint principal.

13. `_80_legacy_navigation.js.html`
    - Tabs i panes legacy.

14. `_85_lazy_panel.js.html`
    - Manifest, selectors, cerca, canvi de franja/unitat/grup, carrega lazy.

15. `_90_global_warnings.js.html`
    - Panell d'avis globals, validacio, refresh i estat visual.

16. `_99_init.js.html`
    - `DOMContentLoaded`, wiring final d'events i primera carrega.

## Fases de migracio

### Fase 0: inventari i baseline

Responsable recomanat: Subagent de verificacio.

Tasques:

- Confirmar linies totals i blocs principals del template actual.
- Fer una llista dels IDs `json_script`.
- Fer una llista dels IDs DOM i selectors `data-*` consultats per JavaScript.
- Fer una llista dels noms globals JavaScript declarats.
- Executar checks de base si l'entorn ho permet.

Sortida esperada:

- Notes curtes al PR o al resum de treball.
- Cap canvi funcional.

Definicio de fet:

- Es coneix el mapa del fitxer abans de moure codi.
- Hi ha un baseline de tests o, si no es poden executar, una explicacio concreta.

### Fase 1: extraccio HTML, CSS i JSON contract

Responsable recomanat: Subagent A.

Fitxers propietat:

- `templates/scoring/scoring_notes_home.html`
- `templates/scoring/notes/_styles.html`
- `templates/scoring/notes/_page_header.html`
- `templates/scoring/notes/_out_of_program_alert.html`
- `templates/scoring/notes/_toolbar.html`
- `templates/scoring/notes/_main_shell.html`
- `templates/scoring/notes/_legacy_tabs.html`
- `templates/scoring/notes/_legacy_group_panes.html`
- `templates/scoring/notes/_media_drawer.html`
- `templates/scoring/notes/_json_contract.html`

Tasques:

- Crear carpeta `templates/scoring/notes/`.
- Moure CSS del bloc `content` a `_styles.html`.
- Moure blocs HTML a parcials, sense editar selectors ni classes.
- Moure tots els `json_script` a `_json_contract.html`.
- Deixar `scoring_notes_home.html` com a fitxer orquestrador.

Notes:

- Si hi ha CSS duplicat dins `extra_scripts`, no eliminar-lo encara excepte si es pot demostrar que es exactament duplicat i no altera l'ordre.
- Aquesta fase no ha de tocar la logica JavaScript.

Definicio de fet:

- La pagina renderitza amb la mateixa estructura DOM.
- `python manage.py check` passa.
- No hi ha errors de template includes.

### Fase 2: bootstrap, helpers, estat i API

Responsables recomanats: Subagents B i C si es vol paral.lelitzar amb cura.

Fitxers propietat:

- `templates/scoring/notes/scripts/_00_bootstrap.js.html`
- `templates/scoring/notes/scripts/_05_dom_helpers.js.html`
- `templates/scoring/notes/scripts/_10_store.js.html`
- `templates/scoring/notes/scripts/_15_api.js.html`
- `templates/scoring/scoring_notes_home.html` nomes per afegir includes.

Tasques:

- Crear carpeta `templates/scoring/notes/scripts/`.
- Extreure lectura de JSON i constants a `_00_bootstrap`.
- Extreure helpers purs a `_05_dom_helpers`.
- Extreure estat de notes i indexos a `_10_store`.
- Extreure helpers de xarxa i CSRF a `_15_api`.

Regla:

- Els noms de funcions i variables globals s'han de mantenir. No convertir encara a namespaces.

Definicio de fet:

- El panell carrega sense errors de consola per variables indefinides.
- El guardat encara pot trobar `NOTES_STATE`, endpoints i scores.

### Fase 3: multimedia i playback

Responsable recomanat: Subagent C.

Fitxers propietat:

- `templates/scoring/notes/scripts/_20_playback.js.html`
- Pot tocar `_media_drawer.html` nomes si cal afegir comentaris o conservar markup.

Tasques:

- Moure `PLAYBACK_STATE`.
- Moure renderitzat del panell multimedia.
- Moure carrega de context multimedia.
- Moure handlers d'obrir/tancar drawer si estan acoblats al playback.

Contractes:

- IDs del drawer intactes.
- Mateix endpoint `scoring_media_context`.
- Mateix comportament quan no hi ha videos.

Definicio de fet:

- Obrir video des d'una fila continua carregant el drawer.
- Tancar el drawer no deixa estat visual inconsistent.

### Fase 4: presencia de jutges i columnes

Responsables recomanats: Subagents D i E amb fitxers separats.

Fitxers propietat:

- `_30_judge_presence.js.html`
- `_35_column_visibility.js.html`

Tasques Subagent D:

- Moure helpers de presencia de jutges.
- Moure construccio de claus de presencia.
- Moure comptadors i disponibilitat de jutges per esquema/exercici/camp.

Tasques Subagent E:

- Moure configuracio de columnes visibles.
- Moure panell de columnes.
- Preservar claus de `localStorage`.

Definicio de fet:

- Les columnes es poden ocultar/mostrar igual que abans.
- La presencia de jutges continua afectant avisos i renderitzat.

### Fase 5: guardat, updates i focus

Responsable recomanat: Subagent F.

Fitxers propietat:

- `_40_save_and_updates.js.html`
- `_45_focus_and_navigation.js.html`

Tasques:

- Moure `saveEntry`, `scheduleSave` i logica de debounce.
- Moure polling d'updates i aplicacio de canvis remots.
- Moure descriptors de focus i restauracio de focus.
- Moure navegacio de teclat entre inputs si esta barrejada.

Contractes:

- No canviar payloads enviats al backend.
- No canviar noms de camps.
- No canviar timing de debounce excepte si es documenta com a bugfix separat.

Definicio de fet:

- Editar una nota guarda correctament.
- Un update remot no trenca el focus actiu.
- Les proves d'API de notes continuen passant.

### Fase 6: avisos locals i globals

Responsable recomanat: Subagent G.

Fitxers propietat:

- `_50_score_warnings.js.html`
- `_90_global_warnings.js.html`

Tasques:

- Moure logica d'avis local de cel.la.
- Moure logica del panell global d'avisos.
- Moure validacio d'avis i refresc posterior.
- Preservar textos visibles actuals excepte correccions ortografiques molt petites aprovades.

Contractes:

- Endpoints `scoring_notes_warnings` i `scoring_notes_warning_validate`.
- Els avisos validats han de deixar d'apareixer si el backend ja ho fa.
- El mode "tots els avisos" no ha de perdre filtres si el comportament actual els conserva.

Definicio de fet:

- Els avisos locals segueixen apareixent a la taula.
- El panell global carrega avisos.
- Validar un avis continua funcionant.

### Fase 7: renderitzadors de taula

Responsables recomanats: Subagents H i I.

Fitxers propietat:

- `_60_team_renderer.js.html`
- `_70_table_renderer.js.html`

Tasques Subagent H:

- Moure renderitzat especific d'equips.
- Moure cel.les, totals i estructura propia d'equip.
- No tocar renderitzat individual excepte dependencies compartides.

Tasques Subagent I:

- Moure `buildHeader`, `buildBody` i renderitzat individual.
- Moure helpers de files, cel.les, estats visuals i totals.
- Mantenir dependencias cap a avisos, presencia i guardat.

Risc:

- Aquesta fase es la de mes risc per quantitat de dependencies.
- Si un renderitzador usa helpers d'un altre domini, no duplicar-los. Moure el helper compartit a `_05_dom_helpers` o mantenir-lo en el fitxer que ja s'inclou abans.

Definicio de fet:

- Taules individuals renderitzen igual.
- Taules d'equip renderitzen igual.
- Edicio, avisos i videos continuen disponibles dins la taula.

### Fase 8: navegacio lazy, filtres i inicialitzacio

Responsable recomanat: Subagent J.

Fitxers propietat:

- `_80_legacy_navigation.js.html`
- `_85_lazy_panel.js.html`
- `_99_init.js.html`

Tasques:

- Moure tabs i navegacio legacy.
- Moure selectors de franja/unitat/grup.
- Moure cerca i estat del panell lazy.
- Moure `DOMContentLoaded` i wiring final a `_99_init`.

Contractes:

- La primera carrega del panell ha de seleccionar el mateix grup que abans.
- Els filtres han de generar les mateixes crides lazy.
- El mode avisos globals ha de continuar sent accessible.

Definicio de fet:

- La pagina arrenca sense errors.
- Canviar franja/unitat/grup carrega la taula esperada.
- La cerca continua filtrant opcions.

### Fase 9: neteja controlada

Responsable recomanat: Subagent de manteniment o integrador final.

Tasques:

- Eliminar CSS duplicat si es comprova que ja esta consolidat.
- Afegir comentaris curts al principi de cada parcial explicant propietat i dependencies.
- Revisar noms de fitxer i includes.
- Actualitzar aquest document si la migracio real divergeix.

No fer encara:

- No namespacejar tot el JS.
- No reescriure renderitzadors.
- No eliminar legacy sense confirmacio funcional.

Definicio de fet:

- El fitxer principal es curt i nomes orquestra includes.
- Cada parcial te una responsabilitat clara.
- No queden blocs grans duplicats sense justificacio.

## Repartiment recomanat per subagents

### Subagent A: estructura template

Responsabilitat:

- HTML, CSS i JSON contract.

Pot tocar:

- `scoring_notes_home.html`
- `notes/_*.html` no scripts.

No pot tocar:

- Logica JavaScript.
- Views Python.
- Tests funcionals.

### Subagent B: bootstrap i estat

Responsabilitat:

- Constants, lectura JSON, estat i helpers de dades.

Pot tocar:

- `_00_bootstrap.js.html`
- `_05_dom_helpers.js.html`
- `_10_store.js.html`
- `_15_api.js.html`

No pot tocar:

- Renderitzadors de taula.
- Logica d'avis.

### Subagent C: multimedia

Responsabilitat:

- Drawer multimedia i playback.

Pot tocar:

- `_20_playback.js.html`
- `_media_drawer.html` si cal.

No pot tocar:

- Guardat de notes.
- Warnings.

### Subagent D: presencia de jutges

Responsabilitat:

- Presencia, comptadors i matrius de jutges.

Pot tocar:

- `_30_judge_presence.js.html`

No pot tocar:

- Columnes visibles, excepte dependencies documentades.

### Subagent E: columnes visibles

Responsabilitat:

- Configuracio de columnes i persistencia en navegador.

Pot tocar:

- `_35_column_visibility.js.html`

No pot tocar:

- Renderitzadors excepte crides ja existents.

### Subagent F: guardat i updates

Responsabilitat:

- Persistencia parcial, debounce, polling i focus.

Pot tocar:

- `_40_save_and_updates.js.html`
- `_45_focus_and_navigation.js.html`

No pot tocar:

- Backend d'API si no hi ha bug confirmat.

### Subagent G: avisos

Responsabilitat:

- Avisos locals i globals.

Pot tocar:

- `_50_score_warnings.js.html`
- `_90_global_warnings.js.html`

No pot tocar:

- Serveis Python de warnings en aquesta migracio estructural.

### Subagent H: equips

Responsabilitat:

- Renderitzat de taules d'equip.

Pot tocar:

- `_60_team_renderer.js.html`

No pot tocar:

- Renderitzat individual.

### Subagent I: taules individuals

Responsabilitat:

- Renderitzat general i individual.

Pot tocar:

- `_70_table_renderer.js.html`

No pot tocar:

- Lazy panel i inicialitzacio.

### Subagent J: navegacio i arrencada

Responsabilitat:

- Lazy loading, selectors, cerca, legacy navigation i init.

Pot tocar:

- `_80_legacy_navigation.js.html`
- `_85_lazy_panel.js.html`
- `_99_init.js.html`

No pot tocar:

- Renderitzadors, excepte crides publiques.

### Integrador final

Responsabilitat:

- Revisar ordre d'includes.
- Resoldre dependencies creuades.
- Executar tests.
- Fer smoke manual.
- Actualitzar documentacio.

## Regles de treball per subagents

- Treballar sempre en un domini petit i amb fitxers propietat clars.
- No fer refactors funcionals barrejats amb moviments de codi.
- No canviar noms publics de funcions globals durant la fragmentacio.
- Si una funcio mouda necessita una dependency que queda mes tard en l'ordre, moure la dependency a un fitxer anterior o deixar la funcio en el seu domini original.
- No duplicar helpers per sortir del pas.
- No eliminar legacy ni CSS duplicat fins a la fase de neteja.
- Cada subagent ha de deixar un resum amb:
  - Fitxers tocats.
  - Funcions mogudes.
  - Contractes preservats.
  - Tests executats o motiu pel qual no s'han executat.

## Estrategia de verificacio

### Checks automatics recomanats

Executar com a minim:

```bash
python manage.py check
```

Si hi ha Docker en l'entorn del projecte, l'equivalent habitual es:

```bash
docker compose exec -T web python manage.py check
```

Tests recomanats segons domini:

```bash
docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.notes.test_notes_api --verbosity 1 --keepdb
docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.test_score_warnings --verbosity 1 --keepdb
docker compose exec -T web python manage.py test competicions_trampoli.tests.rotacions.test_ordering_display --verbosity 1 --keepdb
```

Si existeixen tests especifics d'equips o updates en la branca:

```bash
docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.team --verbosity 1 --keepdb
docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.notes --verbosity 1 --keepdb
```

### Smoke manual recomanat

Fer una passada manual al panell:

- Obrir el panell de notes.
- Confirmar que no hi ha errors de consola.
- Canviar franja, unitat i grup.
- Editar una nota i veure estat de guardat.
- Obrir el drawer multimedia des d'una fila amb video.
- Mostrar/ocultar columnes.
- Revisar avisos locals dins taula.
- Obrir vista d'avis global.
- Validar un avis i comprovar que desapareix si correspon.
- Provar una taula individual i una taula d'equip.

## Riscos i mitigacions

### Risc: ordre de scripts trencat

Signe:

- Errors tipus `ReferenceError`.

Mitigacio:

- Respectar l'ordre d'inclusio d'aquest document.
- Si cal, moure helpers compartits a `_05_dom_helpers` o `_10_store`.

### Risc: selector DOM canviat accidentalment

Signe:

- Botons que no fan res, taules buides o guardat que no troba inputs.

Mitigacio:

- En fase 1, moure HTML literalment.
- No canviar classes, IDs ni `data-*`.

### Risc: CSS duplicat o ordre visual alterat

Signe:

- Layout diferent, toolbar trencada, drawer mal posicionat.

Mitigacio:

- Primer conservar tot el CSS.
- Consolidar nomes a fase 9.

### Risc: renderitzadors massa acoblats

Signe:

- Funcions de taula criden helpers que encara no existeixen.

Mitigacio:

- Extreure renderitzadors tard, quan store/API/presencia/warnings ja estan separats.

### Risc: avisos globals depenen del lazy panel

Signe:

- La vista d'avis perd filtres o no refresca.

Mitigacio:

- Moure avisos globals despres de lazy panel o deixar una API publica clara entre `_85_lazy_panel` i `_90_global_warnings`.

## Criteris d'acceptacio finals

- `scoring_notes_home.html` queda curt i nomes inclou parcials.
- La carpeta `templates/scoring/notes/` conte els dominis descrits.
- Cap endpoint ni URL name ha canviat.
- Cap ID `json_script` ha canviat.
- Cap selector DOM usat pel JavaScript ha canviat sense justificacio.
- El panell permet editar notes, navegar per filtres, obrir multimedia i validar avisos.
- Els tests rellevants passen o queda documentat per que no s'han pogut executar.
- El document queda actualitzat si la implementacio real canvia noms o fases.

## Recomanacio de primera iteracio

La primera iteracio futura hauria de limitar-se a Fase 1 i Fase 2. Aixo redueix molt el tamany visual del fitxer sense tocar encara les parts mes delicades: renderitzadors, guardat, updates i avisos.

La segona iteracio pot atacar Fases 3 a 6.

La tercera iteracio hauria de reservar-se per renderitzadors i lazy panel, que son les zones amb mes dependencies creuades.

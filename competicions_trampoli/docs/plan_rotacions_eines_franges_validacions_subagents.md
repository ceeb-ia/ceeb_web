# Pla d'implementacio V1: eines operatives del planner de rotacions

## Objectiu

Afegir eines operatives al planner de rotacions per fer mes rapida la programacio de competicio, sense convertir la barra superior en un calaix de sastre.

La V1 ha de prioritzar:

- seleccio de franges i accions massives sobre aquestes;
- duplicar franges;
- desplacar o ajustar temps;
- validacions basiques del programa;
- notes internes per franja;
- mantenir coherencia amb l'estil actual de barra superior tipus Excel.

No incloure encara plantilles de programa. Les plantilles queden fora de V1.

## Estat de partida

La pantalla actual de rotacions ja esta parcialment modularitzada:

- Template principal: `competicions_trampoli/templates/competicio/rotacions_planner.html`
- Barra superior: `competicions_trampoli/templates/competicio/rotacions/_toolbar.html`
- Graella: `competicions_trampoli/templates/competicio/rotacions/_grid.html`
- Files:
  - `templates/competicio/rotacions/grid/_row_competitive.html`
  - `templates/competicio/rotacions/grid/_row_global.html`
- Panells:
  - `templates/competicio/rotacions/drawer/_programables.html`
  - `templates/competicio/rotacions/drawer/_franges.html`
  - `templates/competicio/rotacions/drawer/_globals.html`
- JS monolitic principal:
  - `templates/competicio/rotacions/scripts/_planner.html`
- JS parcial ja iniciat:
  - `templates/competicio/rotacions/scripts/planner/_toolbar.html`
  - `templates/competicio/rotacions/scripts/planner/_programables.html`
- Models:
  - `competicions_trampoli/models/rotacions.py`
- Views:
  - `competicions_trampoli/views/rotacions/planner.py`
  - `competicions_trampoli/views/rotacions/franges.py`
  - `competicions_trampoli/views/rotacions/assignments.py`
- URLs:
  - `competicions_trampoli/urls/rotacions.py`

El planner ja disposa de:

- creacio manual de franges;
- generacio automatica de franges;
- edicio inline via modal;
- insercio despres d'una franja;
- eliminacio;
- neteja d'una franja;
- extrapolar;
- DnD de franges competitives;
- DnD visual de franges globals;
- colors de franja;
- compatibilitat d'aparell al moment de programar.

## Principis de disseny

- `Franges` ha de contenir accions que creen o modifiquen estructura temporal.
- `Eines` ha de contenir accions de diagnostic, cerca, notes i revisio global.
- Les accions massives nomes han d'apareixer com a rellevants quan hi ha franges seleccionades.
- Cap accio destructiva pot executar-se sense confirmacio clara.
- Les accions que afecten hores han de reutilitzar el model existent de preview/confirmacio quan provoquen desplacaments de franges posteriors.
- Evitar seguir fent gros el monolit `_planner.html`; afegir parcials nous a `scripts/planner/`.

## Arquitectura proposada

Crear aquests parcials JS:

- `templates/competicio/rotacions/scripts/planner/_franges_selection.html`
- `templates/competicio/rotacions/scripts/planner/_franges_bulk_actions.html`
- `templates/competicio/rotacions/scripts/planner/_validations.html`
- `templates/competicio/rotacions/scripts/planner/_notes.html`

Incloure'ls a `rotacions_planner.html` despres de `_planner.html` i despres dels parcials ja existents, perque puguin reutilitzar helpers globals com `postJSON`, `showAlert`, `showConfirm`, `renderAll`, `grid`, `groupSidebar`, `stationModes`, etc.

Ordre recomanat:

```django
{% include "competicio/rotacions/scripts/_planner.html" %}
{% include "competicio/rotacions/scripts/planner/_toolbar.html" %}
{% include "competicio/rotacions/scripts/planner/_programables.html" %}
{% include "competicio/rotacions/scripts/planner/_franges_selection.html" %}
{% include "competicio/rotacions/scripts/planner/_franges_bulk_actions.html" %}
{% include "competicio/rotacions/scripts/planner/_validations.html" %}
{% include "competicio/rotacions/scripts/planner/_notes.html" %}
```

## Fase 1: seleccio de franges

### Objectiu

Permetre seleccionar una o diverses franges des de la graella i mostrar una barra contextual dins la pestanya `Franges`.

### UI

Afegir un checkbox petit a cada capcalera de franja:

- en `grid/_row_competitive.html`;
- en `grid/_row_global.html`, si es decideix permetre accions sobre franges globals;
- recomanacio V1: permetre seleccio de totes les franges, pero limitar certes accions a competitives.

El checkbox ha d'estar integrat dins `.franja-title` o `.franja-head`, amb classe:

- `.js-franja-select`
- `data-franja-id="{{ f.id }}"`
- `data-franja-tipus="{{ f.tipus }}"`
- `data-franja-competitive="{{ f.is_competitive|yesno:'1,0' }}"`

Afegir bloc a `drawer/_franges.html`:

- titol: `Seleccio`
- comptador: `0 franges seleccionades`
- botons:
  - `Netejar`
  - `Duplicar`
  - `Desplacar`
  - `Canviar color`
  - `Canviar tipus`
  - `Eliminar`

El bloc pot estar desactivat o en estat buit quan no hi ha seleccio.

### JS

`_franges_selection.html` ha de gestionar:

- estat `selectedFranjaIds: Set<string>`;
- `toggleFranjaSelection(id, checked)`;
- `clearFranjaSelection()`;
- `syncFranjaSelectionUI()`;
- actualitzar classes visuals:
  - fila seleccionada: `.is-selected-franja`;
  - bloc d'accions actiu: `.has-franja-selection`.

### CSS

Afegir a `styles/_components.html` o nou parcial si es considera:

- `.franja-selection-check`
- `.franja-row-competitive.is-selected-franja > th`
- `.franja-row-competitive.is-selected-franja > td`
- `.franja-bulk-panel`
- `.franja-bulk-actions`

Visualment ha de seguir l'estil actual: vora amber suau, fons clar, botons compactes.

## Fase 2: accions massives sobre franges

### Objectiu

Executar accions sobre les franges seleccionades.

### Accions V1

1. Netejar assignacions
2. Eliminar franges
3. Canviar color
4. Canviar tipus
5. Desplacar temps
6. Duplicar franges

### Backend recomanat

Crear endpoints nous a `views/rotacions/franges.py`:

- `rotacions_franges_bulk_clear`
- `rotacions_franges_bulk_delete`
- `rotacions_franges_bulk_update`
- `rotacions_franges_bulk_shift`
- `rotacions_franges_bulk_duplicate`

Afegir URLs a `urls/rotacions.py`.

Payloads recomanats:

```json
{
  "franja_ids": [1, 2, 3]
}
```

```json
{
  "franja_ids": [1, 2],
  "color_fons": "#DBEAFE"
}
```

```json
{
  "franja_ids": [1, 2],
  "tipus": "break"
}
```

```json
{
  "franja_ids": [1, 2],
  "minutes": 10,
  "preview_only": true
}
```

```json
{
  "franja_ids": [1, 2],
  "offset_minutes": 30,
  "copy_assignments": false
}
```

### Regles de negoci

#### Netejar

- Esborrar assignacions de `RotacioAssignacio` per les franges seleccionades.
- No eliminar la franja.
- Confirmacio obligatoria.

#### Eliminar

- Eliminar franges seleccionades i assignacions associades.
- Confirmacio obligatoria.
- Despres de l'eliminacio, recalcular `ordre` i `ordre_visual` si cal.

#### Canviar color

- Actualitzar `color_fons`.
- Acceptar cadena buida per tornar al color per defecte.
- Reutilitzar `normalize_hex_color`.

#### Canviar tipus

- Validar contra `RotacioFranja.TIPUS_CHOICES`.
- Si es converteix una franja competitiva en no competitiva, cal avisar que les assignacions poden perdre sentit.
- Recomanacio V1: si una franja competitiva te assignacions, bloquejar canvi a tipus no competitiu o exigir confirmacio explicita.

#### Desplacar temps

- Sumar/restar minuts a `hora_inici` i `hora_fi`.
- Preservar durada.
- Si afecta franges competitives posteriors, reutilitzar la logica de preview existent a `submitFranjaMutation` o extreure-la a servei compartit.
- No permetre hores invalides.

#### Duplicar

- Crear franges noves immediatament despres de la seleccio, preservant durades i tipus.
- Recomanacio V1:
  - per defecte no copiar assignacions;
  - opcional `copy_assignments`.
- Recalcular ordre de franges posteriors.
- Si hi ha solapament temporal, oferir preview/confirmacio.

### JS

`_franges_bulk_actions.html` ha de:

- llegir seleccio de `_franges_selection.html`;
- obrir controls inline o modal petit per color/tipus/desplacament;
- cridar endpoints amb `postJSON`;
- gestionar confirmacions;
- fer `location.reload()` quan l'accio modifica estructura de franges.

Per V1 es acceptable recarregar pagina despres d'accions massives de franges. No cal fer render incremental.

## Fase 3: validacions de programa

### Objectiu

Afegir una seccio a `Eines` que revisi el programa i retorni errors, avisos i informacio util.

### UI

Afegir bloc a `drawer/_globals.html` quan `globals_part == "after_franges"` o crear parcial nou `drawer/_validacions.html` inclos dins panel `globals`.

Contingut:

- titol: `Validacio`
- boto: `Validar programa`
- resum:
  - `0 errors`
  - `0 avisos`
- llista agrupada:
  - `Errors`
  - `Avisos`
  - `Info`

Cada resultat ha de tenir:

- tipus (`error`, `warning`, `info`);
- missatge curt;
- accio opcional `Anar-hi` que ressalti franja/cel.la afectada.

### Validacions V1

1. Grup duplicat dins el programa
   - Detectar si un mateix `key` (`g:`, `s:`, `pu:`) apareix en mes d'una cel.la.
   - Distingir duplicat en franges diferents i duplicat dins mateixa franja.

2. Gimnasta/equip simultani en dos aparells a la mateixa franja
   - Per cada franja, expandir els subjectes dels programables.
   - Si un subjecte apareix en mes d'una estacio en la mateixa franja, error.
   - Cal suportar:
     - grups individuals;
     - series d'equip;
     - program units si ja porten membres/slots.

3. Aparell incompatible
   - Tot i que el DnD ja ho bloqueja, validar estat persistent.
   - Per cada assignacio, verificar `itemAllowedInStation(key, estacioId)` o equivalent backend.
   - Si hi ha inconsistencies antigues o importades, mostrar error.

4. Franges buides
   - Warning, no error.

5. Programables pendents
   - Warning o info segons volum.

### Backend vs frontend

Recomanacio: implementar validacio principal backend per evitar divergencies.

Crear servei:

- `competicions_trampoli/services/rotacions/validation.py`

Funcio:

```python
def validate_rotacions_program(competicio) -> dict:
    return {
        "errors": [],
        "warnings": [],
        "info": [],
    }
```

Cada item:

```python
{
    "code": "duplicate_program_item",
    "message": "...",
    "franja_id": 1,
    "estacio_id": 2,
    "program_key": "g:10",
    "severity": "error",
}
```

Endpoint:

- `rotacions_validate_program`

El frontend nomes renderitza resultats i enfoca/rassalta cel.les.

### Ressaltat

Afegir helper JS:

- `highlightPlannerCell(franjaId, estacioId)`
- `highlightPlannerRow(franjaId)`

Ha de fer scroll dins `.grid-wrap` i aplicar classe temporal `.is-validation-highlight`.

## Fase 4: notes internes

### Objectiu

Permetre notes internes per franja i veure-les globalment dins `Eines`.

### Model

Opcio simple V1: afegir camp a `RotacioFranja`:

```python
nota_interna = models.TextField(blank=True, default="")
```

Crear migracio.

Alternativa mes flexible, no necessaria V1:

- model `RotacioNotaInterna` amb autor, timestamps i scope.

### UI per franja

Afegir accio al menu de franja:

- `Nota interna`

Obre modal petit:

- titol franja;
- textarea;
- guardar.

Mostrar indicador discret a la capcalera de franja quan te nota:

- icona petita o badge `Nota`.

### UI global

Afegir bloc a `Eines`:

- `Notes internes`
- llista de franges amb nota;
- clic a una nota fa scroll a la franja;
- editar des de la llista.

### Backend

Endpoint:

- `rotacions_franja_note_save`

Payload:

```json
{
  "franja_id": 1,
  "nota_interna": "..."
}
```

Resposta:

```json
{
  "ok": true,
  "franja_id": 1,
  "nota_interna": "..."
}
```

## Fase 5: reorganitzacio de panells

### Pestanya Franges

Estructura recomanada:

1. `Crear franja`
2. `Generar franges automaticament`
3. `Seleccio`
4. `Temps`

La seccio `Temps` pot contenir shortcuts:

- `-10`
- `-5`
- `+5`
- `+10`
- input custom.

### Pestanya Eines

Estructura recomanada:

1. `Validacio`
2. `Cerca dins programa` (pot quedar placeholder si no entra a V1)
3. `Notes internes`
4. `Programa`

`Netejar tot` ha de quedar a `Eines > Programa`, no a `Franges`, perque afecta tot el programa.

## Ordre d'implementacio recomanat

1. Afegir seleccio visual de franges.
2. Afegir panell `Seleccio` dins `Franges`.
3. Implementar `bulk_clear` i `bulk_delete`.
4. Implementar `bulk_update` per color/tipus.
5. Implementar `bulk_shift`.
6. Implementar `bulk_duplicate`.
7. Afegir servei backend de validacio.
8. Afegir panel de validacions a `Eines`.
9. Afegir notes internes al model, migracio, modal i panel global.
10. Netejar helpers duplicats del monolit si queden obsolets.

## Fitxers esperats

### Nous

- `competicions_trampoli/services/rotacions/validation.py`
- `competicions_trampoli/templates/competicio/rotacions/scripts/planner/_franges_selection.html`
- `competicions_trampoli/templates/competicio/rotacions/scripts/planner/_franges_bulk_actions.html`
- `competicions_trampoli/templates/competicio/rotacions/scripts/planner/_validations.html`
- `competicions_trampoli/templates/competicio/rotacions/scripts/planner/_notes.html`
- migracio per `RotacioFranja.nota_interna`

### Modificats

- `competicions_trampoli/models/rotacions.py`
- `competicions_trampoli/views/rotacions/franges.py`
- `competicions_trampoli/views/rotacions/planner.py`
- `competicions_trampoli/urls/rotacions.py`
- `templates/competicio/rotacions_planner.html`
- `templates/competicio/rotacions/drawer/_franges.html`
- `templates/competicio/rotacions/drawer/_globals.html`
- `templates/competicio/rotacions/grid/_row_competitive.html`
- `templates/competicio/rotacions/grid/_row_global.html`
- `templates/competicio/rotacions/styles/_components.html`
- `templates/competicio/rotacions/scripts/_planner.html` nomes per exposar o moure helpers si cal.

## Tests recomanats

### Backend

Crear tests a:

- `competicions_trampoli/tests/rotacions/test_bulk_franges.py`
- `competicions_trampoli/tests/rotacions/test_validation.py`
- `competicions_trampoli/tests/rotacions/test_notes.py`

Cobrir:

- bulk clear elimina assignacions pero no franges;
- bulk delete elimina franges i assignacions;
- bulk color valida hex i permet color buit;
- bulk tipus valida tipus;
- bulk shift preserva durada;
- bulk duplicate crea franges ordenades;
- validacio detecta duplicats;
- validacio detecta subjecte simultani;
- validacio detecta aparell incompatible;
- nota interna es guarda i es renderitza.

### Smoke/render

Executar:

```powershell
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py test competicions_trampoli.tests.rotacions --verbosity 1
docker compose run --rm web python manage.py shell -c "from django.template.loader import get_template; get_template('competicio/rotacions_planner.html'); print('template ok')"
```

Render real:

```powershell
docker compose run --rm web python manage.py shell -c "from django.test import RequestFactory; from competicions_trampoli.models import Competicio; from competicions_trampoli.views.rotacions.planner import rotacions_planner; c=Competicio.objects.first(); print('competicio', getattr(c, 'id', None)); resp=rotacions_planner(RequestFactory().get('/'), c.id) if c else None; print(getattr(resp, 'status_code', None), len(resp.content) if resp else 0)"
```

## Riscos i punts d'atencio

- No duplicar logica de compatibilitat aparell/grup entre frontend i backend sense test.
- Vigilar que `ProgramUnit` i `SerieEquipItem` no quedin fora de validacions de simultaneitat.
- No fer accions massives sobre franges globals com si fossin competitives si afecten scoring.
- Evitar que `bulk_shift` generi solapaments silenciosos.
- No perdre assignacions accidentalment en `bulk_duplicate`; fer `copy_assignments` explicit.
- No incrementar mes el monolit `_planner.html` excepte per extreure helpers compartits.

## Criteris d'acceptacio

- Es poden seleccionar diverses franges des de la graella.
- La pestanya `Franges` mostra accions contextuals quan hi ha seleccio.
- Es poden netejar, eliminar, canviar color/tipus, desplacar i duplicar franges seleccionades.
- La pestanya `Eines` permet validar el programa i mostra errors/avisos agrupats.
- Les validacions detecten com a minim:
  - programable duplicat;
  - gimnasta/equip simultani en una mateixa franja;
  - aparell incompatible.
- Es poden crear i consultar notes internes per franja.
- La UI manté l'estil actual de la barra superior i del planner.
- `manage.py check`, render de plantilla i render real del planner passen.


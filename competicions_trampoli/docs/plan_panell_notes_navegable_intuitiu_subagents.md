# Pla Per Fer El Panell De Notes Navegable I Intuitiu

## Objectiu

Aquest document es per a un agent extern sense context previ.

L'objectiu es canviar el panell central de notes perque deixi de funcionar com una cadena obligatoria de filtres:

`franja -> aparell -> unitat/grup -> exercici`

El model nou ha de ser mes simple:

- Franja pot ser una franja concreta o `Totes`.
- Aparell pot ser un aparell concret o `Tots`.
- Grup/unitat pot ser un grup/unitat concret o `Tots`.
- Subjecte pot estar buit o ser una inscripcio/equip concret.
- Avisos pot estar desactivat o filtrar contextos amb avisos.

Quan un filtre esta a `Tots`, no s'ha d'escollir automaticament un valor concret. El panell ha de mostrar resultats agrupats i deixar que l'usuari decideixi quin context editable obrir.

## Problema Actual

El panell actual esta pensat per operar una sola taula editable a la vegada. Aixo fa que sempre acabi forcant una seleccio maxima:

`franja concreta + aparell concret + unitat concreta + exercici concret`

Casos que fallen:

- Buscar una inscripcio obre el primer context, encara que existeixi en altres franges o aparells.
- Si despres de buscar una inscripcio l'usuari canvia l'aparell, el grup/unitat es recalcula dins la franja actual i es perd el subjecte.
- No es pot veure "DMT a totes les franges" sense entrar franja per franja.
- No es pot veure "Grup 3 a tots els aparells" com a resultat agrupat.
- "Tots els avisos" esta massa barrejat amb el filtre de files de la taula activa.

El problema de fons no es que falti un altre mode complex. El problema es que els selectors actuals son dependents i obligatoris. Cal convertir-los en filtres independents amb opcio `Tots`.

## Principi De Disseny

Separar dues vistes:

1. **Vista de resultats**
   - S'utilitza quan un o mes filtres estan a `Tots`, o quan la cerca retorna multiples contextos.
   - Mostra targetes/files agrupades per franja, aparell, unitat i exercici.
   - No construeix una taula editable gegant.
   - Cada resultat te una accio `Obrir` que carrega la taula concreta.

2. **Vista de taula editable**
   - S'utilitza nomes quan el context es unic:
     `franja concreta + aparell concret + unitat concreta + exercici concret`.
   - Carrega `notes_table`.
   - Mante guardat parcial, polling, focus de fila i multimedia lazy.

La regla principal:

> Els filtres decideixen el conjunt de contextos visibles. La taula editable nomes apareix quan l'usuari obre un context concret.

## Estat Actual Del Codi

Fitxers principals:

- `competicions_trampoli/views/scoring/notes.py`
  - Vista HTML del panell.
  - Encara pot construir payload inicial gran: schemas, scores, inscripcions, media counts, videos i rotacions.

- `competicions_trampoli/views/scoring/notes_api.py`
  - `notes_manifest`: metadata del programa.
  - `notes_table`: carrega una taula concreta.
  - `notes_warnings`: avisos agregats.
  - `notes_warning_validate`: validacio d'avisos.
  - `notes_search`, si existeix: pot retornar contextos, pero el frontend no ha d'obrir automaticament el primer.

- `competicions_trampoli/services/scoring/notes_units.py`
  - Construeix unitats de notes a partir de rotacions.
  - Dona `units`, `out_of_program_units`, `grouped_inscripcions`, `team_subjects_by_bucket`.
  - Ja representa cel-les multi-grup com unitats.

- `competicions_trampoli/templates/scoring/notes/scripts/_85_lazy_panel.js.html`
  - Logica de selectors, cerca i carrega lazy.
  - Punt critic: substituir selectors en cascada per filtres independents.

- `competicions_trampoli/templates/scoring/notes/scripts/_90_global_warnings.js.html`
  - Panell d'avisos globals.

- `competicions_trampoli/tests/scoring/notes/test_notes_api.py`
  - Tests backend de notes.

## Nou Model De Filtres

### Estat Frontend Recomanat

```js
const NOTES_STATE = {
  manifest: null,

  filters: {
    franja: "all",       // "all", "off", or franja id
    appId: "all",        // "all" or comp_aparell id
    unitKey: "all",      // "all" or unit key
    exercici: "all",     // "all" or exercise number
    subject: null,       // null or {subject_kind, subject_id, name}
    warnings: "all"      // "all", "with-warnings", "without-warnings"
  },

  resultContexts: [],
  selectedContext: null,
  view: "summary",       // "summary" or "table"

  loadingKey: "",
  warningsLoadingKey: "",
  searchLoadingKey: ""
};
```

No cal que l'usuari vegi "modes". Internament nomes cal saber si s'esta mostrant resum o taula.

### Filtres Independents

Els selectors no han de buidar ni forcar els altres per defecte.

Exemples:

- `Franja = Totes`, `Aparell = DMT`, `Grup = Tots`
  - Mostra totes les unitats de DMT a totes les franges.

- `Subjecte = Anna`, `Aparell = Tots`, `Franja = Totes`
  - Mostra tots els contextos d'Anna.

- `Grup = 3`, `Aparell = Tots`, `Franja = Totes`
  - Mostra totes les aparicions del Grup 3.

- `Aparell = Tots`, `Franja = Franja 2`
  - Mostra tots els aparells i unitats de la Franja 2.

- `Tot = Tots`
  - Mostra una vista organitzada de tota la competicio, no una taula editable massiva.

## Vista De Resultats

La vista de resultats ha d'agrupar contextos. No ha de renderitzar totes les taules.

Agrupacio recomanada:

```text
Franja 1
  DMT
    Grup 1 + Grup 2 - 18 subjectes - 2 avisos - [Obrir ex. 1] [Obrir ex. 2]
  TRA
    Grup 3 - 9 subjectes - [Obrir ex. 1]

Franja 2
  DMT
    Grup 4 - 12 subjectes - 1 avis - [Obrir ex. 1]

Fora de programa
  TUM
    Grup 7 - 5 subjectes - [Obrir]
```

Cada fila/context ha de poder mostrar:

- franja;
- aparell;
- unitat/grup;
- nombre de subjectes;
- exercicis disponibles;
- avisos pendents, si es pot calcular sense cost excessiu;
- estat de puntuacio, si ja hi ha endpoint o metrica barata;
- accio `Obrir`.

## Opcio Expandir

La vista de resultats pot oferir una accio `Expandir` quan els filtres encara inclouen `Tots`, pero el nombre de contextos es raonable o es pot carregar per blocs.

Regles:

- `Tots` continua mostrant resum per defecte.
- `Expandir` es una accio explicita de l'usuari.
- Cada context expandit es carrega amb l'endpoint lazy de taula existent.
- Les taules expandides son editables i mantenen el mateix contracte de `score_key`, guardat parcial i polling.
- No s'ha de crear una taula gegant barrejant contextos; cal renderitzar blocs independents.
- Si hi ha molts contextos, carregar un primer bloc i oferir `Carrega mes`.
- Multimedia continua lazy: comptadors/presencia poden carregar amb la taula, pero fitxers i reproduccio no s'han de pre-carregar massivament.

Exemples:

- `Franja concreta + Aparell concret + Grup = Tots + Exercici concret`
  - `Expandir` obre les unitats d'aquella franja/aparell/exercici.

- `Franja concreta + Aparell concret + Grup concret + Exercici = Tots`
  - `Expandir` obre els exercicis d'aquella unitat.

- `Franja = Totes + Aparell concret`
  - `Expandir` pot carregar per blocs, agrupant per franja.

Punts tecnics sensibles:

- Cada taula expandida necessita el seu payload local de subjectes.
- El polling ha de considerar visibles les taules dins el panell expandit.
- Abans de substituir resum/expandit/taula concreta cal fer flush dels saves pendents visibles.
- Els outputs d'un `score_key` s'han d'actualitzar en totes les taules visibles on aparegui.

## Paginacio Semi-Intel-ligent

Quan algun filtre esta a `Tots`, el panell pot generar molts contextos. Aixo no ha de bloquejar la pantalla ni provocar una carrega massiva.

Regla base:

> `Tots` vol dir mostrar tots els contextos com a resum incremental, no carregar totes les taules ni tots els inputs.

Llindars recomanats:

- menys de 50 contextos: mostrar tots els resultats agrupats.
- entre 50 i 200 contextos: mostrar resultats agrupats amb "Carrega mes" per grup visual.
- mes de 200 contextos: usar endpoint paginat o cursor.

La paginacio ha de ser contextual, no nomes una pagina global plana.

Eix recomanat segons filtres:

- `Franja = Totes`, `Aparell concret`
  - agrupar i paginar per franja.

- `Aparell = Tots`, `Franja concreta`
  - agrupar i paginar per aparell.

- `Franja = Totes`, `Aparell = Tots`
  - primer agrupar per franja, despres per aparell.

- `Grup/unitat = Tots`, amb aparell concret
  - agrupar per franja i paginar unitats.

- `Subjecte concret`
  - normalment no cal paginar; els contextos haurien de ser pocs.

- `Avisos = Amb avisos`
  - paginar per severitat, subjecte o franja segons el contracte disponible.

UI recomanada:

- preferir boto `Carrega mes` dins cada agrupacio;
- evitar paginacio global classica si barreja franges i aparells sense estructura;
- mostrar comptadors totals quan es pugui:
  - `Mostrant 25 de 83 contextos`;
  - `Carrega 25 mes`;
  - `DMT - 12 unitats pendents de mostrar`.

Endpoint opcional:

`GET /competicio/<pk>/scoring/notes/contexts/?franja=all&app=10&unit=all&page_size=25&cursor=...&group_by=franja`

Resposta orientativa:

```json
{
  "ok": true,
  "contexts": [],
  "count": 25,
  "total": 83,
  "next_cursor": "opaque-token",
  "group_by": "franja"
}
```

Aquest endpoint no ha de retornar scores complets ni multimedia. Nomes contextos i comptadors lleugers.

## Vista De Taula Editable

La taula editable continua sent contextual.

Per obrir-la cal un context:

```json
{
  "franja_id": 1,
  "comp_aparell_id": 10,
  "unit_key": "unit:3+4",
  "exercici": 1
}
```

L'accio `Obrir` ha de:

1. guardar el context a `selectedContext`;
2. posar `view = "table"`;
3. cridar `notes_table`;
4. renderitzar la taula;
5. enfocar fila si el filtre subjecte esta actiu;
6. mantenir visible o recuperable la vista de resultats.

## Cerca

La cerca no ha d'obrir automaticament el primer resultat.

Comportament correcte:

1. L'usuari escriu un nom, grup o aparell.
2. El backend retorna resultats amb contextos.
3. La UI aplica el resultat com a filtre o mostra els contextos disponibles.
4. L'usuari clica `Obrir` en un context concret.

Exemple:

```text
Anna Exemple
  Franja 1 - DMT - Grup 3 - Ex 1
  Franja 2 - TRA - Grup 3 - Ex 1
  Fora de programa - TUM - Grup 3
```

Buscar una inscripcio ha d'activar `filters.subject`, no forcar franja/aparell/unitat.

Buscar un aparell pot posar `filters.appId`.

Buscar un grup pot posar `filters.unitKey` o un filtre de grup semantic si la unitat pot ser multi-grup.

## Contracte Backend Recomanat

### `notes_manifest`

Ha de continuar retornant:

- franges;
- aparells;
- unitats;
- unitats fora de programa;
- metadades lleugeres.

No ha de retornar scores complets.

### `notes_search`

Ruta:

`GET /competicio/<pk>/scoring/notes/search/?q=...&limit=20`

Resposta recomanada:

```json
{
  "ok": true,
  "query": "anna",
  "results": [
    {
      "id": "inscripcio:123",
      "kind": "subject",
      "subject_kind": "inscripcio",
      "subject_id": 123,
      "name": "Anna Exemple",
      "meta": "Club - Categoria",
      "subject": {
        "id": 123,
        "subject_id": 123,
        "subject_kind": "inscripcio",
        "name": "Anna Exemple",
        "group": 7,
        "allowed_app_ids": [10, 11],
        "meta": "Club - Categoria"
      },
      "contexts": [
        {
          "franja_id": 1,
          "franja_label": "Franja 1",
          "comp_aparell_id": 10,
          "app_label": "DMT",
          "unit_key": "7",
          "unit_identity": "franja:1|10|7",
          "unit_label": "Grup 7",
          "exercicis": [1, 2],
          "label": "Franja 1 - DMT - Grup 7"
        }
      ]
    }
  ],
  "count": 1
}
```

Notes:

- Query minima: 2 caracters.
- Limit maxim: 50.
- No retornar scores complets.
- No carregar multimedia.
- Construir contextos des de `build_notes_units_context()`.
- Respectar `competition_view(..., "scoring.view")`.

### Endpoint Opcional `notes_contexts`

Si el frontend necessita recalcular resultats filtrats sense portar molta logica al client:

`GET /competicio/<pk>/scoring/notes/contexts/?franja=all&app=all&unit=all&subject_kind=inscripcio&subject_id=123&warnings=all`

Resposta:

```json
{
  "ok": true,
  "contexts": [
    {
      "franja_id": 1,
      "franja_label": "Franja 1",
      "comp_aparell_id": 10,
      "app_label": "DMT",
      "unit_key": "7",
      "unit_label": "Grup 7",
      "exercicis": [1, 2],
      "count": 12,
      "warning_count": 1
    }
  ]
}
```

Aquest endpoint no es imprescindible si `manifest` ja dona prou dades i el client pot filtrar localment.

### `notes_table`

No canviar el contracte principal.

Continua sent:

`GET /competicio/<pk>/scoring/notes/table/?franja_id=...&comp_aparell_id=...&unit_key=...&exercici=...`

Aquest endpoint carrega la taula concreta.

### `notes_warnings`

Millorar si cal:

- afegir `page` o `cursor`;
- afegir filtres:
  - franja;
  - app;
  - unit;
  - subjecte;
  - grup.
- retornar contexts navegables igual que `notes_search`.

## Canvis Frontend Recomanats

### 1. Substituir Selectors En Cascada Per Filtres

Fitxer probable:

`competicions_trampoli/templates/scoring/notes/scripts/_85_lazy_panel.js.html`

Canviar:

- `unitsForSelectedFranja()`
- `unitsForSelectedApp()`
- `selectFirstAvailableUnit()`
- `populateLazyFranjaOptions()`
- `populateLazyAppOptions()`
- `populateLazyUnitOptions()`

Per funcions basades en filtres:

- `allContextsFromManifest()`
- `contextMatchesFilters(context, filters)`
- `filteredContexts()`
- `populateFilterOptions()`
- `renderSummaryResults()`
- `openNotesContext(context)`

### 2. Opcio `Tots` A Tots Els Selectors

Selectors:

- Franja:
  - `Totes`
  - cada franja
  - `Fora de programa`

- Aparell:
  - `Tots`
  - cada aparell

- Grup/unitat:
  - `Tots`
  - unitats que coincideixen amb la resta de filtres

- Exercici:
  - `Tots`
  - exercicis disponibles

Important:

- Si l'usuari tria `Tots`, no seleccionar automaticament el primer valor.
- Si el resultat filtrat conte multiples contextos, mostrar resum.
- Si conte un unic context i un exercici concret, es pot obrir taula o mostrar boto clar `Obrir taula`.

### 3. Renderitzar Resum En Lloc De Taula Quan Hi Ha Multiples Contextos

Afegir un contenidor:

```html
<div data-notes-results-panel="1"></div>
```

Comportament:

- `view = "summary"` mostra resultats i amaga la taula.
- `view = "table"` mostra la taula i conserva un cami de retorn al resum.

### 4. Unificar Obertura De Context

Crear una funcio unica:

```js
async function openNotesContext(context, opts = {}) {
  NOTES_STATE.selectedContext = context;
  NOTES_STATE.view = "table";
  // set selected ids for compatibility with code existing
  // call notes_table
  // focus subject row if opts.subject exists
}
```

Aquesta funcio s'ha d'usar des de:

- resultats de cerca;
- resultats filtrats;
- avisos globals;
- programa/franja;
- botons `Obrir`.

### 5. Cerca Com A Filtre

Quan l'usuari selecciona un resultat de cerca:

- si es subjecte: posar `filters.subject`;
- si es aparell: posar `filters.appId`;
- si es grup/unitat: posar filtre de grup/unitat;
- recalcular `filteredContexts()`;
- renderitzar resum;
- no obrir `contexts[0]`.

### 6. Avisos Com A Filtre O Vista De Resultats

No tractar `Tots els avisos` com un filtre de files de la taula activa.

Opcio simple:

- selector `Avisos`: `Tots`, `Amb avisos`;
- si `Amb avisos`, carregar/usar `notes_warnings`;
- mostrar resultats agrupats amb botons `Obrir`.

## Polling I Elements Sensibles

### Polling

No canviar `scoring_updates`.

Requisits:

- El polling continua actualitzant `SCORES`.
- Si hi ha una taula oberta i rep update, es re-renderitza com ara.
- Si el context no esta carregat, l'update queda al store i es veura quan s'obri.
- La vista resum no ha de dependre de tenir scores complets carregats.
- La paginacio de resultats no ha de subscriure ni renderitzar inputs de contextos no oberts.
- Els contextos resumits poden mostrar comptadors aproximats o calculats per endpoint, pero no han de requerir polling fi de cada score.

### Focus Del Frontend

Separar tres coses:

- focus d'input editable;
- focus visual de fila;
- filtre de subjecte.

Risc:

- canviar de context mentre hi ha una cel-la editant pot perdre canvis pendents.

Mesura:

- abans d'obrir un altre context, fer servir el mecanisme existent de `focusout`/flush si existeix;
- si hi ha edicio pendent, no destruir la taula sense guardar o avisar;
- no reutilitzar "subject focus" com si fos focus DOM.

### Guardat Parcial

No tocar `scoring_save_partial`.

La taula continua enviant:

- `subject_kind`;
- `subject_id`;
- `comp_aparell_id`;
- `exercici`;
- `inputs_patch`.

Regla obligatoria:

> La vista amb filtres `Tots` no es editable.

Nomes la vista de taula concreta crea inputs i escriu notes. Aixo evita:

- milers d'inputs al DOM;
- guardats parcials massius;
- conflictes de focus;
- re-renderitzats per polling sobre taules no visibles;
- carregues innecessaries de scores.

El resum pot tenir accions administratives no destructives, com `Obrir`, `Veure avisos` o `Carrega mes`, pero no camps de puntuacio editables.

### Multimedia

No carregar multimedia a la cerca ni al resum.

Permes:

- comptadors de multimedia;
- presencia de video;
- badges lleugers.

No permes:

- carregar fitxers audio/video fins que l'usuari obri drawer o reproduccio.

### Team Subjects

Mantenir suport per:

- `subject_kind = "team_unit"`;
- unitats `team_series`;
- unitats `team_rotation_cell`;
- unitats fora de programa `team_bucket`.

## Fases D'Implementacio

### Fase 1. Tests Del Problema Actual

Afegir tests abans de modificar UI.

Backend:

- una inscripcio amb contextos en mes d'un aparell retorna tots els contextos.
- cerca per aparell retorna unitats de diverses franges.
- cerca per grup retorna contextos de diverses franges/aparells.

Frontend/browser:

- cercar un subjecte no obre automaticament el primer context.
- canviar aparell amb subjecte filtrat no canvia a un grup arbitrari.
- `Franja = Totes` i `Aparell = DMT` mostra multiples franges.

### Fase 2. Construir Contextos Filtrables

Implementar al client o backend una estructura normalitzada:

```js
{
  franjaId,
  franjaLabel,
  appId,
  appLabel,
  unitKey,
  unitLabel,
  memberKeys,
  subjectKind,
  count,
  exercicis,
  isOutOfProgram
}
```

Font principal:

- `notes_manifest.units`
- `notes_manifest.out_of_program_units`
- `notes_manifest.apps`

### Fase 3. Filtres Amb `Tots`

Canviar selectors per tenir `Tots`.

Els canvis de filtre han de:

1. actualitzar `NOTES_STATE.filters`;
2. recalcular `filteredContexts()`;
3. mostrar resum si hi ha multiples contextos;
4. no obrir taula automaticament.

### Fase 4. Vista De Resultats Agrupats

Crear UI de resum:

- agrupacio per franja;
- dins, aparell;
- dins, unitat;
- botons per exercici/context.

La taula editable passa a ser una vista secundaria oberta des d'un context.

### Fase 5. Cerca Com A Filtre

Modificar cerca:

- mostrar resultats;
- seleccionar resultat aplica filtre;
- mostrar contextos;
- no obrir primer context automaticament.

### Fase 6. Avisos Com A Resultats

Separar avisos globals de `rowFilter`.

Implementar:

- `Avisos = Amb avisos`;
- carregar `notes_warnings`;
- mostrar resultats navegables;
- `Obrir` usa `openNotesContext`.

### Fase 7. Neteja Lazy Real

Quan la nova navegacio funcioni:

- reduir payload inicial;
- eliminar dependencia de `scores` globals inicials si es possible;
- mantenir fallback temporal si cal.

## Tests Minims D'Acceptacio

Backend:

- `notes_search` retorna multiples contextos per subjecte.
- `notes_search` retorna resultats per grup.
- `notes_search` retorna resultats per aparell.
- Query curta retorna llista buida.
- Limits capats.
- Access control amb `scoring.view`.

Frontend:

- `Franja = Totes`, `Aparell = DMT` mostra DMT a totes les franges.
- `Subjecte = Anna`, `Aparell = Tots` mostra tots els contextos d'Anna.
- `Grup = 3`, `Franja = Totes` mostra totes les aparicions del grup.
- Cercar subjecte no obre automaticament cap taula.
- Clicar `Obrir` en un context obre la taula correcta.
- Tornar al resum conserva filtres.
- Avisos globals obren el context correcte.

Regressio:

- Guardat parcial funciona despres d'obrir context des del resum.
- Polling incremental continua funcionant.
- Multimedia continua lazy.
- Team subjects continuen funcionant.
- Cel-les multi-grup continuen sent una sola unitat.

## Criteris D'Acceptacio UX

El canvi es considera correcte quan:

- els selectors tenen `Tots`;
- els selectors no es resetegen agressivament entre ells;
- veure multiples franges/aparells/grups es possible sense entrar manualment context per context;
- la cerca actua com a filtre o selector de resultats, no com a salt automatic al primer context;
- la taula editable continua existint, pero nomes quan s'obre un context concret;
- el panell deixa clar quan s'esta veient resum i quan s'esta editant una taula.

## Advertiments Per A L'Agent

- No convertir el panell en una SPA completa.
- No canviar models de dades de puntuacio.
- No tocar `scoring_save_partial` excepte necessitat demostrada.
- No carregar multimedia des del resum o cerca.
- No eliminar el flux de franja concreta, perque continua sent util en directe.
- No fer refactor massiu abans de tenir tests del comportament nou.
- No assumir que una inscripcio pertany a un sol context.
- No assumir que `Tots` vol dir carregar totes les taules; vol dir mostrar resultats agrupats.

# Pla D'Implantacio De L'Avatar Assistent Per Pantalles De Competicions

## Objectiu

Aquest document defineix el patró de treball per aplicar l'avatar assistent d'IA Score a pantalles del programa de competicions. Ha de servir a futurs agents i subagents que no tinguin context de la conversa original.

L'objectiu no és posar una mascota decorativa a cada pantalla. L'avatar ha de funcionar com un assistent contextual:

- apareix plegat per defecte;
- es pot obrir manualment;
- mostra explicacions curtes en vinyetes;
- pot obrir-se directament en un tema concret quan l'usuari prem un botó d'ajuda;
- manté un estil visual i funcional coherent a tot el programa;
- no tapa la feina principal ni ocupa espai d'acció principal.

## Estat Base Ja Implementat

La primera pantalla implantada és el home de competicions.

Fitxers de referència:

- `competicions_trampoli/services/avatar/home/messages.py`
- `competicions_trampoli/views/competition/competicio.py`
- `competicions_trampoli/templates/components/avatar_helper.html`
- `competicions_trampoli/templates/competicio/_dashboard_home.html`

El component compartit és:

```text
competicions_trampoli/templates/components/avatar_helper.html
```

Aquest component ja suporta:

- estat plegat per defecte;
- obertura amb el logo/botó de l'avatar;
- vinyetes amb `Anterior` i `Següent`;
- selecció de tema via `data-avatar-topic`;
- alternança d'imatges d'avatar per pas;
- accions opcionals dins la bombolla;
- tancament complet quan es prem la `x` o el botó de plegar;
- bombolla arrossegable;
- persistència de posició de la bombolla amb `localStorage`.

Els subagents han de reutilitzar aquest component. No han de crear un component nou per pantalla.

## Principis De Disseny

1. Un sol avatar per pantalla.

No afegir múltiples instàncies del component en una mateixa pantalla. Si hi ha molts punts d'ajuda, tots han d'obrir el mateix avatar amb un `topic` diferent.

2. Plegat per defecte.

L'avatar no ha d'aparèixer obert automàticament excepte si una pantalla futura ho justifica explícitament. El patró normal és:

```django
{% include "components/avatar_helper.html" with avatar_messages=avatar_messages avatar_initial_topic=avatar_initial_topic position="left" state="closed" %}
```

3. Ajuda sota demanda.

Els botons `?` han de ser petits, secundaris i contextuals. No han d'ocupar el lloc visual d'una acció principal.

4. Explicacions curtes.

Cada pas ha de tenir una idea clara. Evitar paràgrafs llargs, manuals complets o text massa tècnic. L'avatar orienta, no substitueix la documentació.

5. Context abans que ordre fix.

El tema `welcome` serveix per una introducció general. La resta de temes s'han d'obrir directament des dels punts d'ajuda de la UI.

6. No duplicar explicacions d'una pantalla en una altra.

Si una ajuda correspon a una UI dedicada, el text ha de viure al servei d'avatar d'aquella UI, no al home ni a una pantalla anterior.

Exemple ja decidit:

- el home no explica en detall `Aparells globals`;
- el home no explica en detall `Plantilles classificacio`;
- aquestes explicacions han d'anar a les pantalles dedicades.

## Contracte De Missatges

Cada pantalla ha de definir un catàleg `AVATAR_MESSAGES` en un mòdul Python dins `services/avatar`.

Exemple de ruta:

```text
competicions_trampoli/services/avatar/<domini>/<pantalla>.py
```

Exemples:

```text
competicions_trampoli/services/avatar/home/messages.py
competicions_trampoli/services/avatar/competition/overview.py
competicions_trampoli/services/avatar/inscripcions/overview.py
competicions_trampoli/services/avatar/inscripcions/series_workspace.py
```

Forma recomanada:

```python
EXPLAINING_AVATARS = [
    "avatar/explaining/explaining_2.png",
    "avatar/explaining/explaining_3.png",
    "avatar/explaining/explaining_4.png",
    "avatar/explaining/explaining_5.png",
]


AVATAR_MESSAGES = {
    "welcome": {
        "id": "welcome",
        "title": "Titol curt",
        "avatar": "avatar/greeting_2.png",
        "avatars": [
            "avatar/greeting_2.png",
            *EXPLAINING_AVATARS,
        ],
        "variant": "welcome",
        "steps": [
            {"text": "Primera idea."},
            {"text": "Segona idea."},
        ],
        "actions": [],
    },
    "topic_contextual": {
        "id": "topic_contextual",
        "title": "Tema concret",
        "avatar": EXPLAINING_AVATARS[0],
        "avatars": EXPLAINING_AVATARS,
        "variant": "info",
        "steps": [
            {"text": "Explicacio contextual curta."},
        ],
        "actions": [],
    },
}
```

### Camps

`id`

Ha de coincidir amb la clau del diccionari. Es fa servir per obrir el tema des de `data-avatar-topic`.

`title`

Títol curt de la bombolla. Ha de ser específic del tema.

`avatar`

Imatge fallback si no hi ha `avatars`.

`avatars`

Llista d'imatges que el component alterna per cada pas. Per explicacions normals, reutilitzar `avatar/explaining/explaining_2.png` fins a `explaining_5.png`.

`variant`

Etiqueta semàntica per futur estil o analítica. Valors recomanats:

- `welcome`
- `info`
- `action`
- `warning`
- `success`

No inventar variants visuals noves sense necessitat.

`steps`

Llista de vinyetes. Cada element ha de tenir com a mínim `text`.

`actions`

Llista opcional d'accions dins la bombolla. Fer-ne un ús moderat. Les accions poden ser útils quan la vinyeta explica una acció directa i hi ha un enllaç clar a la pantalla.

## Integracio Amb Vista Django

Cada vista que mostri l'avatar ha de passar el catàleg al context.

Patró:

```python
from ...services.avatar.<domini>.<pantalla> import AVATAR_MESSAGES as <SCREEN>_AVATAR_MESSAGES


ctx["avatar_messages"] = <SCREEN>_AVATAR_MESSAGES
ctx["avatar_initial_topic"] = "welcome"
```

Si la pantalla usa `ListView`, `DetailView` o un mixin, afegir-ho a `get_context_data`.

Si la pantalla és una function view, afegir-ho al diccionari `ctx`.

No importar missatges d'una pantalla que no correspon. Cada pantalla ha de tenir el seu catàleg o reutilitzar un catàleg compartit només si realment representa el mateix flux.

## Integracio Amb Template

Incloure el component una sola vegada dins la pantalla, preferiblement prop del títol o shell principal.

Patró:

```django
{% include "components/avatar_helper.html" with avatar_messages=avatar_messages avatar_initial_topic=avatar_initial_topic position="left" state="closed" %}
```

Després, qualsevol botó d'ajuda de la pantalla pot obrir un tema:

```html
<button
  class="... classe local ..."
  type="button"
  data-avatar-topic="topic_contextual"
  aria-label="Ajuda sobre ..."
  title="Ajuda sobre ...">
  ?
</button>
```

No posar botons interactius dins d'un `<a>`. Si cal posar ajuda sobre una card clicable, crear un wrapper:

```html
<div class="card-shell">
  <button type="button" data-avatar-topic="create_competition">?</button>
  <a class="card" href="...">...</a>
</div>
```

## Col.locacio Dels Botons D'Ajuda

Els botons `?` han d'aparèixer només on aporten valor.

Ubicacions recomanades:

- al costat del títol principal per obrir `welcome`;
- a la cantonada d'una secció complexa;
- sobre una card dedicada a una acció important;
- al costat d'un panell o workspace quan l'usuari necessita entendre aquell context;
- prop d'un conjunt de filtres o controls si aquests tenen comportament no evident.

Ubicacions a evitar:

- al costat de cada botó d'una toolbar simple;
- dins d'un enllaç;
- repetit al costat de diverses accions que ja tenen pantalles dedicades;
- ocupant espai principal dins del flux de treball;
- enganxat a icones o botons que puguin confondre si l'acció és ajuda o navegació.

Mida visual recomanada:

- petit, circular, secundari;
- no més gran que la iconografia auxiliar de la pantalla;
- ha de tenir `aria-label` i `title`.

## Redaccio Dels Textos

To:

- clar;
- directe;
- acompanyant;
- orientat a l'acció;
- sense tecnicismes interns si no són visibles per l'usuari.

Evitar:

- frases massa llargues;
- repetir el nom complet d'IA Score a cada pas;
- explicar detalls que pertanyen a una altra pantalla;
- prometre automatismes que encara no existeixen;
- usar l'avatar com a manual exhaustiu.

Longitud recomanada:

- 1 idea per `step`;
- 1 o 2 frases curtes per `step`;
- 2 a 5 `steps` per tema;
- `welcome` pot tenir 3 o 4 passos màxim.

## Accions De La Bombolla

El component actual suporta accions com:

- `create_competition`
- `open_competition`

Abans d'afegir noves accions, el subagent ha de comprovar si realment cal una acció dins la bombolla. En molts casos és millor que el botó `?` només expliqui el context i que l'usuari faci servir els controls visibles de la pantalla.

Si cal afegir una acció nova:

1. Afegir l'entrada a `actions` del tema.
2. Implementar el comportament al JS compartit de `avatar_helper.html`, només si és genèric i reutilitzable.
3. Si l'acció és específica d'una pantalla, preferir un selector `data-avatar-action="..."` al template i resoldre'l de manera declarativa.
4. Validar que l'acció no aparegui si l'usuari no té permís o si l'enllaç no existeix.

No afegir accions que facin canvis destructius o modifiquin dades sense confirmació explícita.

## Com Aplicar L'Avatar A Una Pantalla Nova

### Pas 1. Llegir La Pantalla

Abans d'escriure textos, revisar:

- vista Django que renderitza la pantalla;
- template principal i partials;
- accions principals;
- estats buits;
- filtres;
- workspace o panells;
- permisos;
- si hi ha ja textos d'ajuda o manuals existents.

### Pas 2. Definir Temes

Crear una llista curta de temes. Exemple:

```text
welcome
filters
main_workspace
empty_state
bulk_actions
import_flow
review_panel
```

No crear un tema per cada botó. Crear temes per zones o fluxos.

### Pas 3. Escriure `AVATAR_MESSAGES`

Crear o actualitzar:

```text
competicions_trampoli/services/avatar/<domini>/<pantalla>.py
```

Fer servir `EXPLAINING_AVATARS` i el contracte definit en aquest document.

### Pas 4. Connectar La Vista

Importar el catàleg de missatges i afegir:

```python
ctx["avatar_messages"] = ...
ctx["avatar_initial_topic"] = "welcome"
```

### Pas 5. Incloure El Component

Afegir el component al template de la pantalla:

```django
{% include "components/avatar_helper.html" with avatar_messages=avatar_messages avatar_initial_topic=avatar_initial_topic position="left" state="closed" %}
```

### Pas 6. Afegir Punts D'Ajuda

Afegir només els `?` necessaris.

Cada `data-avatar-topic` ha d'existir al catàleg.

Exemple:

```html
<button type="button" data-avatar-topic="filters" aria-label="Ajuda sobre filtres" title="Ajuda sobre filtres">?</button>
```

### Pas 7. Validar

Executar validacions mínimes:

```powershell
py -3 -m compileall competicions_trampoli\services\avatar\<domini>\<pantalla>.py
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py shell -c "from django.template.loader import get_template; get_template('<template_principal>'); print('template ok')"
git diff --check -- <fitxers_modificats>
```

Si hi ha tests específics de la pantalla, executar-los també.

## Checklist D'Acceptacio

Una pantalla es considera correctament adaptada quan:

- el component `avatar_helper.html` s'inclou una sola vegada;
- l'avatar apareix plegat d'entrada;
- el botó del títol o context principal obre `welcome`;
- cada `?` obre un tema concret i existent;
- no hi ha `?` sobrants al costat d'accions trivials;
- cap botó `?` està dins d'un `<a>`;
- la bombolla no queda fixa tapant el flux principal sense opció de moure-la;
- tancar la bombolla plega tot l'avatar;
- plegar l'avatar no deixa cap vinyeta flotant;
- els textos són curts i específics;
- no s'expliquen pantalles dedicades des d'una pantalla que només les enllaça;
- `manage.py check` passa;
- els templates modificats carreguen;
- `git diff --check` no mostra errors.

## Write Scopes Recomanats Per Subagents

Per treballar en paral.lel, repartir per pantalla o domini. Evitar que dos subagents modifiquin el mateix template o el mateix fitxer de missatges alhora.

### Subagent A. Pantalla Home O Overview D'Un Domini

Scope:

- `competicions_trampoli/services/avatar/<domini>/overview.py`
- vista Django corresponent;
- template principal o partial d'overview.

Responsabilitat:

- definir `welcome`;
- afegir ajuda a títol principal;
- afegir ajuda a seccions grans;
- evitar explicar detalls que pertanyen a subpantalles.

### Subagent B. Workspace Operatiu

Scope:

- `competicions_trampoli/services/avatar/<domini>/<workspace>.py`
- partials del workspace;
- scripts només si cal marcar punts `data-avatar-topic`.

Responsabilitat:

- explicar zones de treball;
- explicar estats buits;
- explicar accions agrupades o fluxos;
- no crear ajuda per cada microbotó.

### Subagent C. Component Compartit

Scope:

- `competicions_trampoli/templates/components/avatar_helper.html`

Responsabilitat:

- només canvis transversals;
- compatibilitat amb totes les pantalles;
- no introduir comportaments específics d'una pantalla dins el component si es pot resoldre amb `data-*`.

Aquest subagent no ha de tocar catàlegs de missatges de pantalles concretes excepte per adaptar contractes trencats.

### Subagent D. Repassada UX I Textos

Scope:

- fitxers de `services/avatar/**`;
- petits ajustos de `data-avatar-topic` als templates si hi ha desalineacions.

Responsabilitat:

- coherència de to;
- evitar duplicació;
- assegurar que els temes tenen noms clars;
- comprovar que els textos no expliquen funcionalitats inexistents.

## Anti-Patrons

No fer:

- crear un component d'avatar nou per pantalla;
- posar l'avatar obert per defecte sense motiu;
- posar botons `?` grans que competeixin amb accions principals;
- posar botons interactius dins enllaços;
- obrir sempre el primer tema quan l'usuari demana ajuda contextual;
- escriure manuals llargs dins `steps`;
- barrejar textos de pantalles diferents en un sol catàleg;
- afegir accions que naveguen a llocs sense comprovar permisos;
- tocar `avatar_helper.html` per un cas local que es pot resoldre al template.

## Patrons De Noms

Temes recomanats:

```text
welcome
filters
empty_state
main_workspace
side_panel
detail_panel
import_flow
review_flow
bulk_actions
media_matching
series_workspace
teams_workspace
groups_workspace
```

Evitar noms massa genèrics com:

```text
help
info
button_1
section
text
```

## Notes Sobre Accessibilitat

Cada botó d'ajuda ha de tenir:

```html
aria-label="Ajuda sobre ..."
title="Ajuda sobre ..."
```

El component ja usa `aria-live="polite"` a la bombolla. No canviar-ho a `assertive` tret que es tracti d'una alerta crítica.

Els botons han de ser navegables amb teclat. No substituir-los per `<span>` clicables.

## Notes Sobre Persistencia Visual

La posició de la bombolla és global i es guarda al navegador. Això és intencionat: si un usuari la recol.loca perquè en la seva pantalla tapa contingut, la posició es manté en plegar, desplegar i refrescar.

No guardar posicions per pantalla tret que hi hagi una necessitat clara. Si en el futur cal fer-ho, afegir un atribut al component, per exemple:

```html
data-avatar-storage-scope="inscripcions-series"
```

i adaptar el `storageKey()` del component de manera retrocompatible.

## Ordre Recomanat D'Implantacio

1. Home de competicions. Ja implantat.
2. Overview de competicio.
3. Inscripcions overview.
4. Workspaces d'inscripcions: equips, grups, series i multimedia.
5. Aparells globals.
6. Plantilles de classificacio.
7. Fases i rotacions.
8. Classificacions.
9. Notes i portal de jutges, amb molta cura per no interferir en fluxos operatius.

En pantalles d'operació en directe, l'avatar ha de ser més discret que en pantalles de configuració.

## Validacio Manual Recomanada

Per cada pantalla:

1. Obrir la pantalla amb l'avatar plegat.
2. Obrir l'avatar des del control principal.
3. Confirmar que surt `welcome`.
4. Obrir cada `?` contextual.
5. Navegar `Anterior` i `Següent`.
6. Arrossegar la bombolla.
7. Plegar l'avatar i tornar-lo a obrir.
8. Refrescar la pàgina i confirmar que la posició es manté.
9. Provar una amplada mòbil o estreta.
10. Confirmar que cap `?` tapa accions principals.

## Criteri Final

L'avatar ha d'ajudar l'usuari a entendre on és i què pot fer ara. Si un text no respon a aquesta pregunta, probablement no ha d'estar a l'avatar d'aquella pantalla.

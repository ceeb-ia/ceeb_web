# Guia frontend - Competicions

Aquest document defineix criteris senzills per donar coherencia visual al programa de competicions. No vol ser un design system complet, sino una referencia practica per evitar que cada pantalla resolgui botons, colors i superficies d'una manera diferent.

## Principis

- El programa es una eina interna de gestio: ha de ser clar, dens, llegible i rapid d'escanejar.
- El color serveix per orientar l'usuari, no per decorar tota la pantalla.
- Les seccions principals han de ser reconeixibles a traves de botons, capcaleres i petits accents.
- Les cards s'han d'usar nomes quan agrupen contingut real o elements repetits. No han de ser la resposta per defecte a qualsevol bloc.
- Les accions de navegacio entre grans blocs han de tenir un llenguatge propi, diferent dels botons d'accio com guardar, exportar o eliminar.

## Paleta de seccions

| Seccio | Base | Fons suau | Border | Text |
| --- | --- | --- | --- | --- |
| Inscripcions | `#0F766E` | `#E6FFFB` | `#99F6E4` | `#134E4A` |
| Aparells i Fases | `#2563EB` | `#EFF6FF` | `#BFDBFE` | `#1E3A8A` |
| Rotacions | `#B45309` | `#FFF7ED` | `#FED7AA` | `#7C2D12` |
| Classificacions | `#9F1239` | `#FFF1F2` | `#FECDD3` | `#881337` |
| Notes i QRs | `#A16207` | `#FFFBEB` | `#FDE68A` | `#78350F` |

## Neutres comuns

```css
--app-bg: #F8FAFC;
--surface: #FFFFFF;
--border: #E2E8F0;
--border-soft: #CBD5E1;
--text: #0F172A;
--muted: #64748B;
--text-muted: #94A3B8;
```

## Tipografia

El programa de competicions usa Inter com a tipografia principal:

```css
--competicio-font-family: "Inter", "Poppins", "Segoe UI", Arial, sans-serif;
```

Aquest valor no ha d'estar fixat al CSS. El defineix el context de Django a partir de settings i s'injecta com a variable CSS a `body.competicions-app`. Si no hi ha cap configuracio, el default es Inter amb fallback immediat a Poppins.

Cap pantalla fora de competicions ha d'usar `--competicio-font-family` ni classes visuals propies del programa.

Configuracio disponible:

```python
COMPETICIONS_APP_FONT_FAMILY = ""  # default intern: Inter
COMPETICIONS_APP_FONT_FOLDER = ""  # carpeta opcional dins static/fonts/
COMPETICIONS_APP_FONT_FILES = None  # opcional: {400: "Nom-Regular.woff2", ...}
```

Exemple per usar una font local a `competicions_trampoli/static/fonts/manrope/`:

```python
COMPETICIONS_APP_FONT_FAMILY = "Manrope"
COMPETICIONS_APP_FONT_FOLDER = "manrope"
```

Per defecte es busquen fitxers amb noms tipus `Manrope-Regular.otf`, `Manrope-SemiBold.otf`, `Manrope-Bold.otf`, etc. Si una carpeta nomes te alguns pesos, nomes es declararan els fitxers que existeixin.

## Botons de seccio

Els botons que porten a un bloc principal han d'usar `section-btn` i una variant tematica:

```html
<a class="btn btn-sm section-btn section-btn--inscripcions">Inscripcions</a>
<a class="btn btn-sm section-btn section-btn--fases">Aparells i fases</a>
<a class="btn btn-sm section-btn section-btn--rotacions">Rotacions</a>
<a class="btn btn-sm section-btn section-btn--classificacions">Classificacions</a>
<a class="btn btn-sm section-btn section-btn--notes">Notes i QRs</a>
```

Regles:

- Mantenir el text curt i literal.
- No usar aquests colors per accions generiques com `Guardar`, `Afegir`, `Eliminar` o `Exportar`.
- Si el boto obre un desplegable d'una seccio, tambe pot usar la variant de la seccio.
- El color ple queda reservat per accions primaries molt clares dins d'una pantalla, no per tota la navegacio.

## Botons operatius

Els botons operatius mantenen les classes Bootstrap existents, pero dins les superficies internes tenen una pell propia:

| Tipus | Classes | Us |
| --- | --- | --- |
| Primari | `btn-primary` | Accio principal immediata: guardar, crear, confirmar. |
| Secundari neutre | `btn-secondary`, `btn-outline-secondary` | Tornar, configurar, editar, accions auxiliars. |
| Operatiu blau | `btn-outline-primary` | Accions de treball no destructives: cercar, assignar, previsualitzar. |
| Exit / export | `btn-success`, `btn-outline-success` | Importar, exportar, aplicar amb resultat positiu. |
| Avis | `btn-warning`, `btn-outline-warning` | Accions que demanen atencio o afecten calculs/configuracio. |
| Informacio | `btn-info`, `btn-outline-info` | Ajuda, comprovacions, suport contextual. |
| Destructiu | `btn-danger`, `btn-outline-danger` | Eliminar, descartar, revocar. |
| Fort neutre | `btn-dark`, `btn-outline-dark` | Accions compactes o d'eina quan no encaixen en una categoria millor. |

Regles:

- No canviar el significat d'una classe per aconseguir un color concret.
- Preferir `outline-*` quan l'accio es secundaria.
- Reservar `btn-primary` per una sola accio principal per zona de pantalla, quan sigui possible.
- Les accions destructives sempre han de mantenir `danger`.

## Capcaleres de pantalla

Les pantalles principals haurien de seguir aquest patro:

- Titol de pantalla.
- Subtitol curt amb context de competicio o estat.
- A la dreta, botons de navegacio entre blocs amb `section-btn`.
- Accions operatives separades visualment quan sigui possible.

## Dock de navegacio

El programa de competicions pot mostrar un dock inferior persistent per moure's entre zones estables del programa:

- Competicions
- Inscripcions
- Aparells i fases
- Rotacions
- Classificacions
- Notes i QRs
- Configuracio

Regles:

- El dock es navegacio, no accions operatives.
- No hi van accions com importar, exportar, afegir, eliminar o guardar.
- Els items es mostren segons permisos i context de competicio.
- Els labels han de ser literals i llegibles; evitar abreviatures com `Insc.`, `Class.` o `Config.`.
- Les icones del dock han de sortir de `competicions_trampoli/static/dock/` i no de lletres generiques.
- L'estat actiu usa el color de la seccio.
- En pantalles publiques o sense chrome base no s'ha de mostrar.
- Pot conviure temporalment amb botons de capcalera fins que es decideixi quins accessos es poden retirar.

## Superficies

- `card-surface` es pot mantenir com a contenidor principal mentre no hi hagi un refactor global.
- Evitar posar cards dins de cards si no hi ha una relacio clara de contingut.
- Preferir taules, files i panells compactes per fluxos de gestio.

## Taula d'inscripcions

La taula d'inscripcions es una data grid funcional amb molt JavaScript associat. Les millores visuals han de respectar el DOM i els selectors existents:

- La capcalera d'Inscripcions ha de contenir context i accions propies de la pantalla, no navegacio cap a Notes, Rotacions, Configuracio o llista de competicions. Aquesta navegacio queda al dock.
- Inscripcions ha de tenir una identitat teal reconeixible, pero el teal ha de funcionar com a accent: titol, boto primari, focus, pestanya activa, badges puntuals i barres de grup. Evitar superficies grans tenyides.
- El layout base d'Inscripcions ha de ser neutre: fons `#F8FAFC`, superficies `#FFFFFF`, borders `#E2E8F0`, text principal `#0F172A` i text secundari `#64748B`.
- El panell de cerca pot agrupar cercador, estat de resultats i opcions de treball com l'ordre de competicio, sempre mantenint ids funcionals (`search-btn`, `clear-search-btn`, `competition-order-tail-toggle`).
- No canviar ids, `data-*`, classes funcionals ni estructura de files/cel.les sense revisar els scripts.
- Mantenir les classes `group-band-0` a `group-band-7`; els colors de grup s'han d'aplicar al header de grup i a la barra lateral, no a totes les files internes.
- Les pestanyes de grup han de ser netes: activa amb text i linia inferior teal, inactives en gris, comptadors com badges neutres. Han de mantenir `nav-tabs`, `nav-link`, ids, `aria-*` i lazy loading intactes.
- Les files de grup han de llegir-se com capcaleres de seccio: fons molt suau, franja d'accent, nom complet, recompte discret i menu de tres punts.
- La taula ha de prioritzar lectura de dades: capcalera sticky, files blanques, separadors fins, hover `#F8FAFC` i menys sensacio de quadricula.
- Les columnes `Grup` i `Aparells` han de ser compactes: `Grup` pot tallar-se dins la columna, pero la capcalera de grup sempre ha de mostrar el nom complet.
- A `Aparells`, el resum `Competeix...` ha de quedar visible sencer i el selector multiple ha de quedar dins un desplegable per usar-lo nomes quan calgui editar.
- La columna `Equip` s'ha de llegir com `Equip actiu`: mostra l'equip del context seleccionat, el context a sota i un indicador discret quan la inscripcio tambe te equip en altres contextos.
- La columna `Fitxers` no ha de mostrar el control natiu de fitxer com a element principal. Cal mantenir `.js-media-upload-input` i `.js-media-upload-btn`, pero presentar-los amb controls compactes i discrets.
- Les accions de fila han de mostrar nomes una accio principal discreta i un menu `...` per accions secundaries o destructives.
- El panell lateral d'accions d'Inscripcions s'ha d'obrir amb una nansa lateral compacta, no amb un boto flotant llarg. La nansa ha de conservar `id`, `aria-controls` i `aria-expanded`.
- Els controls de fila, drag handles, filtres, ordenacio, media i aparells es poden polir visualment, pero s'han de conservar els selectors funcionals (`js-*`, `data-*`) i els elements interactius que consumeix el JavaScript.

## Coses a evitar

- Massa tags o badges decoratius.
- Paletes dominades per un sol color en tota la pantalla.
- Botons Bootstrap generics per navegar entre blocs principals.
- Hero sections o composicions de landing page dins del programa intern.

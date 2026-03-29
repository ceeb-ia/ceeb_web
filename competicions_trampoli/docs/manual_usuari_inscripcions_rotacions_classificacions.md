# Manual d'usuari provisional

## Objectiu d'aquest document

Aquest document explica, amb llenguatge d'usuari i sense entrar en detalls tecnics, com funciona el bloc de treball de:

1. Inscripcions
2. Rotacions
3. Classificacions

A mes, incorpora un capitol previ sobre aparells i puntuacio, perque aquesta configuracio condiciona com es recullen les notes i com es podran construir les classificacions.

L'ordre segueix el flux de treball habitual d'una competicio: primer es defineixen els aparells i la seva logica de puntuacio, despres es preparen les persones inscrites, tot seguit es programa on competiran i finalment es defineix com es mostraran els resultats.

## Abast

Aquest manual esta pensat per a persones d'organitzacio, coordinacio o secretaria tecnica que necessiten entendre:

- que fa cada pantalla
- que fa cada boto o accio visible
- quan conve utilitzar cada opcio
- quins avisos o limits es poden trobar
- com resoldre casos senzills i casos mes complexos

---

# 0. Aparells, tipus i puntuacio

## 0.1. Que son els aparells dins del programa

En aquest programa, un aparell es la manera d'identificar una prova o unitat de notes que despres es fara servir a la competicio.

Dit d'una manera practica, l'aparell respon a preguntes com aquestes:

- quina prova existeix
- com es diu i amb quin codi es reconeix
- si competeix per persona o per equip
- quants exercicis tindra
- com s'introdueixen les notes
- quins calculs es fan abans d'arribar al resultat final

Per tant, els aparells no son nomes un nom visible. Tambe defineixen com treballara la puntuacio.

### Exemple senzill

Una competicio te nomes un aparell anomenat `Trampoli`, amb 2 exercicis i una puntuacio final que surt de combinar execucio, dificultat i altres valors.

### Exemple mes complex

Una competicio te diversos aparells, alguns individuals i alguns d'equip. Cada un pot tenir un nombre d'exercicis diferent i una manera de calcular la nota final tambe diferent.

## 0.2. Diferencia entre aparell global i aparell dins d'una competicio

El programa separa dues idees:

- l'aparell global
- l'aparell configurat dins d'una competicio

L'aparell global es la fitxa reutilitzable. Es on es defineix la identitat de l'aparell:

- codi
- nom
- tipus d'unitat competitiva
- si esta actiu
- model de puntuacio base

L'aparell dins d'una competicio es l'us concret d'aquell aparell en una competicio determinada. Aqui es decideix, per exemple:

- si aquest aparell s'utilitzara realment en la competicio
- quants exercicis tindra
- si esta actiu o no en aquella competicio

En resum:

- l'aparell global es la plantilla reutilitzable
- l'aparell de competicio es l'aplicacio concreta d'aquella plantilla

## 0.3. On es troba aquesta configuracio

Des de la pantalla de configuracio de la competicio, l'usuari troba tres accessos importants:

- `Configurar aparells`
- `Configurar classificacions`
- `Configurar rotacions`

Per treballar els aparells, el flux habitual es:

1. entrar a `Configurar aparells`
2. revisar els aparells ja afegits a la competicio
3. afegir-ne un de nou o editar-ne un d'existent
4. obrir `Puntuacio` quan calgui revisar camps i calculs

Tambe hi ha un acces a `Aparells globals`, que serveix per crear o mantenir les plantilles reutilitzables.

## 0.4. Pantalla de gestio d'aparells globals

La pantalla de `Gestio d'aparells globals` es el cataleg de plantilles d'aparell.

L'usuari hi troba:

- `Crear aparell`
- la llista d'aparells existents
- un indicador de si l'aparell esta actiu
- el recompte de quantes competicions el fan servir
- l'estat de la seva puntuacio
- les accions `Editar`, `Puntuacio` i, si es pot, `Eliminar`

### Que significa cada columna

`Codi`

Es l'identificador curt de l'aparell. Conve que sigui clar i consistent.

`Nom`

Es el nom visible que l'usuari trobara despres als desplegables i llistats.

`Actiu`

Indica si l'aparell esta disponible per fer-lo servir. Si no esta actiu, no hauria de formar part de noves configuracions habituals.

`En competicions`

Mostra quantes competicions fan servir aquest aparell. Es molt util per saber si es tracta d'un aparell ja consolidat o d'una prova encara no usada.

`Schema puntuacio`

Indica si l'aparell ja te configurada la seva logica de camps i calculs. Si diu que no esta configurat, l'aparell existeix, pero la part de notes encara no esta preparada.

### Accions disponibles

`Crear aparell`

Obre el formulari per donar d'alta una nova plantilla d'aparell.

`Editar`

Permet canviar nom, codi, tipus i estat actiu.

`Puntuacio`

Obre la pantalla on es defineix com es recullen i es calculen les notes.

`Eliminar`

Nomes es pot eliminar quan l'aparell no esta en us en cap competicio. Si ja s'esta fent servir, el programa protegeix aquesta eliminacio.

### Exemple senzill

Una organitzacio crea l'aparell `TRAMP` amb nom `Trampoli`, el deixa actiu i li defineix la puntuacio basica. A partir d'aqui, el podra reutilitzar a diverses competicions sense haver-lo de tornar a crear.

### Exemple mes complex

Una organitzacio te diversos aparells historics. Alguns continuen actius, d'altres ja no. Mirant la columna `En competicions`, pot decidir quins mantenir, quins deixar inactius i quins no conve tocar perque ja s'estan fent servir en esdeveniments reals.

## 0.5. Crear o editar un aparell global

Quan s'obre el formulari de crear o editar un aparell global, l'usuari veu principalment aquests camps:

- `Codi`
- `Nom`
- `Unitat competitiva`
- `Actiu`

I, a mes, veu el boto de `Puntuacio`.

### Codi

Es recomanable que sigui curt, clar i facil de reconeixer. Normalment s'utilitza una abreviacio estable.

Bon criteri:

- un codi curt
- en majuscules
- facil de diferenciar d'altres aparells

Mal criteri:

- un codi molt llarg
- un codi ambigu
- un codi gairebe igual a un altre ja existent

### Nom

Es el text que veuran les persones usuaries a les pantalles.

Ha de ser entenedor. En general, es millor un nom natural que no pas una abreviacio.

### Unitat competitiva

Aquest es un dels camps mes importants, perque defineix el tipus de subjecte que competira en aquest aparell.

Les opcions visibles son:

- `Individual`
- `Equip`

`Individual`

L'aparell competeix per inscripcio. Es a dir, cada persona inscrita pot passar per aquest aparell i tenir-hi notes propies.

`Equip`

L'aparell competeix per equip. En aquest cas, la logica de treball canvia: l'aparell es vincula a unitats d'equip i no nomes a persones individuals.

### Actiu

Serveix per decidir si l'aparell queda disponible per fer-lo servir.

Desactivar un aparell pot ser util quan:

- ja no es vol oferir en noves competicions
- es vol conservar l'historic pero evitar usos nous

### El boto `Puntuacio`

Si l'aparell encara no s'ha desat, el boto apareix desactivat amb el missatge que primer cal desar.

Quan l'aparell ja existeix, aquest boto obre el constructor de puntuacio.

### Exemple senzill

Es crea un aparell `DMT`, amb nom `Doble minitramp`, tipus `Individual` i estat actiu. Despres de desar-lo, ja es pot entrar a `Puntuacio`.

### Exemple mes complex

Es crea un aparell d'equip per a una prova en que el resultat final no surt d'una sola persona, sino de la combinacio de diversos membres. En aquest cas, marcar `Equip` des del principi es clau perque la resta de pantalles mostrin opcions coherents amb aquest tipus de treball.

## 0.6. Afegir un aparell a una competicio

A la pantalla `Aparells [nom de la competicio]`, l'usuari veu els aparells que aquella competicio te actius o configurats.

Des d'aqui hi ha accessos a:

- `Configuracio`
- `Aparells globals`
- `Afegir aparell`
- `Anar a notes`

La taula mostra, habitualment:

- codi
- nom de l'aparell
- nombre d'exercicis
- si esta actiu
- accio `Editar`

### El boto `Afegir aparell`

Serveix per incorporar a la competicio un aparell global que ja existeix.

Quan l'usuari entra al formulari, veu:

- el desplegable `Aparell`
- el camp `Nombre d'Exercicis`
- un resum de la `Unitat competitiva`
- el boto `Puntuacio`

### Aparell

Aquest desplegable mostra els aparells globals disponibles.

Si l'usuari selecciona un aparell, la pantalla informa automaticament si es tracta d'un aparell:

- global individual
- global d'equip

Aquesta ajuda es important per entendre quina mena de subjectes competiran en aquella prova.

### Nombre d'exercicis

Indica quantes vegades competiran les persones o equips en aquell aparell dins d'aquella competicio.

No es exactament la mateixa idea que els camps de notes. Aqui no es defineixen els valors d'una nota, sino quantes passades o exercicis hi haura.

### Resum d'unitat competitiva

La mateixa pantalla recorda a l'usuari:

- si l'aparell es individual, despres es podra fer servir amb inscripcions
- si l'aparell es d'equip, el treball de preparacio es fara des del workspace d'equips de la competicio

### El boto `Puntuacio`

Quan l'usuari ha triat un aparell, aquest boto apunta a la pantalla on es poden revisar o editar els camps i calculs d'aquell aparell.

### Exemple senzill

Una competicio afegeix `Trampoli` i li posa `2` exercicis. A partir d'aqui, les notes i les classificacions ja sabran que en aquest aparell hi ha dues passades.

### Exemple mes complex

Una competicio afegeix un aparell d'equip i un aparell individual. Encara que tots dos aparells visquin dins la mateixa competicio, el programa mostrara usos diferents mes endavant: l'individual treballara amb inscripcions, i el d'equip amb contextos, equips o series.

## 0.7. Com entendre els tipus d'aparell

Hi ha dues grans preguntes que l'usuari s'ha de fer:

1. aquest aparell competeix per persona o per equip?
2. aquest aparell tindra una puntuacio simple o una puntuacio amb diversos passos de calcul?

La primera pregunta es resol amb la `Unitat competitiva`.

La segona es resol a `Puntuacio`.

### Quan triar `Individual`

Quan cada esportista te la seva nota propia i aquella nota neix de les seves dades i els seus exercicis.

Exemples habituals:

- cada persona fa la seva passada
- cada persona te una dificultat propia
- cada persona apareix individualment a les classificacions o forma part d'una suma posterior

### Quan triar `Equip`

Quan la unitat que competeix no es una sola persona, sino un grup de membres que despres produiran un resultat conjunt.

Exemples habituals:

- equips on compten diversos membres
- resultats on es seleccionen les millors aportacions de l'equip
- proves on una mateixa nota final depen de diverses persones

### Cas important

Un aparell pot ser `Individual` i, mes endavant, participar en una classificacio per equips.

Aixo no es cap contradiccio.

Vol dir, simplement, que:

- les notes es recullen per persona
- pero el ranking final es pot agrupar o sumar per equips

Per tant, el tipus de l'aparell no diu com es mostrara tota la competicio; diu com competeix aquella prova en el moment de recollir i tractar les notes.

## 0.8. Pantalla de puntuacio de l'aparell

La pantalla `Puntuacio` serveix per definir com es construeix la nota.

Te tres pestanyes principals:

- `Camps`
- `Formules`
- `Avancat (JSON)`

I, a la part superior, acostuma a mostrar:

- el nom de l'aparell
- el nom de la competicio, si s'hi ha arribat des d'una competicio
- el boto `Ajuda`
- el boto `Desar`
- el boto `Cancelar`

### Idea general

El flux mental correcte es aquest:

1. decidir quines dades s'introduiran
2. decidir com es combinaran
3. desar el resultat

Si es fa al reves, es facil acabar amb formules que fan referencia a camps que encara no existeixen o a conceptes poc clars.

## 0.9. Pestanya `Camps`

La pestanya `Camps` defineix les dades d'entrada. Es a dir, que es demanara o es recollira abans del calcul final.

Cada fila de camp acostuma a tenir aquestes parts:

- `Etiqueta`
- `Code`
- `Var`
- `Abast`
- `Jutges`
- `Items`
- `Min`
- `Max`
- `Decimals`
- `Crash`
- `Eliminar`

### `Etiqueta`

Es el nom visible per a l'usuari.

Exemple:

- `Execucio`
- `Dificultat`
- `TOF`

### `Code`

Es la clau estable d'aquell camp. L'usuari no l'ha d'entendre com una funcio tecnica, sino com el nom curt amb que la resta de calculs reconeixeran aquest valor.

Conve no canviar-lo a la lleugera un cop el camp ja esta en us.

### `Var`

Es un nom curt alternatiu per fer que algunes formules siguin mes facils d'escriure o de llegir.

Si l'usuari vol simplicitat, pot deixar una nomenclatura curta i coherent.

### `Abast`

Indica a qui pertany realment aquest camp.

En un aparell individual, normalment el camp pertany a la persona que competeix.

En un aparell d'equip, aquest punt es especialment important perque ajuda a distingir:

- valors que pertanyen a cada membre
- valors compartits per tota la unitat competitiva

### `Jutges`

Quants jutges ompliran aquest camp.

### `Items`

Quants valors aporta cada jutge dins del mateix camp.

Es pot entendre aixi:

- si `Items` es `1`, cada jutge posa un sol valor
- si `Items` es `10`, cada jutge posa una llista de 10 valors

### `Min` i `Max`

Serveixen per limitar el rang admissible.

Son especialment utils per evitar errors d'entrada.

### `Decimals`

Serveix per decidir la precisio amb que es desara i es mostrara el valor.

### `Crash`

Activa una logica de tall o aturada en camps on aquesta regla tingui sentit.

Per a l'usuari, el mes important es entendre que, si s'activa, el programa pot deixar de tenir en compte part dels valors a partir d'un determinat punt.

### Exemple senzill

Camp `Dificultat`: 1 jutge, 1 item, minim 0, maxim alt, 2 decimals. Es el cas d'un valor unic i directe.

### Exemple mitja

Camp `Execucio`: 3 jutges, 10 items, decimals controlats. Cada jutge introdueix una petita taula de valors i despres una formula en fara el resum.

### Exemple complex

En un aparell d'equip, es defineix un camp individual per membre i un altre camp compartit per tota la unitat. Aixo permet que unes dades vinguin de cada participant i d'altres siguin comunes a tot l'equip.

## 0.10. Pestanya `Formules`: camps calculats o computed

La pestanya `Formules` serveix per crear resultats calculats a partir dels camps d'entrada o d'altres calculs anteriors.

En llenguatge d'usuari, aqui es decideix com neix la nota.

Cada fila acostuma a tenir:

- `Etiqueta`
- `Code`
- `Var`
- `Funcio`
- `Configuracio / Formula`
- `Eliminar`

### Regla practica

Cada formula hauria de tenir una finalitat clara.

Per exemple:

- obtenir una nota per jutge
- resumir diversos valors d'un mateix jutge
- resumir diversos jutges
- resumir aportacions de membres d'un equip
- construir el resultat final

## 0.11. Opcions de `Funcio` que l'usuari pot trobar

La columna `Funcio` es la que determina el tipus de calcul.

Les opcions habituals visibles son aquestes.

### `Expressio manual`

Es l'opcio mes directa. L'usuari escriu una formula lliure a partir de camps o calculs ja existents.

Quan conve:

- quan el calcul es simple
- quan ja es te clar el resultat que es vol
- quan nomes cal sumar, restar o combinar valors coneguts

Exemple senzill:

Una nota final que es la suma de diversos blocs i una resta de penalitzacio.

Avantatge:

- maxima llibertat

Precaucio:

- demana mes atencio, perque no guia tant com les opcions assistides

### `Per jutge i despres entre jutges (total final)`

Aquesta opcio fa un calcul en dues fases:

1. primer treballa dins de cada jutge
2. despres combina els resultats de tots els jutges

Es molt util quan cada jutge te diversos valors i primer cal resumir-los abans d'arribar a la nota final.

Exemple senzill:

Cada jutge valora diversos items d'execucio. Primer es calcula el resum de cada jutge i despres es fa la mitjana o la seleccio entre jutges.

Exemple mes complex:

Primer s'eliminen extrems dins de cada jutge, despres s'obte una nota per jutge, i finalment es tornen a aplicar regles de seleccio entre jutges per obtenir el resultat final.

### `Resultat per jutge (nota per jutge)`

Aquesta opcio calcula el resultat dins de cada jutge, pero no arriba a combinar els jutges entre ells.

Serveix quan l'usuari vol obtenir una llista de resultats, un per cada jutge, per usar-la despres en una altra formula.

Exemple molt clar:

Primer es crea una nota resumida per cada jutge, i mes endavant una altra formula decideix quines d'aquestes notes compten i com s'agreguen.

### `Per items i despres entre items (total final)`

Aqui l'ordre mental es l'invers:

1. primer es calcula que passa a cada item entre els jutges
2. despres es combinen els resultats de tots els items

Conve quan el protagonisme el tenen els items o elements, i no tant cada jutge considerat com a bloc complet.

Exemple senzill:

Per a cada element, es calcula un resum entre jutges. Despres se sumen o s'agreguen els resultats de tots els elements.

### `Entre membres (seleccio + agregacio)`

Aquesta opcio nomes apareix quan l'aparell es d'equip.

Serveix per combinar les aportacions dels membres d'una mateixa unitat competitiva.

Exemples habituals:

- sumar tots els membres
- fer la mitjana de tots els membres
- quedar-se amb els millors `N`
- eliminar extrems entre membres

Exemple senzill:

Un equip te 4 membres, pero nomes compten els 3 millors. Aquesta opcio permet triar exactament aquesta regla.

Exemple mes complex:

Primer es calcula una nota individual resumida per cada membre i despres, en una segona formula, es seleccionen les millors aportacions de l'equip per construir el resultat conjunt.

## 0.12. Opcions de seleccio que apareixen en les funcions assistides

Quan l'usuari fa servir funcions guiades, acostuma a trobar aquestes opcions de seleccio:

- `Tots (no seleccionar)`
- `Eliminar extrems (min i max)`
- `Eliminar extrems alternant fins N`
- `Millors N`
- `Pitjors N`

### `Tots (no seleccionar)`

No es descarta cap valor. Es fan servir tots els disponibles.

### `Eliminar extrems (min i max)`

Serveix per treure el valor mes baix i el mes alt abans de fer el calcul final.

Es una opcio molt util quan es vol reduir l'impacte d'un valor massa extrem.

### `Eliminar extrems alternant fins N`

Va traient valors extrems de manera progressiva fins quedar-se amb la quantitat desitjada.

Es util quan hi ha molts valors i es vol arribar a un conjunt mes controlat.

### `Millors N`

Nomes es queden els `N` valors mes alts.

### `Pitjors N`

Nomes es queden els `N` valors mes baixos.

### Exemple senzill

Hi ha 5 valors i l'organitzacio vol que nomes comptin els 3 millors. La seleccio correcta es `Millors N` i `N = 3`.

### Exemple mes complex

En un equip gran, es volen ignorar els extrems i acabar treballant amb un nucli mes representatiu. En aquest cas, `Eliminar extrems alternant fins N` pot ser mes adequat que una simple mitjana de tots els valors.

## 0.13. Opcions d'agregacio que l'usuari pot trobar

Despres de seleccionar quins valors compten, el programa demana com s'han de combinar.

Les opcions habituals son:

- `Suma`
- `Mitjana`
- `Mediana`
- `Minim`
- `Maxim`

I, quan es tracta de funcions entre membres, tambe pot apareixer:

- `Comptar`

### `Suma`

Ajunta tots els valors seleccionats en un total.

### `Mitjana`

Fa la mitjana dels valors seleccionats.

### `Mediana`

Agafa el valor central. Es especialment util quan es vol reduir l'efecte d'algun extrem.

### `Minim`

Es queda amb el valor mes baix.

### `Maxim`

Es queda amb el valor mes alt.

### `Comptar`

No construeix una nota com a tal, sino que retorna quants valors s'han tingut en compte. Es una opcio molt especifica, pero pot ser util en regles d'equip o comprovacions.

## 0.14. Altres opcions de configuracio dins les funcions guiades

Segons la funcio triada, l'usuari pot trobar mes opcions de detall.

### Camp font

Es la font d'on surten les dades que es volen tractar.

### Transformacio per valor

Permet aplicar una petita regla a cada valor abans de seleccionar o agregar.

En llenguatge d'usuari, vol dir:

- transformar cada dada abans del resum

Exemple:

- invertir una escala
- convertir un valor en una deduccio
- ajustar el comportament de cada item abans del calcul final

### Rang d'items

Permet dir des de quin item es comenca i quants items es volen tenir en compte.

Es molt util quan:

- nomes volen comptar alguns elements
- hi ha una part inicial o final que no s'ha d'incloure

### Seleccionar segons valor original o resultat transformat

Algunes pantalles avancades deixen decidir si la seleccio i l'agregacio s'han de fer:

- sobre el valor original
- sobre el valor ja transformat

Per a la majoria d'usos normals, el mes senzill es mantenir el comportament per defecte i nomes tocar aquesta opcio si es te molt clar el criteri esportiu o reglamentari.

### Transformacio final

Permet aplicar un ultim ajust al resultat, un cop el resum principal ja esta fet.

Pot ser util quan:

- cal canviar d'escala al final
- cal invertir el sentit del resultat
- cal presentar una nota derivada del resum obtingut

## 0.15. Pestanya `Avancat (JSON)`

Aquesta pestanya existeix com a suport avancat i de revisio.

Per a una persona usuaria no tecnica, la recomanacio habitual es clara:

- no tocar aquesta pestanya si les altres dues ja permeten fer la configuracio necessaria

Conve veure-la com una vista interna del resultat de la configuracio, no com la via principal de treball.

## 0.16. Exemples complets de configuracio

### Cas molt senzill

Es crea un aparell individual amb:

- un camp de dificultat
- un camp de penalitzacio
- una formula manual final

Aquest cas es bo per a proves simples on quasi tot es resol amb valors unics.

### Cas habitual

Es crea un aparell individual amb:

- un camp d'execucio amb diversos jutges i diversos items
- un camp de dificultat
- un camp de temps o valor complementari
- una formula per obtenir una nota per jutge
- una formula final que combina el resum d'execucio amb la resta de blocs

Aquest es el patro mes habitual quan la nota necessita diversos passos abans del resultat final.

### Cas d'equip

Es crea un aparell d'equip on:

- cada membre aporta una nota individual
- primer es resumeix la nota de cada membre
- despres es seleccionen els millors membres
- finalment es construeix la nota global de l'equip

Aquest cas ajuda a entendre per que el tipus `Equip` no es nomes un detall, sino una decisio que condiciona tota la logica posterior.

## 0.17. Recomanacio de flux per treballar be els aparells

El flux mes segur acostuma a ser aquest:

1. crear o revisar l'aparell global
2. decidir si es `Individual` o `Equip`
3. entrar a `Puntuacio` i definir els camps basics
4. afegir les formules mes necessaries, de la mes simple a la mes final
5. afegir l'aparell a la competicio
6. indicar el nombre d'exercicis
7. nomes despres continuar amb Inscripcions, Rotacions i Classificacions

Si aquest ordre es respecta, la resta del programa es torna molt mes previsible i molt mes facil d'explicar a l'usuari final.

---

# 1. Inscripcions

## 1.1. Per a que serveix

La pantalla d'Inscripcions es el centre de preparacio de la competicio. Des d'aqui es pot:

- importar participants des d'un Excel
- afegir o editar inscripcions manualment
- cercar participants
- dividir el llistat en pestanyes o blocs
- canviar l'ordre visible
- definir l'ordre de competicio
- crear i gestionar grups
- crear i gestionar equips
- preparar series d'equip
- associar fitxers multimedia
- exportar el llistat

## 1.2. Capcalera i accessos principals

A la part superior apareixen els accessos principals:

- `+ Importar Excel`: obre la pantalla per carregar un fitxer d'inscripcions.
- `+ Afegir inscripcio`: crea una inscripcio manual.
- `Configuracio competicio`: porta a la configuracio general de la competicio.
- `Tornar a competicions`: torna al llistat general de competicions.
- `Notes`: obre la pantalla de notes.
- `Rotacions`: obre el planner de rotacions en una pestanya nova.

Tambe es mostra:

- el nom de la competicio
- el nombre d'inscrits visibles
- el total general, si s'esta filtrant

## 1.3. Importar inscripcions des d'Excel

La pantalla d'importacio es molt directa:

- `Fitxer Excel (.xlsx)`: selector del fitxer.
- `Importar`: puja el document i crea o actualitza inscripcions.
- `Cancella`: torna a Inscripcions sense importar.
- `Torna a competicions`: surt de la competicio actual.

Comportament important:

- si una persona ja existeix a la competicio amb el mateix document identificatiu, la seva fitxa s'actualitza
- si l'Excel porta columnes extra amb noms que coincideixen amb camps habituals, pot haver-hi confusions en algunes vistes o exportacions

Bones practiques:

- utilitza una columna d'identificacio consistent
- revisa els noms de columnes abans d'importar
- si tens dades especials, es millor donar-los un nom clar i diferenciat

### Exemple senzill

Una entitat envia un sol Excel amb totes les seves gimnastes. L'organitzacio puja el fitxer i el llistat queda creat en pocs segons.

### Exemple mes complex

La mateixa entitat envia un segon Excel corregit. En tornar-lo a importar, el sistema actualitza les fitxes ja existents en lloc de duplicar-les, sempre que la identificacio coincideixi.

## 1.4. Afegir, editar i eliminar una inscripcio

### Afegir una inscripcio

Quan es prem `+ Afegir inscripcio`, s'obre un formulari amb:

- dades basiques
- camps addicionals, si la competicio en fa servir
- `Desar`
- `Cancelar`

Si s'esta treballant dins d'un context d'equips concret, el formulari ho indica clarament i informa de quin equip base tenia aquella persona.

### Editar una inscripcio

A la taula, cada fila pot mostrar:

- `Editar`: obre el formulari de la persona seleccionada

### Eliminar una inscripcio

A la taula, cada fila pot mostrar:

- `Eliminar`: obre la pantalla de confirmacio

A la confirmacio apareixen:

- `Cancella`
- `Eliminar`

La supressio es irreversible.

### Exemple senzill

Falta una gimnasta que no venia a l'Excel. Es prem `+ Afegir inscripcio`, s'omplen les dades i es desa.

### Exemple mes complex

Una persona ha estat creada per error. S'entra a `Eliminar`, es comprova el nom i es confirma la supressio definitiva.

## 1.5. Cercador

La barra de cerca permet trobar rapidament participants per:

- nom
- cognoms
- document
- entitat

Botons visibles:

- `Cerca`: aplica la cerca
- `Netejar`: elimina el text buscat

Quan la cerca esta activa, la pantalla mostra:

- quantes persones s'estan veient
- una etiqueta indicant quin text s'esta filtrant

### Exemple senzill

Es busca una sola gimnasta pel seu cognom per editar-li una dada.

### Exemple mes complex

Es filtra per una entitat concreta escrivint-ne el nom per revisar totes les inscripcions abans de crear grups.

## 1.6. Barra lateral d'accions

La pantalla te una barra lateral amb diverses eines.

Elements generals:

- `Desfer`: recupera l'estat anterior si s'ha fet un canvi.
- `Refer`: torna a aplicar un canvi desfet.
- `Amagar accions` o `Mostrar accions`: plega o desplega la barra lateral.
- boto de `Tornar a dalt`: ajuda a tornar a l'inici de la pantalla.

Aquest bloc es especialment util quan s'han reordenat llistes, s'han mogut participants o s'han aplicat ordenacions.

## 1.7. Ordre de competicio com a criteri final

A la part superior hi ha un interruptor anomenat `Ordre de competicio`.

Quan s'activa:

- l'ordre de competicio s'afegeix al final de les ordenacions actives
- el resultat final queda guardat com a nou ordre de sortida

Quan no hi ha cap ordenacio previa activa:

- el sistema avisa que primer cal activar almenys una ordenacio

Etiqueta visible possible:

- `Criteri final actiu`

### Quan conve fer-lo servir

- quan ja tens una ordenacio principal feta per categoria, subcategoria o qualsevol altre criteri
- quan vols que, en cas d'empat dins aquesta ordenacio, es respecti un ordre de competicio preparat abans

## 1.8. Divisions

La seccio `Divisions` serveix per separar el llistat en pestanyes o blocs mes manejables.

Accions visibles:

- `Aplicar divisio`: crea la divisio segons els camps marcats.
- `Barreja aleatoriament`: remena l'ordre de sortida dins el context actual.
- `Treure divisio`: elimina la divisio activa.

Opcions visibles:

- camps tipus `Divideix per:` amb selectors com categoria, subcategoria, entitat o altres camps disponibles

Comportament util:

- una mateixa inscripcio continua sent la mateixa, nomes canvia com es presenta el llistat
- si hi ha divisio activa, es poden fusionar pestanyes mantenint `SHIFT` mentre se n'arrossega una sobre una altra

### Forquilles de data de naixement

Si es treballa amb la divisio per forquilles de naixement, apareix una configuracio extra:

- `Etiqueta sense data`
- `Etiqueta fora de rang`
- `Afegir forquilla`
- `Desar forquilles`

Serveix per definir trams de dates i etiquetar correctament qui queda fora del tram o no te dada.

### Exemple senzill

Es marca `Categoria` i es prem `Aplicar divisio`. El llistat queda separat per categories.

### Exemple mes complex

Es marca la divisio per forquilles de naixement, es defineixen tres trams i es guarda. Despres s'aplica la divisio per veure la competicio separada per aquests trams.

## 1.9. Columnes

La seccio `Columnes` controla quina informacio es veu a la taula i en quin ordre.

Botons visibles:

- `Tot`: mostra totes les columnes disponibles
- `Cap`: amaga totes les columnes seleccionables
- `Per defecte`: torna a la configuracio base
- `Desar columnes`: guarda la disposicio actual

Comportament:

- les targetes de columna es poden arrossegar per canviar-ne l'ordre
- cada columna te una casella per mostrar-la o amagar-la
- es mostra un comptador de columnes visibles

### Exemple senzill

Per una revisio rapida, l'organitzacio deixa visibles nomes nom, entitat, categoria i ordre.

### Exemple mes complex

Abans d'exportar, es reorganitzen les columnes per posar primer les dades esportives i despres les administratives, i es desa aquesta vista.

## 1.10. Ordenacions des de la taula

Moltes columnes tenen un menu propi amb opcions d'ordenacio.

Accions habituals del menu de columna:

- triar `Mode`: ascendent, descendent o altres variants de presentacio
- triar `Ambit`
- `Ordre custom`
- `Reset custom`
- `Aplicar`

Ambits possibles:

- totes les inscripcions filtrades
- dins de cada pestanya activa
- dins de cada grup
- nomes un grup numeric concret

Si s'escull el grup numeric concret, apareix un selector extra per triar-lo.

### Ordre custom

`Ordre custom` obre una finestra on es poden arrossegar els valors detectats per decidir manualment quin valor ha d'anar abans i quin despres.

Botons visibles a la finestra:

- `Reset custom`
- `Tancar`
- `Desar ordre`

Comportament important:

- aquest ordre es desa per a aquella columna i per al context actual
- els canvis no s'apliquen fins que es prem `Desar ordre`

### Ordenacions actives

A la seccio `Altres` es veu la llista d'ordenacions actives.

Accions visibles:

- `Netejar ordenacions`
- `Treure` sobre un criteri concret

### Exemple senzill

S'ordena per `Entitat` de forma ascendent per veure juntes totes les persones del mateix club.

### Exemple mes complex

Primer s'ordena per categoria, despres per entitat i finalment s'activa `Ordre de competicio` com a criteri final per preservar una llista interna ja preparada.

## 1.11. Grups

La seccio `Grups` serveix per crear, omplir, buidar i revisar grups de competicio.

### Vista compacta

Elements principals:

- resum de quants grups hi ha
- `Abast`
- `Grup desti`
- `Crear grup nou amb seleccio`
- `Assignar seleccio`
- `Treure seleccio`
- `Obrir workspace`

L'abast pot ser:

- `Seleccio actual`
- `Visibles filtrades`

### Workspace de grups

El workspace amplia la feina en tres zones.

#### Zona esquerra: subconjunt d'inscripcions

Filtres visibles:

- `Cerca`
- `Categoria`
- `Subcategoria`
- `Entitat`
- `Estat de grup`
- `Grup actual`

Botons de seleccio:

- `Seleccionar visibles`
- `Afegir visibles`
- `Treure visibles`
- `Importar seleccio del llistat`
- `Netejar seleccio`
- `Anterior`
- `Seguent`

#### Zona central: accions

Pestanyes:

- `Manual`
- `Automatic`

En mode manual:

- `Previsualitzar creacio`
- `Crear grup nou`
- `Assignar a grup`
- `Treure del grup`
- `Desactivar grup buit`

En mode automatic:

- es poden seleccionar blocs d'origen
- hi ha opcions de fallback per gestionar casos irregulars
- es pot crear per nombre de grups, per mida fixa o per forquilla
- sempre hi ha opcions de `Previsualitzar` abans de crear

#### Zona dreta: grups existents i impacte

Elements visibles:

- `Desactivar buits`
- llista de grups actius
- zona per deixar persones sense grup
- llista de grups buits
- bloc de `Previsualitzacio d'impacte`
- boto `Netejar` de la previsualitzacio quan hi ha una simulacio feta

### Accions des de cada grup del llistat principal

A la capcalera de cada grup poden aparixer:

- indicador de quants integrants te
- etiqueta `Ordre no desat`
- menu del grup

Dins del menu:

- `Veure ordre competicio`
- `Desar ordre competicio`
- `Editar nom`

### Finestra d'ordre de competicio del grup

Quan s'obre:

- mostra l'ordre guardat real del grup
- indica quants participants hi ha
- pot avisar si l'ordre visible de la taula no coincideix amb l'ordre guardat

Botons visibles:

- `Tancar`
- `Desar ordre`

Comportament important:

- es pot consultar o editar l'ordre guardat sense canviar automaticament l'ordre visible de la taula principal
- si hi ha filtres actius, poden quedar participants del grup fora de la vista actual

### Limits i avisos

Quan ja hi ha rotacions actives:

- deixar buit un grup programat pot quedar bloquejat
- modificar segons quin grup pot generar avisos previs

### Exemple senzill

Es seleccionen 8 persones visibles i es prem `Crear grup nou`. El sistema crea un grup nou amb aquesta seleccio.

### Exemple mitja

Es filtra per una categoria, s'importa la seleccio al workspace, es previsualitza la creacio automatica i despres es creen 4 grups equilibrats.

### Exemple complex

Ja existeixen grups programats a Rotacions. Cal retocar nomes dues persones. Es fa des del workspace manual, es revisa la previsualitzacio i despres es desa l'ordre de competicio del grup afectat.

## 1.12. Equips

La seccio `Equips` serveix per treballar equips dins d'un context concret.

Un context pot ser:

- el context base
- un context addicional per a una necessitat concreta de competicio

### Vista compacta

Elements principals:

- selector de `Context`
- selector d'`Abast`
- selector d'`Equip desti`
- camp `Nom del nou equip`
- `Crear equip nou amb seleccio`
- `Assignar seleccio`
- `Treure seleccio`
- `Obrir workspace`
- `Obrir series d'equip`

### Workspace d'equips

#### Capcalera del context

Informacio visible:

- context actiu
- nombre d'equips
- quantes inscripcions tenen equip
- quantes no en tenen

Botons visibles:

- `Detalls`

Quan s'obren els detalls:

- selector de context
- `Nou context`
- `Renombrar context`
- `Eliminar context`
- llista d'aparells d'equip disponibles per a aquest context
- `Desar aparells d'equip`

Limits importants:

- el context base no es pot renombrar
- el context base no es pot eliminar

#### Zona esquerra: subconjunt d'inscripcions

Filtres visibles:

- `Cerca`
- `Categoria`
- `Subcategoria`
- `Entitat`
- `Estat al context`
- `Equip actual al context`

Botons de seleccio:

- `Seleccionar visibles`
- `Afegir visibles`
- `Treure visibles`
- `Importar seleccio del llistat`
- `Netejar seleccio`
- `Anterior`
- `Seguent`

#### Zona central: accions

Pestanyes:

- `Automatic`
- `Manual`

En mode automatic:

- seleccio dels camps de particio
- opcio `Reassignar equips existents`
- `Previsualitzar`
- `Crear equips automaticament`

En mode manual:

- camp per escriure el nom del nou equip
- `Crear equip nou i assignar seleccio`
- selector d'equip existent
- `Assignar seleccio a aquest equip`
- `Treure equip de la seleccio`

#### Zona dreta: resultat previst i equips del context

Elements visibles:

- panell de `Resultat previst`
- `Netejar` la previsualitzacio
- llista d'equips del context
- `Mode tauler`
- `Eliminar buits`
- `Eliminar tots`

Comportament util:

- es pot deixar una persona sense equip arrossegant-la a la zona sense assignacio
- les targetes dels equips permeten revisio i manteniment sense tocar la seleccio central

### Avisos i limits

- si no es marca cap camp de particio, l'automatic no pot calcular equips
- si es treballa nomes amb la seleccio del workspace i aquesta es buida, el sistema ho avisa
- eliminar tots els equips del context deixa les persones sense equip dins aquell context

### Exemple senzill

Es crea un equip manual per a 3 persones ja seleccionades i s'assignen d'un sol cop.

### Exemple mitja

Es crea un context nou per a una prova concreta, s'activen els aparells d'equip pertinents i es generen equips automaticament per entitat i categoria.

### Exemple complex

Es treballa amb un context addicional sense tocar l'equip base. Algunes persones mantenen el seu equip base, pero en aquest context concret es reorganitzen amb un altre criteri.

## 1.13. Series d'equip

La seccio `Series d'equip` organitza les unitats competitives dels aparells d'equip.

Nomes te sentit quan la competicio te almenys un aparell d'equip actiu.

### Vista compacta

Elements principals:

- selector d'`Aparell`
- `Refrescar`
- `Start list`
- camp de nom opcional per a la serie
- `Crear serie buida`
- `Crear amb seleccio`
- `Treure seleccio`
- `Obrir workspace`

### Workspace de series

#### Part superior

Elements principals:

- selector d'aparell
- camp per nom opcional
- `Refrescar`
- `Desactivar buides`
- `Crear serie buida`
- `Crear amb seleccio`
- `Treure seleccio`
- `Start list`

#### Zona esquerra: unitats competitives

Filtres visibles:

- `Cerca`
- `Context`
- `Estat`
- `Serie`

Botons de seleccio:

- `Seleccionar visibles`
- `Netejar seleccio`
- `Anterior`
- `Seguent`

#### Zona dreta: series creades

Mostra:

- les series actives de l'aparell seleccionat
- el seu resum
- si estan programades o no

### Avisos i limits

- si no hi ha seleccio, nomes es pot crear una serie buida
- nomes es poden desactivar series buides
- quan una serie ja esta programada, algunes neteges poden conservar-la i avisar-ho

### Exemple senzill

Es tria un aparell d'equip, es seleccionen dues unitats competitives i es prem `Crear amb seleccio`.

### Exemple complex

Despres de crear diverses series, es genera una `Start list` per compartir-la amb l'equip d'organitzacio i es desactiven nomes les series buides que no tenen utilitat.

## 1.14. Fitxers multimedia

La seccio `Fitxers multimedia` te dos usos principals:

- carregar fitxers manualment per persona
- fer una assignacio assistida a partir d'una carpeta local

### Assignacio assistida des de carpeta

Elements visibles:

- selector de carpeta
- `Previsualitzar match`
- `Aplicar assignacions`

Despres de la previsualitzacio apareix una taula amb:

- `Fitxer`
- `Estat`
- `Inscripcio`
- `Score`
- `Detall`

Lectura practica dels estats:

- coincidencia clara
- coincidencia que conve revisar
- fitxer sense coincidencia

### Gestio des de cada fila del llistat

A la columna multimedia de cada inscripcio poden aparixer:

- llista de fitxers ja associats
- boto `Pujar`
- boto per marcar un fitxer com a principal
- boto per eliminar un fitxer

### Exemple senzill

Es puja una sola foto manualment a una inscripcio concreta.

### Exemple complex

S'importa una carpeta amb molts fitxers. Primer es fa `Previsualitzar match`, es revisen les coincidencies dubtoses i despres s'aplica l'assignacio definitiva.

## 1.15. Altres

La seccio `Altres` concentra eines de revisio i sortida.

Accions visibles:

- `Exportar Excel`
- `Netejar ordenacions`
- `Treure` criteris concrets de la llista d'ordenacions actives

Tambe permet escollir quines columnes han d'apareixer a l'Excel.

Utilitat habitual:

- preparar una exportacio administrativa
- preparar una exportacio per impressio
- confirmar quines ordenacions estan afectant el llistat abans de seguir treballant

## 1.16. Recomanacio de flux a Inscripcions

Un ordre de treball habitual es:

1. importar o afegir inscripcions
2. cercar i revisar errors evidents
3. aplicar divisions utiles
4. ordenar i guardar columnes
5. crear grups
6. crear equips si la competicio en necessita
7. preparar series d'equip si cal
8. revisar l'ordre de competicio
9. exportar o passar a Rotacions

---

# 2. Rotacions

## 2.1. Per a que serveix

La pantalla de Rotacions serveix per construir el programa horari de la competicio.

Des d'aqui es pot:

- crear franges horaries
- crear descansos
- definir estacions
- col.locar grups o series a la graella
- decidir quins elements queden fora de programa
- guardar dades d'exportacio
- descarregar l'horari en Excel

## 2.2. Capcalera i accessos principals

Botons visibles:

- `Ajuda`
- `Inscripcions`
- `Notes`
- `Configuracio`

La capcalera recorda:

- quina competicio s'esta editant
- que la graella es treballa arrossegant grups o series

## 2.3. Resum de fora de programa

A la part superior hi ha un resum anomenat `Fora de programa`.

Mostra:

- si hi ha elements existents que encara no formen part de l'horari
- quants elements son
- quants subjectes representen

Aquest resum es molt util per detectar si el programa esta incomplet.

## 2.4. Columna esquerra: elements programables

La columna esquerra separa els elements en tres blocs:

- `Programats`
- `Fora de programa`
- `Utilitats`

### Programats

Mostra tot el que ja esta col.locat a la graella.

### Fora de programa

Mostra tot el que existeix pero encara no ha estat situat a cap franja i estacio.

### Utilitats

Inclou:

- `(Buit)`

Aquest element serveix per esborrar una cel.la de la graella arrossegant-lo fins a la posicio que es vol buidar.

## 2.5. Mostrar grups fora de programa a notes i jutges

Hi ha un interruptor amb el text:

- `Mostrar grups fora de programa a notes i jutges`

Si esta activat:

- aquests elements tambe apareixen a les vistes de competicio relacionades

Si esta desactivat:

- nomes es veuen al planner de rotacions

Es una decisio organitzativa important quan hi ha grups encara pendents de situar.

## 2.6. Afegir una franja manualment

El bloc `Afegir franja` te:

- hora d'inici
- hora de fi
- camp de titol
- boto `+`

Serveix per crear una franja concreta de manera manual.

### Exemple senzill

Es crea una franja de `09:00` a `09:20` amb el titol `Escalfament`.

## 2.7. Generar franges automaticament

El bloc `Generar franges automaticament` te:

- hora inicial
- hora final
- interval en minuts
- titol base
- opcio `Esborrar franges existents abans de generar`
- boto `Generar franges`

Serveix quan es vol construir una pauta regular sense entrar una per una.

Comportament important:

- les franges es generen a partir de l'interval indicat
- si es marca l'opcio d'esborrar, el programa anterior desapareix abans de crear el nou

### Exemple senzill

De `09:00` a `11:00`, amb interval de `20` minuts i titol base `Rotacio`, el sistema crea una serie de franges regulars.

### Exemple complex

Despres d'una reunio d'ultima hora, es decideix refer tot l'horari del mati. Es marca l'opcio d'esborrar i es regeneren totes les franges del tram.

## 2.8. Afegir descans

El bloc `Afegir descans` te:

- boto `+ Descans`

Serveix per crear una estacio o punt de descans que pot entrar a la planificacio com a part del circuit.

## 2.9. Graella del programa

La zona central es la graella `Programa (franges x estacions)`.

Com es treballa:

- s'arrosseguen grups o series a cada cel.la
- si una cel.la queda buida, es mostra un guio
- es pot arrossegar `(Buit)` per esborrar una assignacio

Si s'intenta posar un element en una estacio incompatible:

- el sistema ho bloqueja i ho avisa

## 2.10. Estacions

Cada columna representa una estacio.

Accions visibles a la capcalera de cada estacio:

- arrossegar la columna per canviar l'ordre
- `Eliminar estacio`

L'ordre de les estacions afecta directament la lectura del programa i tambe la manera com es fa servir l'opcio d'extrapolar.

## 2.11. Accions de cada franja

Cada franja mostra:

- titol
- hora d'inici i hora de fi
- selector d'`Ordre`

El selector d'ordre pot mostrar opcions com:

- `Mantenir`
- `Aleatori`
- `Primer passa a ultim`

Aquest camp serveix per decidir com ha de circular l'ordre dins aquella franja.

Botons de cada franja:

- `Editar`
- `Inserir despres`
- `Netejar franja`
- `Extrapolar`
- `Eliminar`

### Editar

Obre una finestra petita on es poden canviar:

- titol
- hora inicial
- hora final

Quan es desa:

- les franges seguents s'ajusten automaticament

### Inserir despres

Crea una nova franja just a continuacio de la seleccionada.

Serveix molt be quan cal afegir una pausa o una rotacio extra sense reconstruir tot el dia.

### Netejar franja

Esborra les assignacions d'aquella franja, pero no necessariament elimina la franja en si.

### Extrapolar

Copia el patro de la franja actual a les seguents, fent-lo rodar per les estacions.

Es especialment util quan:

- hi ha un circuit regular
- cada grup ha d'anar passant per totes les estacions

No te sentit si la franja base esta buida.

### Eliminar

Esborra la franja.

## 2.12. Netejar tot el programa

Boto visible:

- `Netejar Programa`

Serveix per esborrar tota la programacio actual.

Avis important:

- es una accio forta i el sistema la demana confirmar
- no es pot desfer de manera automatica

## 2.13. Exportacio Excel

A la columna dreta hi ha el bloc `Exportacio Excel`.

Opcions del desplegable:

- `Exportar participants`
- `Exportar grups`

La diferencia practica es:

- el mode de participants mostra el detall de les persones dins cada cel.la
- el mode de grups resumeix el programa a nivell de grup o serie

## 2.14. Dades de l'exportacio

El bloc `Dades export Excel` permet personalitzar el document.

Camps visibles:

- titol de competicio
- seu
- data

Configuracio addicional:

- llista de camps de participants arrossegable per canviar-ne l'ordre
- selector per pujar logo
- `Pujar logo`
- `Treure`
- `Desar dades export`

Serveix per deixar l'Excel llest per compartir o imprimir.

### Exemple senzill

S'omple titol, seu i data i es desa. Despres s'exporta l'horari.

### Exemple mes complex

S'afegeix el logo oficial, es reordenen els camps de participant i es genera un Excel mes formal per enviar a clubs i jutges.

## 2.15. Recomanacio de flux a Rotacions

Un flux de treball habitual es:

1. comprovar quins elements estan fora de programa
2. crear o regenerar franges
3. revisar estacions i el seu ordre
4. col.locar grups o series a la graella
5. usar `Extrapolar` si hi ha un circuit repetitiu
6. decidir si els elements fora de programa han de ser visibles a notes i jutges
7. preparar les dades d'exportacio
8. exportar l'horari

---

# 3. Classificacions

## 3.1. Per a que serveix

La zona de Classificacions serveix per definir com es calculen i es mostren els resultats de la competicio.

Des d'aqui es pot:

- crear classificacions diferents
- decidir si son individuals o per equips
- escollir quins aparells i quins camps entren al calcul
- definir desempats
- aplicar filtres
- configurar la presentacio final
- previsualitzar el resultat abans de publicar-lo
- reutilitzar plantilles
- consultar la vista en viu i el mode loop

## 3.2. Barra superior del configurador

Botons visibles:

- `Configuracio`
- `Plantilles globals`, si l'usuari en te acces
- `+ Afegir`
- `Guardar`
- `Eliminar`

Que fa cada boto:

- `+ Afegir`: crea una classificacio nova.
- `Guardar`: desa la classificacio actual.
- `Eliminar`: esborra la classificacio seleccionada.

Important:

- si una classificacio es nova i encara no s'ha guardat, algunes accions com la previsualitzacio poden quedar limitades fins que es desi

## 3.3. Biblioteca de plantilles

A sota de la barra principal pot apareixer la biblioteca de plantilles.

Elements visibles:

- selector `Les meves plantilles...`
- `Recarregar`
- `Comprovar`
- `Aplicar`
- `Desar com plantilla`

### Recarregar

Actualitza la llista de plantilles disponibles.

### Comprovar

Analitza si una plantilla encaixa amb la competicio actual.

### Aplicar

Crea una nova classificacio a partir de la plantilla seleccionada.

Si hi ha incompatibilitats:

- el sistema pot mostrar avisos
- en alguns casos pot oferir una segona via per provar d'adaptar la plantilla

### Desar com plantilla

Guarda la classificacio actual com a model reutilitzable.

Important:

- primer cal haver guardat la classificacio
- cal posar nom a la plantilla

### Exemple senzill

Es carrega una plantilla de `General individual`, es comprova i s'aplica per estalviar temps.

### Exemple complex

Es prova una plantilla antiga que no encaixa del tot. El sistema mostra avisos, es confirma una adaptacio assistida i finalment es crea una nova classificacio compatible.

## 3.4. Columna esquerra: configuracions

A l'esquerra es veu la llista de classificacions guardades.

Cada entrada pot mostrar:

- nom
- tipus
- estat activa o inactiva
- informacio resum del mode

En fer clic sobre una configuracio:

- s'obre l'editor de la dreta

## 3.5. Ajuda contextual i navegacio interna

L'editor te:

- boto `Ajuda`
- navegacio interna per blocs
- boto per `Tornar a dalt`

Aquestes ajudes estan pensades per orientar l'usuari sense sortir de la pantalla.

## 3.6. Bloc 1: Metadades

Serveix per definir la identitat general de la classificacio.

Camps visibles habituals:

- `Nom`
- `Slug`, en alguns contextos
- `Tipus`
- `Activa`

Si es treballa per equips, apareixen camps addicionals:

- `Context d'equips`
- `Mode d'equips`

El `Tipus` sol distingir entre:

- individual
- equips

L'opcio `Activa` decideix si aquella classificacio ha d'apareixer a la vista en viu.

## 3.7. Bloc 2: Particions

Serveix per decidir com es divideix el resultat final en diferents blocs visibles.

Elements principals:

- seleccio de camps de particio
- configuracions de grups personalitzats
- configuracio de forquilles de naixement, si escau
- configuracio extra per equips

Opcions rellevants en classificacions per equips:

- `Incloure participants sense equip`
- `+ Particio` per crear particions manuals

En aquest bloc no s'esta calculant encara la puntuacio; s'esta decidint com es separaran els resultats finals.

### Exemple senzill

Una classificacio es divideix per `Categoria`.

### Exemple complex

Una classificacio per equips es divideix per un context d'equips concret i, dins d'aquest, per particions manuals que representen diferents blocs de competicio.

## 3.8. Bloc 3: Puntuacio

Es el cor de la classificacio.

Aqui es decideix:

- quins aparells entren
- quins camps es fan servir
- com se seleccionen els exercicis
- com se sumen o comparen els resultats

### Aparells inclosos i camps

L'usuari pot:

- marcar els aparells que formen part del calcul
- definir els camps rellevants per a cada aparell

### Agregacio de camps

Serveix per decidir com es combinen diversos valors dins un mateix exercici.

Opcions visibles habituals:

- suma
- mitjana
- mediana
- maxim
- minim

### Base de seleccio

En alguns casos per equips apareix:

- `Per membre i despres suma`
- `Pool d'equip amb limit per membre`

En paraules simples:

- una opcio calcula primer cada membre i despres suma
- l'altra tracta l'equip com una bossa comuna de resultats, amb limit per participant si cal

### Seleccio d'exercicis

Es pot decidir si es treballa:

- per aparell
- per aparell amb excepcions
- amb una bossa global

I despres triar el mode concret:

- tots
- millor 1
- millors N
- pitjor 1
- pitjors N
- primer existent
- ultim existent
- exercici concret
- llista d'exercicis

Camps auxiliars habituals:

- `N`
- `Index`
- `Max N per participant`
- `Llista d'indexs`

### Agregacio entre aparells

Decideix com es combinen els resultats dels diferents aparells.

### Ordre principal

Defineix si:

- mes es millor
- menys es millor

### Resultat per aparell

Pot ser:

- `Puntuacio normal`
- `Victories`

Si s'escull `Victories`, apareixen blocs addicionals per decidir com es comparen els participants o equips.

### Exemple senzill

Classificacio general individual que suma tots els aparells i ordena de mes a menys.

### Exemple mitja

Classificacio que nomes compta els `millors 2` exercicis d'un conjunt d'aparells.

### Exemple complex

Classificacio per equips derivada dels resultats individuals, amb seleccio comuna d'exercicis i limit per participant per evitar que un sol membre concentri tot el pes del resultat.

## 3.9. Bloc 4: Desempat

Serveix per decidir que passa quan dues o mes posicions queden igualades.

Elements visibles:

- taula de criteris
- `+ Afegir criteri`
- opcions avancades

Per a cada criteri es poden definir:

- aparells
- camp
- exercicis
- participants, quan toca
- ordre

Quan la classificacio esta en mode `Victories`, pot haver-hi tambe un desempat intern propi.

### Exemple senzill

Si dues persones empaten a punts, guanya qui te millor execucio.

### Exemple complex

Primer es desempata pel millor aparell, despres per un camp concret i finalment per una altra combinacio d'exercicis si encara persisteix l'empat.

## 3.10. Bloc 5: Filtres

Serveix per decidir qui entra a la classificacio abans de calcular el resultat.

Filtres visibles:

- entitats
- categories
- subcategories
- grups

Tambe hi ha un apartat d'opcions avancades per a configuracions mes especials.

### Exemple senzill

Es crea una classificacio nomes per a una categoria concreta.

### Exemple complex

Es crea una classificacio d'una sola fase de competicio filtrant per grups i subcategories alhora.

## 3.11. Bloc 6: Presentacio

Serveix per decidir com es veura el resultat final.

### Regles de sortida

Elements visibles:

- `Top N`
- `Mostrar empats`
- `Previsualitzar`

`Top N` limita quantes posicions es mostren.

`Mostrar empats` decideix si els empats es veuen com a tals o si es forca una llista sense aquesta expressio visual.

`Previsualitzar` mostra una simulacio sense sortir de l'editor.

Important:

- si la classificacio encara no esta guardada, la previsualitzacio pot demanar primer un desat

### Columnes i previsualitzacio

Accions visibles:

- `+ Builtin`
- `+ Camp`

Serveixen per decidir quines columnes sortiran a la vista en viu.

Tambe hi ha:

- panell de previsualitzacio
- apartat avancat del esquema complet, pensat per a casos especials

### Exemple senzill

Es mostra nomes posicio, nom i punts.

### Exemple complex

S'afegeixen columnes extres per mostrar parcials, detalls de jutges o camps especifics que siguin importants per a aquella classificacio.

## 3.12. Guardar, eliminar i previsualitzar

### Guardar

`Guardar` desa la configuracio actual.

Despres de desar correctament:

- apareix un missatge breu de confirmacio

### Eliminar

`Eliminar` esborra la classificacio seleccionada despres de confirmacio.

### Previsualitzar

`Previsualitzar` calcula una mostra del resultat i l'ensenya a la mateixa pantalla.

Si la classificacio no estava guardada encara:

- es mostra l'avis que primer s'ha de guardar

## 3.13. Vista en viu

La vista `Classificacions en viu` serveix per seguir els resultats mentre s'estan entrant notes o ajustant configuracions.

Elements visibles:

- estat de connexio
- ultima actualitzacio
- pestanyes, una per cada classificacio activa
- comptador a cada pestanya

Botons visibles:

- `Excel (tot)`
- `Excel (pestanya)`
- `Notes`
- `Configurar`
- `Inscripcions`

Comportament:

- la pantalla s'actualitza automaticament
- cada classificacio activa te la seva pestanya
- si no hi ha classificacions actives, apareix un avis

### Exemple senzill

Es segueix la classificacio general en directe mentre entren les notes.

### Exemple complex

Hi ha diverses classificacions actives alhora, com general, per categoria i per equips, i cada una es consulta en la seva pestanya.

## 3.14. Mode Loop

La vista `Classificacions - Mode Loop` rota automaticament entre classificacions i particions.

Elements visibles:

- nom de classificacio actual
- nom de la particio actual
- indicador de pagina
- indicador de files visibles
- estat i ultima actualitzacio

Botons visibles:

- `Notes`
- `Live tabs`
- `Configurar`

Utilitat habitual:

- pantalles grans
- televisors
- projector
- espais publics on es vol mostrar la classificacio sense intervencio constant

### Exemple senzill

Es projecta una sola classificacio i el loop va passant les pagines automaticament.

### Exemple complex

En una pantalla de pavello es van alternant diferents classificacions i particions de manera automatica durant tota la jornada.

## 3.15. Recomanacio de flux a Classificacions

Un ordre de treball habitual es:

1. crear una nova classificacio o aplicar una plantilla
2. definir metadades i tipus
3. fixar particions
4. configurar la puntuacio
5. decidir els desempats
6. aplicar filtres si cal
7. definir la presentacio
8. guardar
9. previsualitzar
10. activar-la si ha de sortir a la vista en viu
11. revisar la live o el loop

---

# 4. Tres recorreguts complets

## 4.1. Cas molt senzill

1. Importar Excel.
2. Fer una cerca rapida per validar que hi son totes les persones.
3. Aplicar una divisio per categoria.
4. Exportar l'Excel de suport.

## 4.2. Cas habitual de competicio individual

1. Importar participants.
2. Crear grups per categories o subcategories.
3. Revisar i desar l'ordre de competicio dins de cada grup.
4. Passar a Rotacions i col.locar cada grup a la seva franja i estacio.
5. Crear una classificacio general i una altra per categoria.
6. Previsualitzar-les.
7. Activar-les i revisar la vista en viu.

## 4.3. Cas mes complet amb equips

1. Importar participants.
2. Crear o revisar equips en el context adequat.
3. Preparar series d'equip per als aparells corresponents.
4. Configurar Rotacions combinant grups individuals i series d'equip.
5. Definir una classificacio individual i una classificacio per equips.
6. Fer servir previsualitzacions abans d'aplicar canvis grans.
7. Mostrar la classificacio en directe a una pantalla amb mode loop.

---

# 5. Recomanacions practiques

- Abans de fer canvis grans, fes una previsualitzacio si la pantalla l'ofereix.
- Si una pantalla permet `Desfer`, utilitza-la quan hagis provat una ordenacio o una reorganitzacio que no t'encaixa.
- Quan treballis amb grups o equips ja programats, revisa els avisos amb calma abans de confirmar.
- Si una llista visible no coincideix amb l'ordre guardat, no ho donis per bo fins revisar l'ordre de competicio.
- A Rotacions, no deixis elements fora de programa sense decidir si han de ser visibles o no a Notes i jutges.
- A Classificacions, guarda abans de previsualitzar i activa nomes les configuracions que realment hagin d'apareixer en viu.

---

# 7. Notes, Jurat, QRs i portal

## 7.1. Per a que serveix aquest bloc

Aquest bloc cobreix tot el tram que va des de la introduccio de notes fins a la feina dels jutges i la comparticio dels accessos.

En la practica, reuneix quatre peces molt relacionades:

- el panell central de `Notes`
- la gestio de `Jurat / QRs`
- el `Portal del jutge` que s'obre amb cada QR
- el `Portal public` per compartir classificacions en viu

Es important entendre que no son pantalles separades sense relacio. Formen un circuit complet:

1. l'organitzacio prepara aparells, grups i rotacions
2. des de `Notes` obre l'entrada de puntuacions
3. des de `Jurat / QRs` crea accessos concrets per als jutges
4. els jutges entren pel seu portal i desen valors
5. l'organitzacio controla incidencies des del centre de suport
6. si cal, es comparteixen classificacions en viu amb el portal public

## 7.2. Capcalera del panell de `Notes`

La pantalla `Notes` es presenta com a panell central d'organitzacio.

A dalt de tot, l'usuari acostuma a trobar aquests accessos:

- `Inscripcions`
- `Classificacions en viu`
- `Classificacions loop`
- `Suport jutges`
- `QR public`
- `Configuracio`

### Que fa cada boto

`Inscripcions`

Permet tornar al panell on es prepara la base de participants, grups, equips i series.

`Classificacions en viu`

Obre la vista live per comprovar com es transformen les notes en resultats visibles.

`Classificacions loop`

Obre la vista pensada per a pantalla continua o projeccio.

`Suport jutges`

Obre el centre de missatges i seguiment d'incidencies entre organitzacio i jutges.

`QR public`

Obre la gestio dels accessos publics per compartir classificacions en directe.

`Configuracio`

Porta a la zona on es poden revisar aparells, puntuacio, classificacions i altres ajustos generals.

### Exemple senzill

La secretaria tecnica esta entrant notes i, al mateix temps, vol comprovar el ranking. Des de la mateixa capcalera pot saltar a `Classificacions en viu` i tornar a `Notes` sense perdre el context.

### Exemple mes complet

Durant una competicio, una persona d'organitzacio pot anar alternant entre `Notes`, `Suport jutges` i `QR public` segons si necessita revisar valors, respondre una incidencia o compartir la classificacio amb una pantalla externa.

## 7.3. El panell d'inscripcions dins de `Notes`

A la zona central de `Notes`, el programa organitza la feina en diversos nivells de pestanyes.

Normalment l'usuari hi troba:

- pestanyes de grup
- pestanyes d'aparell
- pestanyes d'exercici
- una taula central de persones o unitats competitives

### Pestanyes de grup

Cada pestanya superior representa un grup visible dins del programa.

Al costat del nom del grup, el programa mostra un recompte per ajudar a entendre quantes inscripcions o unitats hi ha dins d'aquell bloc.

Si hi ha grups sense franja assignada, poden aparixer marcats com a `Fora`.

### Avis de `Fora de programa`

Quan surt un avis de fora de programa, vol dir que aquell bloc existeix, pero encara no esta col.locat dins del programa de rotacions.

Per a l'usuari, aquest avis no significa que la dada sigui incorrecta, sino que:

- encara no esta integrada en l'horari real
- o be s'ha decidit mostrar-la igualment

### Pestanyes d'aparell

Un cop dins d'un grup, apareixen els aparells actius per a aquell bloc.

Aixo ajuda a no barrejar notes de proves diferents.

### Pestanyes d'exercici

Dins de cada aparell, el programa separa els exercicis o passades.

Si un aparell te 1 exercici, la lectura es mes simple.

Si en te 2 o mes, cada exercici te la seva pestanya per evitar confusions.

### Exemple senzill

Un grup te un sol aparell i un sol exercici. L'usuari gairebe no ha de navegar: entra al grup i veu directament la taula de notes.

### Exemple mes complex

Una competicio te diversos grups, un aparell amb dues passades i un altre aparell d'equip. En aquest cas, les pestanyes ajuden a separar clarament cada bloc de treball i a evitar que s'introdueixin notes al lloc equivocat.

## 7.4. Accions contextuals dins de cada bloc de `Notes`

Damunt de cada taula d'un aparell i exercici, solen apareixer dues accions molt importants:

- `Camps i funcions`
- `Jurat / QRs`

`Camps i funcions`

Porta directament a la configuracio del model de puntuacio d'aquell aparell.

Conve fer-lo servir quan:

- falta un camp
- algun calcul no es comporta com s'esperava
- cal revisar la manera com s'obte el total

`Jurat / QRs`

Porta a la pantalla on es creen els accessos dels jutges per a aquell aparell.

Conve fer-lo servir quan:

- s'ha d'afegir un jutge nou
- s'ha de donar un QR amb permisos concrets
- s'ha de revisar qui pot introduir quin camp

## 7.5. La taula central de `Notes`

La taula central es la zona on l'organitzacio veu l'estat de la puntuacio.

Segons l'aparell i el tipus de configuracio, hi poden apareixer:

- dades de la persona o unitat competitiva
- camps editables
- camps calculats
- indicadors de multimedia
- controls de crash o tall, quan pertoqui

### Com s'ha de llegir la taula

La idea mes practica es aquesta:

- les files representen les persones o unitats
- les columnes representen dades, notes parcials o totals

Algunes columnes son d'entrada.

Altres son de resultat.

Per tant, no tot el que es veu s'edita manualment.

## 7.6. Botons i elements visibles dins de la taula de `Notes`

### `Columnes`

Aquest boto obre el selector de columnes visibles.

Normalment hi ha accions com:

- `Mostrar-ho tot`
- `Amagar-ho tot`
- `Tancar`

Serveix per adaptar la taula al que es necessita en aquell moment.

Per exemple:

- una vista curta per seguir el directe
- una vista detallada per revisar parcials

### Nom clicable de la inscripcio o subjecte

El nom pot obrir el context de reproduccio multimedia associat a aquella persona o unitat.

Serveix per anar rapidament a la seva musica, video o fitxers associats.

### Indicadors de multimedia

Quan una fila te multimedia associat, solen apareixer distintius o botons petits que indiquen que hi ha pistes disponibles.

Aixo ajuda a no haver d'endivinar qui te arxius associats i qui no.

### Control de crash

En camps on s'ha activat aquesta logica, pot apareixer un petit control per marcar el punt de tall.

Per a l'usuari, la idea important es:

- no es un valor decoratiu
- pot canviar quins items es tenen en compte en el calcul

### Camps readonly

Algunes caselles es mostren nomes per lectura.

Solen correspondre a:

- resultats calculats
- totals
- valors que depenen d'altres dades

## 7.7. Calaix de reproduccio multimedia

La pantalla de `Notes` inclou un calaix lateral de reproduccio.

Quan s'obre, l'usuari pot trobar:

- audio principal
- altres audios
- video principal
- altres videos
- video de jutge, si existeix

Tambe hi ha un reproductor integrat per escoltar o veure el fitxer seleccionat.

### Que fa aquest calaix

Serveix per centralitzar la consulta de materials sense sortir de la taula de notes.

Es especialment util quan:

- cal verificar la musica d'una persona
- cal revisar un video
- cal comparar el fitxer associat amb el que s'esta puntuant

### Exemple senzill

Una participant te una sola pista d'audio. L'usuari obre el calaix, comprova el fitxer i continua.

### Exemple mes complex

Una unitat te audio, video i video de jutge. El calaix permet saltar d'una pista a una altra sense abandonar la pantalla de notes.

## 7.8. Actualitzacions i comportament en viu del panell de `Notes`

El panell de `Notes` esta pensat per treballar de manera viva.

Aixo vol dir que la pantalla pot reflectir canvis que venen d'altres punts del sistema, com ara:

- entrades des del portal del jutge
- nous videos de jutge
- actualitzacions de totals

Per a l'usuari, el mes important es entendre que:

- no sempre cal refrescar manualment la pagina
- alguns indicadors poden canviar mentre la pantalla esta oberta

## 7.9. Pantalla `Jurat / QRs`

Aquesta pantalla serveix per crear, imprimir, revisar i revocar accessos de jutges.

A dalt hi sol haver:

- selector d'`Aparell`
- boto `Imprimir QRs`
- accio per tornar a `Notes`
- accio `Suport jutges`

### Selector d'aparell

Serveix per decidir per quin aparell s'estan creant o revisant els accessos.

Es important no oblidar aquest punt, perque els tokens es creen sempre dins del context d'un aparell concret.

### `Imprimir QRs`

Obre una versio preparada per imprimir tots els codis actius de l'aparell seleccionat.

Conve fer-ho quan:

- s'han de repartir codis en paper
- es vol preparar una carpeta de pista
- es vol tenir un recurs de reserva si falla algun dispositiu

## 7.10. Crear un token de jutge

La zona de `Crear token` es la mes delicada de tota la pantalla, perque aqui es decideix exactament que podra fer aquell QR.

Normalment hi ha aquests camps i controls:

- `Etiqueta`
- l'opcio `Permetre boto "Gravar" per aquest QR`
- la taula de `Permisos`
- `Afegir camp`
- `Crear token`

### `Etiqueta`

Serveix per posar un nom clar al token.

Es molt recomanable posar etiquetes entenedores, per exemple:

- `Execucio J1`
- `Dificultat pista A`
- `Cap de jurat`

Una bona etiqueta evita errors quan s'han de repartir diversos accessos.

### `Permetre boto "Gravar" per aquest QR`

Si aquesta opcio esta activada, el portal del jutge mostrara la possibilitat de gravar video des del dispositiu.

Si no esta activada:

- el jutge no veura aquesta opcio
- el QR sera nomes per entrada de notes

### La taula de permisos

Cada fila de permis defineix una part del treball que aquell QR podra tocar.

Les columnes habituals son:

- `Camp`
- `Abast`
- `Membres`
- `Jutge`
- `Start`
- `Count`
- `Eliminar`

### `Camp`

Indica sobre quin bloc de nota treballara aquest QR.

### `Abast`

Especialment en aparells d'equip, ajuda a distingir si el permis actua sobre una part compartida o sobre valors de membres concrets.

### `Membres`

Quan l'aparell es d'equip, pot apareixer la possibilitat de limitar el permis a:

- tots els membres
- un membre concret
- un subconjunt de membres

### `Jutge`

Serveix per indicar a quina posicio de jurat correspon aquest acces.

### `Start` i `Count`

Serveixen per limitar a quina part d'un camp amb diversos items te acces aquell QR.

En llenguatge practic:

- `Start` diu on comenca
- `Count` diu quants valors consecutius entren dins del permis

### `Eliminar`

Marca que aquella fila de permis s'ha de treure abans de crear el token.

### `Afegir camp`

Afegeix una nova fila de permis a la taula.

Es util quan un mateix QR ha de poder introduir mes d'un bloc de dades.

### `Crear token`

Genera el nou acces amb totes les regles definides.

Si falta algun permis real o la configuracio es inconsistent, la pantalla avisa abans de continuar.

### Exemple senzill

Es crea un token anomenat `Execucio J1` amb un unic camp i sense video. El jutge nomes podra introduir la seva part concreta.

### Exemple mitja

Es crea un token que pot introduir dos camps diferents per al mateix aparell. Aixo pot ser util quan un mateix dispositiu cobreix mes d'una dada.

### Exemple complex

En un aparell d'equip, es crea un QR limitat a certs membres i a un tram concret d'items. Aquest nivell de detall evita que un jutge vegi o modifiqui dades que no li pertoquen.

## 7.11. Llista de tokens existents

La columna o taula de `Tokens existents` serveix per revisar l'estat del que ja s'ha creat.

Per cada token es poden veure:

- l'etiqueta
- l'identificador
- si esta `Actiu`, `Inactiu` o `Revocat`
- si te `Video ON` o `Video OFF`
- el resum dels permisos
- les accions `Obrir`, `QR` i `Revocar`

### `Obrir`

Obre directament el portal del jutge amb aquell token.

Es molt util per provar que el QR fa exactament el que s'espera abans de lliurar-lo.

### `QR`

Obre el codi QR corresponent.

Serveix per:

- descarregar-lo
- imprimir-lo
- ensenyar-lo a un dispositiu

### `Revocar`

Desactiva aquell acces.

Conve fer-ho quan:

- un dispositiu deixa de ser valid
- s'ha creat un token incorrecte
- s'ha acabat la necessitat d'aquell QR

## 7.12. Centre `Suport jutges`

La pantalla de suport serveix per centralitzar converses i incidencies.

L'organitzacio hi troba tres peces principals:

- `Instruccio puntual`
- la llista de `Converses`
- el fil de missatges de la conversa activa

### `Instruccio puntual`

Permet enviar un missatge directe a un token concret sense haver d'esperar que el jutge obri una incidencia.

Flux habitual:

1. seleccionar el token
2. escriure el missatge
3. premer `Enviar instruccio`

### Llista de converses

Mostra les converses ordenades per prioritat i activitat.

L'usuari hi veu, per exemple:

- qui ha escrit
- l'estat de la conversa
- un resum del darrer missatge
- si hi ha missatges pendents de llegir

### Accions sobre la conversa activa

`Acceptar`

Serveix per indicar que l'organitzacio ja ha vist la peticio i l'esta tractant.

`Marcar resolta`

Serveix per tancar operativament la incidencia.

`Enviar`

Permet respondre dins del fil obert.

### Exemple senzill

Un jutge demana ajuda. L'organitzacio entra al centre de suport, obre la conversa, respon una instruccio breu i la marca com atesa.

### Exemple mes complex

Diversos jutges escriuen alhora. La llista de converses ajuda a veure primer les que estan demanant assistencia i a ordenar les respostes sense perdre el fil.

## 7.13. El portal del jutge

El `Portal del jutge` es la pantalla que s'obre quan el jutge escaneja el seu QR o entra amb el seu enllac.

A la capcalera hi pot veure:

- el nom de la competicio
- l'aparell
- la seva etiqueta de token
- l'exercici inicial obert
- un avis si hi ha una franja forzada

Tambe hi pot haver:

- `Tornar a notes`, si s'esta provant des d'organitzacio
- boto de `Navegacio`
- boto `SOS`

### `Camps autoritzats`

La pantalla mostra sempre quins camps pot tocar aquell QR.

Aixo es molt important per al jutge, perque li deixa clar:

- quina part del treball li pertoca
- que no te acces a tot

## 7.14. El panell d'inscripcions dins del portal del jutge

Dins del portal, les persones o unitats es mostren en targetes.

La navegacio es basa en:

- grups
- targetes de persones o equips
- xips d'exercici com `Ex1`, `Ex2`, etc.

### Pestanyes de grup

Funcionen com al panell de notes: separen el treball per blocs.

Si hi ha grups fora de programa, poden sortir marcats com a `Fora`.

### Navegacio lateral o desplegable

El portal inclou una navegacio per:

- inscripcio, en proves individuals
- equip, en proves d'equip

Serveix per trobar rapidament la targeta correcta, especialment des de mobil.

### Xips d'exercici

Cada targeta te xips com `Ex1`, `Ex2` i similars.

Aquests xips serveixen per obrir l'exercici concret que es vol puntuar.

La seva aparenca pot canviar segons l'estat:

- buit
- pendent de desar
- desat

Per a l'usuari, aixo es una ajuda visual rapida per saber que queda per fer.

## 7.15. Accions visibles dins de cada targeta del portal del jutge

Cada exercici obert dins d'una targeta pot mostrar:

- els camps editables autoritzats
- l'estat de desat
- els controls de video, si estan permesos
- `Copia anterior`
- `Desa`

### `Copia anterior`

Serveix per copiar les dades de l'exercici anterior.

Conve utilitzar-lo amb prudencia, nomes quan realment la continuacio de dades tingui sentit.

### `Desa`

Guarda el que el jutge ha introduit en aquell exercici.

Es l'accio principal del portal.

### Estat de desat

La pantalla pot mostrar missatges que indiquen si la dada:

- s'esta desant
- s'ha desat correctament
- te algun problema

## 7.16. Gravacio de video des del portal del jutge

Si el token te video activat, el portal mostra:

- `Gravar`
- `Pujar`
- `Regravar`
- un estat del video
- una previsualitzacio

### `Gravar`

Inicia la captura de video des del dispositiu.

Quan esta en marxa, el boto canvia de comportament per permetre aturar la gravacio.

### `Pujar`

Envia el video capturat al sistema.

Normalment nomes s'activa quan ja hi ha una gravacio preparada.

### `Regravar`

Serveix per descartar la gravacio actual i tornar-la a fer.

### `Sense video`

Es l'estat inicial quan encara no hi ha cap enregistrament.

### `Gravacio desactivada per aquest QR`

Si surt aquest missatge, vol dir que aquell token no te permis per treballar amb video.

### Exemple senzill

Un jutge te un QR nomes per notes. No veu cap control de video i la pantalla queda mes neta.

### Exemple mes complet

Un altre jutge te permis per gravar. Fa una captura, la revisa, la puja i, si no queda be, la regrava abans de desar definitivament.

## 7.17. Suport des del portal del jutge

El boto `SOS` obre el calaix de suport.

Dins d'aquest calaix, el jutge pot trobar:

- un fil de missatges
- el boto `Solicitar assistencia`
- un camp de text per escriure
- el boto `Enviar`

### `Solicitar assistencia`

Envia una peticio rapida d'ajuda a organitzacio.

Es la via mes directa quan hi ha una incidencia de pista o de dispositiu.

### Camp de text i `Enviar`

Permeten afegir context a la peticio o continuar una conversa ja oberta.

### Punt important

La peticio rapida no s'ha d'usar com a xat constant, sino com a recurs de suport quan realment cal atencio de l'organitzacio.

## 7.18. `QR Public` i portal public de classificacions

Des de `Notes`, l'organitzacio pot entrar a `QR public`.

Aquesta pantalla serveix per crear accessos de comparticio per a la vista publica de classificacions.

L'usuari hi troba:

- `Crear token public`
- l'opcio `Permetre media publica`
- la taula de `Tokens existents`
- `Imprimir QRs`

### `Crear token public`

Genera un enllac compartible per a la classificacio live publica.

### `Permetre media publica`

Serveix per decidir si aquell acces public podra veure materials publicables quan estiguin disponibles.

Es una opcio que s'ha d'activar nomes quan es vulgui expressament aquest nivell de visibilitat.

### Accions sobre tokens publics

`Obrir`

Obre la vista publica normal.

`Loop`

Obre la versio pensada per a pantalla continua.

`QR`

Mostra el codi per compartir l'acces.

`Revocar`

Desactiva aquell acces public.

### Exemple senzill

Es crea un token per a una pantalla del pavello. S'obre `Loop` i es deixa projectat durant tota la jornada.

### Exemple mes complex

Es creen diversos accessos publics: un per la pantalla principal, un altre per una pantalla secundaria i un tercer de reserva. Si cal, algun es revoca sense afectar la resta.

## 7.19. Recomanacio de flux per a `Notes`, `Jurat` i portals

Un flux molt segur i clar acostuma a ser aquest:

1. revisar que aparells, camps i funcions estiguin ben configurats
2. comprovar a `Notes` que els grups i exercicis visibles siguin els correctes
3. crear els QRs de jutge aparell per aparell
4. provar cada token amb `Obrir` abans de repartir-lo
5. decidir quins QRs poden gravar video i quins no
6. deixar obert `Suport jutges` durant la competicio
7. usar el `QR public` nomes quan les classificacions ja estiguin llestes per ser compartides

## 7.20. Dos recorreguts complets

### Cas molt senzill

1. L'organitzacio entra a `Notes`.
2. Revisa un sol grup, un sol aparell i un sol exercici.
3. Crea un QR de jutge amb un permis molt concret.
4. Prova el portal amb `Obrir`.
5. El jutge introdueix dades i desa.
6. L'organitzacio comprova el resultat a `Classificacions en viu`.

### Cas mes complet

1. Hi ha diversos grups, alguns fora de programa i aparells amb mes d'un exercici.
2. L'organitzacio fa servir `Notes` per seguir el directe i el calaix multimedia per verificar materials.
3. Crea diferents QRs per camps, jutges i permisos d'equip.
4. Activa video nomes als accessos que realment ho necessiten.
5. Mante obert `Suport jutges` per atendre incidencies.
6. Comparteix la classificacio amb `QR public` en mode normal o `Loop`.

---

# 8. Tancament

Si es fa servir amb aquest ordre, el programa es deixa entendre millor:

- Inscripcions per preparar la base
- Rotacions per convertir la base en horari real
- Classificacions per convertir les notes en resultats visibles

Aquest document es una base extensa per al manual d'usuari i es pot ampliar mes endavant amb altres blocs del programa.

# Manual d'usuari del programa de competicions

## Abast del manual

Aquest manual descriu el funcionament de tres blocs clau del programa, en aquest ordre:

1. Inscripcions
2. Rotacions
3. Classificacions

Està escrit per a persones usuàries, no per a personal tècnic. Per això s'explica què es veu a la pantalla, què fa cada botó i com resoldre les situacions habituals i les més avançades.

Segons els permisos de cada usuari i segons la configuració de cada competició, alguns botons poden no aparèixer o poden quedar desactivats.

## 1. Inscripcions

### 1.1. Per a què serveix

La pantalla d'Inscripcions és el centre de preparació de la competició. Des d'aquí es pot:

- importar participants des d'Excel
- afegir, editar o eliminar inscripcions
- cercar i filtrar
- dividir la llista en pestanyes
- ordenar la sortida
- crear i mantenir grups
- crear i mantenir equips
- preparar sèries d'equip
- pujar i relacionar fitxers multimèdia
- exportar la informació a Excel

### 1.2. Què hi trobaràs en entrar

La pantalla es divideix en quatre zones principals:

- capçalera superior
- barra de cerca
- calaix lateral d'accions
- taula central d'inscripcions

La capçalera mostra:

- el nom de la competició
- el nombre d'inscrits visibles
- `+ Importar Excel`
- `+ Afegir inscripció`
- `Configuració competició`
- `Tornar a competicions`
- `Notes`
- `Rotacions`

### 1.3. Botons i accions de la capçalera

`+ Importar Excel`

- obre la pantalla d'importació
- permet carregar un fitxer Excel
- si una persona ja existeix a la competició, el sistema l'actualitza en lloc de duplicar-la
- en acabar, mostra un resum amb quants registres s'han creat, actualitzat o ignorat

`+ Afegir inscripció`

- obre el formulari manual
- serveix per donar d'alta una nova persona sense passar per Excel

`Configuració competició`

- porta a la pantalla general de configuració
- és útil quan cal revisar aparells o altres paràmetres generals abans de continuar

`Tornar a competicions`

- torna a la llista de competicions creades

`Notes`

- obre la zona de puntuació

`Rotacions`

- obre el planificador de rotacions

### 1.4. Barra de cerca

A sota de la capçalera hi ha un cercador amb:

- camp de text
- botó `Cerca`
- botó `Netejar`, quan hi ha una cerca activa

La cerca està pensada per trobar ràpidament persones per nom, cognoms, document o entitat.

Efectes visibles:

- la taula es redueix als resultats trobats
- el comptador superior indica quants participants s'estan mostrant
- apareix una marca visual amb el text filtrat

### 1.5. Ordre de competició

A la part superior de la zona de treball hi ha el control `Ordre de competició`.

Quan s'activa:

- s'afegeix com a criteri final de les ordenacions que ja tens actives
- el resultat es desa com a ordre de sortida

Quan està desactivat o bloquejat:

- és perquè encara no hi ha cap ordenació aplicada

Quan està actiu:

- apareix un avís indicant que l'ordre actual ja incorpora aquest criteri final

### 1.6. Calaix lateral d'accions

El lateral es pot obrir i tancar amb:

- `Amagar accions`
- `Mostrar accions`

També inclou:

- `Desfer`
- `Refer`

Aquestes dues accions serveixen per recuperar o repetir canvis recents de gestió.

Les seccions del lateral són:

- Divisions
- Columnes
- Grups
- Equips
- Sèries d'equip
- Multimèdia
- Altres

#### 1.6.1. Divisions

Aquesta secció serveix per separar la taula en pestanyes o subconjunts.

Hi trobaràs:

- `Aplicar divisió`
- `Barreja aleatòriament`
- `Treure divisió`
- una llista de camps marcables a `Divideix per`

Què fa cada acció:

`Aplicar divisió`

- reorganitza la llista segons els camps marcats
- pot crear pestanyes com ara categoria, subcategoria, entitat o altres camps disponibles

`Barreja aleatòriament`

- remou l'ordre actual dins del context visible
- és útil quan es vol repartir sense seguir l'ordre original

`Treure divisió`

- elimina la divisió activa
- torna a mostrar la taula en una sola vista

`Divideix per`

- permet marcar un o diversos camps
- si marques més d'un camp, la divisió es torna més específica

Configuració de forquilles de data de naixement

- apareix quan es fa servir la divisió per franges o forquilles de naixement
- permet definir etiquetes com `Sense data` o `Fora de forquilla`
- permet afegir files de rangs i desar-les

Casos habituals:

- dividir per categoria per veure una pestanya per cada categoria
- dividir per categoria i subcategoria per obtenir pestanyes més concretes

Casos avançats:

- preparar forquilles de dates per separar participants per any o rang de naixement
- combinar divisions i ordenacions per construir blocs molt específics

#### 1.6.2. Columnes

Aquesta secció controla quines columnes es veuen i en quin ordre.

Hi trobaràs:

- `Tot`
- `Cap`
- `Per defecte`
- `Desar columnes`

Com funciona:

- pots marcar i desmarcar columnes
- pots arrossegar-les per canviar l'ordre
- en desar, la taula queda configurada amb aquesta presentació

És especialment útil quan:

- vols una vista curta per treballar ràpid
- vols una vista completa abans d'exportar

#### 1.6.3. Grups

La secció de grups té dos nivells:

- accions ràpides
- workspace ampliat

Accions ràpides:

- triar `Abast`
- triar `Grup destí`
- `Crear grup nou amb selecció`
- `Assignar selecció`
- `Treure selecció`
- `Obrir workspace`

El camp `Abast` pot treballar sobre:

- `Selecció actual`
- `Visibles filtrades`

El workspace de grups amplia molt més el control. Hi trobaràs tres zones:

- subconjunt d'inscripcions
- accions
- grups existents i previsualització

Subconjunt d'inscripcions:

- cerca
- filtres per categoria, subcategoria, entitat i estat de grup
- `Seleccionar visibles`
- `Afegir visibles`
- `Treure visibles`
- `Importar selecció del llistat`
- `Netejar selecció`
- navegació `Anterior` i `Següent`

Accions manuals:

- triar abast
- triar grup destí
- escriure un nom nou de grup
- `Previsualitzar creació`
- `Crear grup nou`
- `Assignar a grup`
- `Treure del grup`
- `Desactivar grup buit`

Accions automàtiques:

- seleccionar blocs d'origen resolts
- configurar com es reparteixen les persones
- `Crear X grups`
- `Previsualitzar`
- `Crear per mida`
- `Equilibrats min-max`
- `Crear X amb min-max`
- `1 grup per cada bloc resolt`

Part de resultats:

- llista de grups existents
- `Desactivar buits`
- previsualització d'impacte
- resum de grups programats i fora de programa

Avisos i bloquejos importants:

- si hi ha rotacions actives, buidar un grup programat pot quedar bloquejat
- si una acció toca grups que ja estan programats, el sistema pot mostrar avisos
- abans d'aplicar canvis grans, és recomanable usar la previsualització

#### 1.6.4. Equips

La secció `Fer Equips` també té accions ràpides i workspace ampliat.

Accions ràpides:

- triar `Context`
- triar `Abast`
- triar `Equip destí`
- escriure nom de nou equip
- `Crear equip nou amb selecció`
- `Assignar selecció`
- `Treure selecció`
- `Obrir workspace`
- `Obrir sèries d'equip`

El workspace d'equips es divideix en:

- subconjunt d'inscripcions
- accions automàtiques i manuals
- resultat previst i equips del context

Detalls del context:

- selector de context
- `Nou context`
- `Renombrar context`
- `Eliminar context`
- selecció dels aparells globals d'equip
- `Desar aparells d'equip`

Accions automàtiques:

- escollir camps per particionar
- `Reassignar equips existents`
- `Previsualitzar`
- `Crear equips automàticament`

Accions manuals:

- escriure nom
- `Crear equip nou i assignar selecció`
- triar equip existent
- `Assignar selecció a aquest equip`
- `Treure equip de la selecció`

Manteniment d'equips:

- `Mode tauler`
- `Eliminar buits`
- `Eliminar tots`

Bloquejos i avisos:

- el context base no es pot renombrar
- el context base no es pot eliminar
- per crear equips automàticament cal marcar almenys un camp de partició
- per a moltes accions manuals cal tenir almenys una inscripció seleccionada

#### 1.6.5. Sèries d'equip

Aquesta secció només té sentit quan hi ha aparells d'equip actius.

Zona compacta:

- selector d'`Aparell`
- `Refrescar`
- `Start list`
- camp de nom opcional
- `Crear sèrie buida`
- `Crear amb selecció`
- `Treure selecció`
- `Obrir workspace`

Workspace ampli:

- selector d'aparell
- `Refrescar`
- `Desactivar buides`
- `Crear sèrie buida`
- `Crear amb selecció`
- `Treure selecció`
- `Start list`

Panell d'unitats competitives:

- cerca
- filtres per context, estat i sèrie
- `Seleccionar visibles`
- `Netejar selecció`
- `Anterior`
- `Següent`

Panell de sèries creades:

- resum per sèrie
- `Assignar selecció`
- `Veure detall` o `Amagar detall`
- `Renombrar`
- `Full de treball`
- `Desactivar`

Regles importants:

- només es poden desactivar sèries buides
- el programa pot avisar si un aparell d'equip encara no té contextos font configurats
- si no hi ha selecció, es pot crear una sèrie buida però no una sèrie amb contingut

#### 1.6.6. Multimèdia

La part de multimèdia permet relacionar fitxers amb inscripcions.

Hi trobaràs:

- selector de carpeta
- `Previsualitzar match`
- `Aplicar assignacions`
- resum de coincidències
- taula de propostes

La lògica d'ús és:

1. carregar una carpeta de fitxers
2. demanar una previsualització
3. revisar coincidències automàtiques, dubtoses o sense assignar
4. aplicar les assignacions

A més, dins de la mateixa taula central cada inscripció pot tenir:

- llista de fitxers
- botó per marcar un fitxer com a principal
- botó per eliminar-lo
- camp per pujar un fitxer
- botó `Pujar`

#### 1.6.7. Altres

És la secció de manteniment i exportació.

Hi trobaràs:

- `Exportar Excel`
- resum de criteris d'ordenació actius
- botons per treure criteris
- selecció de columnes per a l'Excel

També és on es treballen les ordenacions avançades de columna:

- ordenació ascendent
- ordenació descendent
- ordenació amb fletxa
- ordre personalitzat
- àmbit de l'ordenació
- filtres per valors de columna

Quan obres el menú d'una columna, pots trobar:

- `Aplicar`
- `Ordre custom`
- `Reset custom`
- `Carregar`
- `Netejar filtre`
- `Aplicar filtre`

L'ordre personalitzat obre una finestra amb:

- llista de valors detectats
- arrossegar per reordenar
- `Reset custom`
- `Tancar`
- `Desar ordre`

### 1.7. La taula central

La taula és on es veu i es manipula la llista.

Elements importants:

- casella de selecció per fila
- nansa d'arrossegar
- grups visuals dins de la taula
- pestanyes quan hi ha divisió activa
- menú de cada grup
- menú de cada columna

Accions per fila:

- seleccionar-la
- arrossegar-la per canviar l'ordre
- `Editar`
- `Eliminar`

Segons les columnes visibles, també pots trobar:

- equip actual
- grup actual
- ordre de sortida
- selector d'aparells per aquella inscripció
- multimèdia

Columna d'aparells:

- permet activar o desactivar en quins aparells participa aquella persona

Columna de multimèdia:

- mostra els fitxers associats
- deixa pujar fitxers manuals
- permet marcar-ne un com a principal

### 1.8. Accions sobre grups des de la taula

Quan la taula està agrupada per grup numèric, cada capçalera de grup ofereix:

- `Veure ordre competició`
- `Desar ordre competició`
- `Editar nom`

També pot aparèixer una marca com:

- `Ordre no desat`

Què vol dir:

- l'ordre visual que veus a la taula encara no s'ha guardat com a ordre definitiu de competició per a aquell grup

Quan hi ha pestanyes, també pots trobar:

- `Fer grup independent de la pestanya`

Serveix per convertir el contingut d'una pestanya o subpestanya en un grup propi.

### 1.9. Pantalles complementàries

#### Importar inscripcions

La pantalla d'importació és simple:

- camp per pujar l'Excel
- `Cancel·la`
- `Importar`

Abans de pujar-lo, la pantalla recorda:

- quines columnes bàsiques espera
- que els documents repetits actualitzen
- que no és bona idea usar noms de columna que entrin en conflicte amb camps ja existents

#### Afegir o editar inscripció

La pantalla de formulari mostra:

- dades bàsiques
- camps addicionals, si n'hi ha
- `Desar`
- `Cancelar`

Si s'està treballant amb equips per context, el formulari també indica:

- si s'està editant l'equip base
- o si s'està assignant un equip dins d'un context concret

#### Eliminar inscripció

- obre una pantalla de confirmació
- en confirmar, la inscripció desapareix de la llista

### 1.10. Missatges habituals

Durant l'ús poden aparèixer missatges com:

- importació correcta amb resum de creats, actualitzats i ignorats
- error de cerca o de càrrega
- guardat correcte
- no s'ha pogut aplicar una ordenació
- no s'ha pogut calcular una previsualització
- selecció insuficient per executar una acció
- bloqueig perquè hi ha rotacions actives

### 1.11. Exemples d'ús

#### Exemple senzill

Objectiu: importar participants i revisar-los.

1. Entrar a `Inscripcions`.
2. Prémer `+ Importar Excel`.
3. Carregar el fitxer i importar-lo.
4. Tornar a la llista.
5. Fer servir `Cerca` per trobar una persona concreta.

#### Exemple intermedi

Objectiu: separar la competició per categoria i ordenar millor la sortida.

1. Obrir `Divisions`.
2. Marcar `Categoria`.
3. Prémer `Aplicar divisió`.
4. Obrir el menú d'una columna rellevant.
5. Aplicar una ordenació.
6. Si cal, activar `Ordre de competició`.

#### Exemple avançat

Objectiu: crear grups, equips i sèries d'equip abans de passar a rotacions.

1. Dividir la llista perquè sigui més còmode treballar.
2. Obrir `Grups` i preparar una selecció.
3. Fer una `Previsualització` del repartiment.
4. Crear o assignar grups.
5. Obrir `Equips`, escollir context i preparar equips.
6. Revisar el `Resultat previst` abans d'aplicar.
7. Obrir `Sèries d'equip` i crear les sèries necessàries.
8. Exportar a Excel si vols fer una revisió externa.

## 2. Rotacions

### 2.1. Per a què serveix

La pantalla de Rotacions serveix per construir l'horari de pas per franges i estacions.

És la pantalla on es decideix:

- quins grups o sèries d'equip passen per cada lloc
- a quina hora ho fan
- quina seqüència segueixen
- quin document Excel es vol generar per imprimir o compartir

### 2.2. Estructura general de la pantalla

La pantalla està dividida en tres columnes:

- esquerra: elements programables i eines de preparació
- centre: programa en forma de graella
- dreta: exportació Excel

A la capçalera hi ha:

- `Ajuda`
- `Inscripcions`
- `Notes`
- `Configuració`

### 2.3. Resum de fora de programa

A sobre de la zona principal hi ha un resum de `Fora de programa`.

Aquest resum indica:

- quants elements existeixen però encara no estan situats al programa
- quants subjectes hi ha afectats

Serveix per detectar ràpidament:

- grups creats però no programats
- sèries d'equip encara no col·locades

### 2.4. Columna esquerra: elements programables i eines

#### Elements programables

Aquí es mostren:

- `Programats`
- `Fora de programa`
- `Utilitats`

`Programats`

- llista d'elements que ja tenen algun lloc dins la graella

`Fora de programa`

- llista d'elements que existeixen però encara no han estat col·locats

`Utilitats`

- inclou l'element `(Buit)`
- serveix per deixar una cel·la sense assignació

També hi ha el control:

`Mostrar grups fora de programa a notes i jutges`

Quan està activat:

- aquests elements també apareixen a les pantalles de competició relacionades amb notes i jutges

Quan està desactivat:

- només es veuen al planificador de rotacions

#### Afegir franja

Hi ha tres camps:

- hora d'inici
- hora de fi
- títol

I el botó:

- `+`

Serveix per crear una fila nova manualment.

Si falten hores o són incorrectes:

- el programa mostra un error i no crea la franja

#### Generar franges automàticament

Hi trobaràs:

- hora d'inici
- hora de fi
- minuts d'interval
- títol base
- casella `Esborrar franges existents abans de generar`
- botó `Generar franges`

És la manera més ràpida de muntar una jornada sencera.

Com funciona:

- crea tantes franges com càpiguen dins del tram indicat
- les anomena amb el títol base i un número
- si marques l'opció d'esborrar, elimina les franges anteriors abans de començar

#### Afegir descans

Hi ha el botó:

- `+ Descans`

No crea una fila nova.

Crea una columna nova de descans, és a dir:

- una estació més dins la graella
- útil per programar torns de pausa

### 2.5. Zona central: la graella del programa

La graella combina:

- files = franges
- columnes = estacions

Cada cel·la pot contenir:

- un o diversos grups
- una o diverses sèries d'equip
- quedar buida

La pantalla recorda:

- que es pot arrossegar `(Buit)` per esborrar una cel·la

També hi ha el botó global:

- `Netejar Programa`

Quan es fa servir:

- s'esborren totes les assignacions
- també desapareixen les franges del programa
- és una acció gran i demana confirmació

### 2.6. Accions sobre les estacions

A la capçalera de cada columna hi ha:

- el nom de l'estació
- botó `×` per eliminar-la

A més, les capçaleres es poden arrossegar:

- això serveix per canviar l'ordre de les estacions
- en guardar-se, la graella adopta aquest nou ordre de columnes

Quan s'intenta posar un element incorrecte en una estació:

- el sistema mostra un avís
- per exemple, no permet col·locar on no toca un element que no correspon a aquell tipus d'estació

### 2.7. Accions sobre cada franja

Cada fila de franja té:

- títol
- hores
- selector `Ordre`

El selector `Ordre` permet triar entre tres maneres de comportar-se:

- `Mantenir`
- `Aleatori`
- `Primer passa a últim`

Què signifiquen:

`Mantenir`

- conserva l'ordre de pas tal com estava

`Aleatori`

- canvia l'ordre intern d'aquella franja de manera estable per a aquella situació

`Primer passa a últim`

- fa una rotació del pas per repartir millor les primeres posicions

Botons ràpids de la franja:

- `Editar`
- `Inserir després`
- `Netejar franja`
- `Extrapolar`
- `Eliminar`

`Editar`

- obre una finestra petita per canviar títol i hores
- en desar, les franges de sota s'ajusten automàticament per continuar encadenades

`Inserir després`

- crea una nova franja immediatament a sota
- li dona la mateixa durada que la franja base
- desplaça les següents en horari

`Netejar franja`

- deixa totes les cel·les d'aquella fila en blanc
- no elimina la franja

`Extrapolar`

- demana quantes franges següents vols omplir
- copia el patró de la franja actual i el va desplaçant per les estacions
- si falten franges, en crea de noves

`Eliminar`

- elimina aquella franja
- després relliga les següents perquè no quedi un forat horari

### 2.8. Com es fan les assignacions

La pantalla funciona arrossegant elements cap a les cel·les.

Pots fer:

- arrossegar un grup o una sèrie a una cel·la
- arrossegar diversos elements a la mateixa cel·la
- arrossegar `(Buit)` per buidar-la
- eliminar només un element concret d'una cel·la

Guardat:

- els canvis es desen automàticament
- la part inferior de la graella mostra missatges com `Guardant...` o `Guardat`

### 2.9. Columna dreta: exportació Excel

La part dreta està dedicada a l'exportació.

Hi trobaràs:

- menú `Excel`
- `Exportar participants`
- `Exportar grups`
- configuració de dades d'exportació

#### Menú Excel

`Exportar participants`

- genera un Excel on dins de cada cel·la es mostren les persones que hi passen

`Exportar grups`

- genera un Excel resumit amb els grups o sèries assignades

#### Dades export Excel

Pots configurar:

- títol de la competició
- seu
- data
- camps de participants
- logo

Botons disponibles:

- `Pujar logo`
- `Treure`
- `Desar dades export`

`Camps de participants`

- es poden marcar o desmarcar
- es poden arrossegar per definir l'ordre
- afecten l'Excel de participants

Missatges habituals:

- `Desant dades export...`
- `Dades export guardades.`
- `Pujant logo...`
- `Logo actualitzat.`
- `Logo eliminat.`

Bloquejos habituals:

- si no tries cap fitxer, no es pot pujar un logo
- si el logo és massa gran o no és una imatge, el sistema el rebutja

### 2.10. Ajuda contextual

La pantalla disposa de molts botons `Ajuda` i `?`.

Serveixen per explicar:

- visió general
- grups
- afegir franges
- generació automàtica
- descansos
- programa
- canvis manuals
- franges i estacions
- exportació
- dades d'exportació
- camps de participants
- mode d'ordre de franja
- accions de franja

### 2.11. Missatges i avisos habituals

Durant el treball poden aparèixer missatges com:

- `Guardant...`
- `Guardat`
- `Ordre columnes guardat`
- `Programa netejat`
- `Creat X franges`
- `Visibilitat guardada`
- `Mode d'ordre de franja guardat`
- `Extrapolat`
- errors de franja, estació o exportació

### 2.12. Exemples d'ús

#### Exemple senzill

Objectiu: muntar una rotació petita a mà.

1. Afegir una franja manual.
2. Afegir un descans si cal.
3. Arrossegar un grup a cada cel·la.
4. Revisar els elements `Fora de programa`.
5. Exportar en format de grups.

#### Exemple intermedi

Objectiu: generar un matí complet.

1. Omplir l'inici, el final i l'interval.
2. Prémer `Generar franges`.
3. Reordenar estacions si convé.
4. Omplir les primeres franges.
5. Fer servir `Extrapolar`.

#### Exemple avançat

Objectiu: preparar una competició amb equips i documents finals.

1. Programar grups individuals i sèries d'equip segons correspongui.
2. Activar o no la visibilitat dels elements fora de programa per a jutges i notes.
3. Ajustar el mode d'ordre de cada franja.
4. Posar descansos com a estacions.
5. Configurar títol, seu, data, camps i logo.
6. Exportar tant participants com grups.

## 3. Classificacions

### 3.1. Per a què serveixen

La part de Classificacions té tres usos diferents:

- configurar com es calcula una classificació
- previsualitzar si la configuració dona el resultat esperat
- publicar-la en viu

Per això hi ha tres pantalles principals:

- configurador
- classificacions en viu
- mode loop

### 3.2. Abans de començar

Si la competició encara no té aparells actius:

- el programa no et deixarà crear classificacions
- et redirigirà primer a la configuració dels aparells

### 3.3. Pantalla de configuració

La pantalla de configuració és un editor complet.

Té:

- capçalera superior
- barra de plantilles
- llista de configuracions a l'esquerra
- editor detallat a la dreta

#### Botons principals de la capçalera

- `Configuració`
- `Plantilles globals`
- `+ Afegir`
- `Guardar`
- `Eliminar`

`+ Afegir`

- crea una classificació nova

`Guardar`

- desa la configuració oberta
- mostra un missatge de guardat correcte

`Eliminar`

- elimina la classificació actual
- demana confirmació

#### Barra de plantilles

Hi trobaràs:

- selector `Les meves plantilles...`
- `Recarregar`
- `Comprovar`
- `Aplicar`
- `Desar com plantilla`

`Recarregar`

- actualitza la llista de plantilles disponibles

`Comprovar`

- revisa si la plantilla encaixa amb la competició actual
- pot mostrar errors i avisos

`Aplicar`

- crea una nova configuració a partir de la plantilla
- si hi ha avisos, pot demanar una confirmació addicional

`Desar com plantilla`

- guarda la classificació actual com a plantilla reutilitzable

#### Llista de configuracions

A l'esquerra apareixen totes les classificacions creades.

Des d'aquí pots:

- veure quantes n'hi ha
- seleccionar-ne una per editar-la
- canviar d'una configuració a una altra

### 3.4. Editor detallat

L'editor està organitzat en aquest ordre:

1. Metadades
2. Particions
3. Puntuació
4. Desempat
5. Filtres
6. Presentació

També hi ha:

- botó `Ajuda`
- navegació interna per blocs
- botó flotant per tornar a dalt

### 3.5. Metadades

Serveixen per identificar la classificació.

Camps habituals:

- `Nom`
- `Tipus`
- `Activa`

En classificacions d'equip també poden aparèixer:

- `Context d'equips`
- `Mode d'equips`

Què ha de decidir l'usuari aquí:

- com s'anomena la classificació
- si està activa o no
- si és individual o d'equips

### 3.6. Particions

Aquest bloc defineix en quins blocs visibles es divideix la sortida final.

Hi pots trobar:

- selecció i ordre de camps de partició
- grups personalitzats
- forquilles de data de naixement
- configuració d'equips, si escau

Botons i accions visibles:

- marcar i desmarcar camps
- reordenar-los
- `+ Partició` en classificacions d'equip
- afegir o treure forquilles de naixement

Opcions específiques d'equip:

- `Incloure participants sense equip`
- llista de particions manuals

### 3.7. Puntuació

És el bloc més important.

Aquí es decideix:

- quins aparells entren
- quins camps compten
- com se sumen o combinen
- quins exercicis es tenen en compte
- com s'agrega el resultat final

Elements visibles:

- selecció d'aparells
- selecció de camps per aparell
- `Agregació camps`
- `Base de selecció`, en alguns modes d'equip
- `Selecció exercicis`
- `Mode d'exercicis`
- camp `N`
- camp `Índex`
- camp `Max N per participant`
- `Agregació exercicis`
- `Llista d'índexs`
- `Agregació entre aparells`
- `Ordre principal`
- `Resultat per aparell`

Quan `Resultat per aparell` està en mode de victòries, apareixen blocs extra:

- `Configuració de victòries`
- `Desempat intern de comparació`

Botons visibles en aquesta zona:

- `+ Afegir criteri` dins dels desempats interns

### 3.8. Desempat

Aquest bloc serveix per resoldre empats finals.

Hi trobaràs una taula amb:

- aparells
- camp
- exercicis
- participants
- ordre
- accions

Botó principal:

- `+ Afegir criteri`

També hi ha una zona avançada de text per a casos especials.

### 3.9. Filtres

Aquest bloc decideix qui entra a la classificació abans del càlcul.

Camps habituals:

- entitats
- categories
- subcategories
- grups

També hi ha una zona avançada per a filtres més detallats.

### 3.10. Presentació

Aquest bloc controla com es veu la classificació final.

Hi trobaràs:

- `Top N`
- `Mostrar empats`
- `Previsualitzar`
- `+ Builtin`
- `+ Camp`
- caixa de previsualització

`Previsualitzar`

- calcula una simulació de la sortida
- si la classificació encara no s'ha guardat, avisa que primer s'ha de desar

`+ Builtin`

- afegeix una columna estàndard de presentació

`+ Camp`

- afegeix una columna basada en un camp disponible

La caixa de previsualització és clau per validar:

- si la classificació té sentit
- si les columnes es veuen bé
- si els blocs i els empats surten com s'espera

### 3.11. Ajuda contextual

El configurador inclou molts botons `?` i `Ajuda`.

Serveixen per explicar, entre altres:

- visió general
- metadades
- tipus
- particions
- equips
- puntuació
- aparells i camps
- agregacions
- selecció d'exercicis
- victòries
- desempat
- filtres
- presentació
- previsualització

### 3.12. Missatges i avisos del configurador

És habitual veure:

- confirmació de guardat correcte
- errors de validació
- avisos de compatibilitat
- avisos en aplicar plantilles
- errors si falta informació imprescindible
- errors si una plantilla no encaixa amb la competició actual

### 3.13. Classificacions en viu

La vista en viu està pensada per consultar resultats que es van actualitzant soles.

Hi trobaràs:

- estat de connexió
- última actualització
- pestanyes de classificació activa

Botons principals:

- `Excel (tot)`
- `Excel (pestanya)`
- `Notes`
- `Configurar`
- `Inscripcions`

Com funciona:

- cada classificació activa apareix com una pestanya
- dins de cada pestanya hi pot haver diverses particions
- el programa actualitza el contingut automàticament quan canvien notes o configuracions

Si no hi ha classificacions actives:

- mostra un avís i no es veuen resultats

### 3.14. Mode loop

El mode loop està pensat per mostrar classificacions en rotació automàtica.

És útil per:

- una pantalla gran
- un monitor de públic
- una projecció contínua

Què mostra:

- nom de classificació
- partició actual
- pàgina actual
- nombre de files

Botons visibles, si s'entra com a organització:

- `Notes`
- `Live tabs`
- `Configurar`

Com funciona:

- va passant automàticament per classificacions, particions i pàgines
- també es va actualitzant quan arriben canvis nous

### 3.15. Exportació Excel de classificacions

Des de la vista en viu es pot exportar:

- tot el conjunt de classificacions
- només la pestanya activa

És útil per:

- lliurar resultats
- fer revisions externes
- guardar una foto fixa del moment

### 3.16. Exemples d'ús

#### Exemple senzill

Objectiu: crear una classificació general individual.

1. Entrar a `Classificacions`.
2. Prémer `+ Afegir`.
3. Posar un nom com `General`.
4. Deixar `Tipus` en individual.
5. Seleccionar els aparells i camps necessaris.
6. Guardar.
7. Prémer `Previsualitzar`.

#### Exemple intermedi

Objectiu: crear classificacions separades per categoria.

1. Duplicar o crear una configuració nova.
2. Anar a `Particions`.
3. Afegir `Categoria`.
4. Revisar `Filtres` si cal limitar participants.
5. Guardar i previsualitzar.
6. Obrir `Classificacions en viu` i comprovar les pestanyes.

#### Exemple avançat

Objectiu: preparar una classificació d'equips amb publicació contínua.

1. Crear una classificació de tipus equips.
2. Escollir context i mode d'equips.
3. Ajustar les particions manuals si cal.
4. Configurar puntuació, agregacions i desempats.
5. Definir `Top N`, empats i columnes visibles.
6. Guardar i previsualitzar.
7. Si el resultat és correcte, obrir la vista en viu.
8. Si es necessita una pantalla rotatòria, obrir també el `Mode loop`.

## 4. Recomanacions de treball

- Comença sempre per Inscripcions i deixa neta la base de participants abans de tocar Rotacions o Classificacions.
- Fes servir les previsualitzacions abans d'aplicar canvis grans a grups, equips o classificacions.
- Si una pantalla mostra avisos de programació activa, revisa primer Rotacions abans de buidar o reassignar grups.
- Desa sovint les configuracions de Classificacions abans de previsualitzar.
- Exporta a Excel quan necessitis revisar amb altres persones el resultat d'un pas important.

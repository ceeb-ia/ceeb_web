# Manual d'usuari del programa de competicions

## Abast d'aquest document

Aquest manual explica, amb llenguatge d'usuari, tres blocs clau del programa:

1. Inscripcions
2. Rotacions
3. Classificacions

L'objectiu es que qualsevol persona de l'organitzacio pugui entendre que veu a pantalla, que fa cada boto, en quin ordre conve treballar i quins comportaments normals o especials es pot trobar.

## Ordre recomanat de treball

L'ordre natural de feina dins del programa es aquest:

1. Preparar les Inscripcions
2. Construir les Rotacions
3. Publicar i revisar les Classificacions

Aquest ordre es important perque moltes decisions de les pantalles posteriors depenen del que ja s'ha deixat preparat abans.

# 1. Inscripcions

## 1.1. Per a que serveix aquesta pantalla

La pantalla d'Inscripcions es el centre de preparacio de la competicio. Des d'aqui pots:

- importar participants des d'Excel
- afegir o editar inscripcions a ma
- dividir el llistat en pestanyes o blocs
- crear i gestionar grups
- crear i gestionar equips
- preparar series d'equip
- decidir en quins aparells competeix cada inscripcio
- pujar fitxers multimedia
- ordenar i filtrar la taula
- exportar el resultat a Excel

En la practica, es la pantalla on poses ordre abans de passar a rotacions i al directe.

## 1.2. Que veu l'usuari quan entra

A la part superior normalment hi trobara:

- el nom de la competicio
- el recompte d'inscrits
- el boto `+ Importar Excel`
- el boto `+ Afegir inscripcio`
- el boto `Configuracio competicio`
- el boto `Tornar a competicions`
- accessos rapids a `Notes` i `Rotacions`

Just sota hi ha:

- una barra de cerca
- un resum del nombre de participants visibles
- un interruptor relacionat amb l'ordre de competicio

La pantalla es divideix en dues zones grans:

- a l'esquerra o en un lateral, el panell d'accions
- al centre, la taula principal d'inscripcions

## 1.3. Botons principals de la capcalera

### `+ Importar Excel`

Serveix per carregar un fitxer Excel amb participants.

Que fa:

- crea inscripcions noves quan no existeixen
- actualitza inscripcions ja existents quan identifica la mateixa persona
- mostra un resum del que s'ha creat, actualitzat o ignorat

Que es veu a la pantalla d'importacio:

- camp per triar el fitxer
- boto `Importar`
- boto `Cancella`

Comportaments importants:

- si el fitxer porta columnes amb noms que poden confondre el sistema, apareix un avis
- si una persona ja existeix, el sistema intenta actualitzar-la en lloc de duplicar-la
- en acabar, es mostra un resum amb creats, actualitzats, ignorats i casos ambigus

Exemple senzill:

- tens 20 participants nous en un Excel
- prems `+ Importar Excel`
- selecciones el fitxer
- prems `Importar`
- tornes a la llista amb els 20 participants carregats

Exemple mes avancat:

- tornes a importar un Excel corregit
- algunes persones ja hi eren
- el programa actualitza les dades coincidents i nomes crea les que falten

### `+ Afegir inscripcio`

Obre el formulari manual per crear una inscripcio.

Que hi trobes:

- dades basiques de la persona
- camps addicionals si la competicio en fa servir
- boto `Desar`
- boto `Cancelar`

Comportaments importants:

- segons el context d'equips actiu, el formulari pot indicar si estas editant l'equip base o una assignacio d'un context concret
- si tries opcions del tipus `Altres`, poden apareixer camps extra per escriure el valor manualment

### `Configuracio competicio`

Porta a la configuracio general. Des d'Inscripcions es fa servir sobretot com a acces rapid quan necessites revisar aparells, estructura o altres dades generals.

### `Notes`

Et porta al modul on es registren notes. Normalment no s'utilitza fins que Inscripcions i Rotacions ja estan prou preparades.

### `Rotacions`

Obre el planificador de rotacions. Acostuma a ser el pas seguent quan grups i series ja tenen sentit.

## 1.4. Buscador i comptadors

### Barra de cerca

Botons visibles:

- `Cerca`
- `Netejar`

Que fa:

- filtra rapidament per nom, cognoms, document o entitat
- actualitza el recompte de participants visibles

### Interruptor d'ordre de competicio

Serveix per afegir l'ordre de competicio com a ultim criteri quan ja estas aplicant ordenacions.

Conve saber:

- no te sentit encendre'l si abans no hi ha cap ordenacio activa
- ajuda a conservar una coherencia final quan s'han fet diverses ordenacions parcials

## 1.5. Panell `Divisions`

Aquest panell serveix per separar el llistat en pestanyes o blocs de treball.

Botons principals:

- `Aplicar divisio`
- `Barreja aleatoriament`
- `Treure divisio`

Opcions principals:

- caselles `Divideix per:` amb camps com categoria, subcategoria, entitat, sexe o forquilles de data
- configuracio de forquilles de data de naixement
- botons `Afegir forquilla` i `Desar forquilles`

Que fa cada accio:

- `Aplicar divisio`: reorganitza la llista segons els camps marcats
- `Barreja aleatoriament`: mante la divisio activa pero barreja l'ordre intern
- `Treure divisio`: torna a una vista sense aquesta separacio
- `Afegir forquilla`: crea un nou interval de dates
- `Desar forquilles`: guarda la configuracio dels intervals

Exemple senzill:

- marques `Categoria`
- prems `Aplicar divisio`
- la taula queda separada per categories

Exemple avancat:

- actives la divisio per `Forquilla data naixement`
- defineixes diversos intervals
- guardes les forquilles
- reapliques la divisio

## 1.6. Panell `Columnes`

Serveix per decidir quines columnes es veuen i en quin ordre.

Botons principals:

- `Tot`
- `Cap`
- `Per defecte`
- `Desar columnes`

Que permet:

- marcar o desmarcar columnes
- arrossegar-les per canviar-ne l'ordre

## 1.7. Panell `Grups`

Es el lloc per construir grups de competicio i revisar-ne l'impacte abans d'aplicar canvis.

### Accions rapides

Botons:

- `Crear grup nou amb seleccio`
- `Assignar seleccio`
- `Treure seleccio`
- `Obrir workspace`

Serveixen per fer canvis rapids sobre:

- la seleccio actual
- o totes les inscripcions visibles filtrades

### Workspace de grups

Dins del gestor ampli es veu:

- zona de filtres
- llista de candidates
- eines de seleccio
- mode `Manual`
- mode `Automatic`
- resum de grups existents
- area de `Previsualitzacio d'impacte`

#### Accions de seleccio

Botons:

- `Seleccionar visibles`
- `Afegir visibles`
- `Treure visibles`
- `Importar seleccio del llistat`
- `Netejar seleccio`
- `Anterior`
- `Seguent`

#### Mode manual

Botons:

- `Previsualitzar creacio`
- `Crear grup nou`
- `Assignar a grup`
- `Treure del grup`
- `Desactivar grup buit`

Que fan:

- `Previsualitzar creacio`: t'ensenya com quedaria el canvi
- `Crear grup nou`: crea un grup nou i hi mou la seleccio
- `Assignar a grup`: envia la seleccio a un grup existent
- `Treure del grup`: deixa aquestes inscripcions sense grup
- `Desactivar grup buit`: retira un grup que ja no te participants

#### Mode automatic

Botons i opcions visibles:

- `Seleccionar tots`
- `Netejar`
- `Crear X grups`
- `Previsualitzar`
- `Crear per mida`
- `Equilibrats min-max`
- `Crear X amb min-max`
- `1 grup per cada bloc resolt`
- selector de `Fallback`

Exemple senzill:

- selecciones 12 participants
- prems `Crear grup nou`
- el programa crea un grup amb aquelles 12 persones

Exemple mitja:

- tens 32 participants filtrats
- vas a automatic
- poses `Crear X grups = 4`
- previsualitzes
- si t'agrada el resultat, l'apliques

Avis important:

- si un grup ja esta implicat a rotacions, el programa pot bloquejar o advertir alguns canvis per evitar deixar la planificacio incoherent

## 1.8. Panell `Equips`

Aquest espai serveix per crear equips dins d'un context concret i mantenir-los sense dependre del llistat principal.

### Accions rapides

Botons:

- `Crear equip nou amb seleccio`
- `Assignar seleccio`
- `Treure seleccio`
- `Obrir workspace`
- `Obrir series d'equip`

### Workspace d'equips

Dins del gestor ampli normalment hi trobes:

- selector de context
- boto `Detalls`
- botons `Nou context`, `Renombrar context`, `Eliminar context`
- llista d'aparells d'equip del context
- boto `Desar aparells d'equip`
- filtres de candidates
- eines de seleccio
- mode `Automatic`
- mode `Manual`
- previsualitzacio
- llista d'equips existents

#### Gestio de context

Botons:

- `Nou context`
- `Renombrar context`
- `Eliminar context`
- `Desar aparells d'equip`

#### Seleccio de candidates

Botons:

- `Seleccionar visibles`
- `Afegir visibles`
- `Treure visibles`
- `Importar seleccio del llistat`
- `Netejar seleccio`
- `Anterior`
- `Seguent`

#### Mode automatic

Botons:

- `Previsualitzar`
- `Crear equips automaticament`

Opcions:

- camps de particio
- opcio `Reassignar equips existents`
- abast sobre filtrades o sobre la seleccio del modal

#### Mode manual

Botons:

- `Crear equip nou i assignar seleccio`
- `Assignar seleccio a aquest equip`
- `Treure equip de la seleccio`

Exemple senzill:

- selecciones tres persones
- escrius un nom
- prems `Crear equip nou i assignar seleccio`

Exemple mitja:

- filtres per categoria i entitat
- marques camps de particio
- prems `Previsualitzar`
- comproves l'impacte
- prems `Crear equips automaticament`

Avisos importants:

- el context natiu acostuma a tenir limitacions especials: no sempre es pot renombrar o eliminar
- abans d'eliminar equips o contextos, el programa acostuma a demanar confirmacio

## 1.9. Panell `Series d'equip`

Aquest panell organitza les unitats competitives dels aparells d'equip en series que despres es poden programar o utilitzar a notes i rotacions.

Botons principals de la vista compacta i del workspace:

- `Refrescar`
- `Start list`
- `Crear serie buida`
- `Crear amb seleccio`
- `Treure seleccio`
- `Obrir workspace`
- `Desactivar buides`
- `Seleccionar visibles`
- `Netejar seleccio`
- `Anterior`
- `Seguent`

Que fan:

- `Crear serie buida`: crea l'estructura encara que encara no hi hagi equips dins
- `Crear amb seleccio`: crea una serie i hi posa la seleccio actual
- `Treure seleccio`: treu equips de la seva serie
- `Desactivar buides`: neteja series sense contingut
- `Start list`: exporta el llistat d'inici

Avis important:

- una serie programada no sempre es pot desactivar lliurement

## 1.10. Panell `Fitxers multimedia`

Serveix per vincular audio, video o imatges a les inscripcions.

### Assignacio assistida per carpeta

Botons:

- `Previsualitzar match`
- `Aplicar assignacions`

Que fa:

- llegeix una carpeta local
- intenta associar cada fitxer amb una inscripcio
- marca si la proposta es automatica, si s'ha de revisar o si no ha trobat cap coincidencia

### Pujada manual per fila

A la columna de multimedia de cada inscripcio pots trobar:

- llistat de fitxers ja vinculats
- boto `Pujar`
- boto per marcar com a principal
- boto per eliminar fitxer

## 1.11. Panell `Altres`

Aqui s'agrupen eines de suport.

Botons principals:

- `Exportar Excel`
- `Netejar ordenacions`
- eines de columna per `Aplicar`, `Ordre custom`, `Reset custom`, `Carregar`, `Aplicar filtre`, `Netejar filtre`

Que permet:

- ordenar tota la taula o una part
- crear ordres manuals de valors
- filtrar per valors d'una columna concreta
- exportar el resultat a Excel

## 1.12. Accions directes dins la taula

### Per fila

Accions habituals:

- casella de seleccio
- nansa per arrossegar
- `Editar`
- `Eliminar`
- selector d'aparells
- gestio de fitxers multimedia

### Per grup

A la fila de capcalera del grup hi pot haver:

- `Veure ordre competicio`
- `Desar ordre competicio`
- `Editar nom`

## 1.13. Desfer i refer

A la zona d'accions hi ha:

- `Desfer`
- `Refer`

Serveixen per recuperar estats recents del treball dins d'Inscripcions.

## 1.14. Avisos i situacions especials a Inscripcions

Comportaments que l'usuari pot trobar:

- no es poden deixar buits certs grups si ja formen part del programa de rotacions
- algunes eliminacions demanen confirmacio forta
- algunes accions poden quedar bloquejades si la seleccio es buida
- una previsualitzacio et pot avisar que tocaras grups o equips ja utilitzats
- alguns canvis no es desen fins que prems explicitament `Desar`

# 2. Rotacions

## 2.1. Per a que serveix aquesta pantalla

Rotacions es la pantalla on es construeix el programa de pas per franges i estacions.

En altres paraules:

- defineixes el temps
- defineixes els punts del programa
- colloques grups o series a cada casella
- ajustes l'ordre intern
- exportes el resultat

## 2.2. Que veu l'usuari quan entra

La pantalla mostra normalment:

- capcalera amb el nom de la competicio
- botons `Inscripcions`, `Notes` i `Configuracio`
- una zona amb grups o series pendents
- una zona per crear franges
- una taula gran de programa, amb franges a un eix i estacions a l'altre
- una area d'exportacio a Excel

## 2.3. Botons principals de la capcalera

### `Inscripcions`

Torna al modul on es preparen grups, equips i series.

### `Notes`

Porta al directe de notes.

### `Configuracio`

Acces rapid a la configuracio general.

### `Ajuda`

Obre textos de suport dins la mateixa pantalla. Es especialment util per entendre la diferencia entre franges, estacions, ordre i exportacio.

## 2.4. Gestio de franges

### Crear una franja manualment

Botons i camps:

- camp de titol
- hora d'inici
- hora de final
- boto `+` per afegir franja

### Crear franges automaticament

Camps i boto:

- hora inici
- hora fi
- interval en minuts
- titol base
- boto `Crear franges`

Que fa:

- genera una cadena de franges consecutives
- si l'interval no encaixa al final, no crea una ultima franja a mitges

Exemple senzill:

- poses 09:00 a 11:00
- marques 30 minuts
- prems `Crear franges`
- el sistema crea quatre franges de 30 minuts

### Accions dins cada franja

Botons visibles a cada capcalera de franja:

- `Editar`
- `Inserir despres`
- `Netejar franja`
- `Extrapolar`
- `Eliminar`

Que fa cada una:

- `Editar`: canvia titol i hores
- `Inserir despres`: crea una nova franja just a continuacio
- `Netejar franja`: buida totes les caselles d'aquella franja
- `Extrapolar`: fa correr el patro de la franja a les seguents
- `Eliminar`: elimina la franja i reajusta les posteriors

Exemple avancat:

- tens una primera franja ben muntada
- prems `Extrapolar`
- el programa crea o omple les seguents franges fent girar el contingut d'una estacio a la seguent

## 2.5. Gestio d'estacions

### `+ Descans`

Afegeix una estacio de descans al programa.

### Eliminar una estacio

A la capcalera de cada estacio hi ha un boto per eliminar-la.

Que passa:

- desapareix la columna
- s'esborren les assignacions que tenia

### Reordenar estacions

Les estacions es poden moure d'ordre.

Per a l'usuari aixo significa:

- canvia la disposicio visual del programa
- pot canviar l'ordre en que es mostren a l'exportacio

## 2.6. Omplir el programa

La taula central es el cor de Rotacions.

Que s'hi fa:

- arrossegar grups o series a les caselles
- deixar una casella buida
- canviar el contingut d'una casella
- guardar el resultat

### `Guardar`

Aquest boto desa el programa actual.

Que veu l'usuari:

- missatge de `Guardant...`
- despres `Guardat.` si tot va be

### `Netejar Programa`

Es una accio forta.

Que fa:

- elimina tot el contingut del programa
- elimina les franges actuals

Comportament:

- demana confirmacio abans d'actuar
- no es una accio pensada per fer servir a la lleugera

## 2.7. Mode d'ordre dins cada franja

A cada franja hi ha un selector de mode d'ordre.

Opcions habituals:

- `Mantenir`
- `Aleatori`
- `Primer passa a ultim`

Que vol dir a la practica:

- `Mantenir`: conserva l'ordre intern
- `Aleatori`: barreja l'ordre
- `Primer passa a ultim`: va rotant qui surt primer

## 2.8. Grups fora de programa

La pantalla pot mostrar si hi ha grups o series que encara no s'han collocat.

Hi ha una opcio per desar la visibilitat d'aquests elements.

Que aporta:

- ajuda a controlar que no es quedi res sense programar
- evita pensar que el programa ja esta tancat quan encara hi ha blocs pendents

## 2.9. Exportacio a Excel

### Menu `Excel`

Opcions visibles:

- `Exportar participants`
- `Exportar grups`

Diferencia principal:

- `Exportar participants`: mostra el detall de les persones dins cada casella
- `Exportar grups`: mostra el resum per grup o serie

### Dades export Excel

Camps i botons:

- titol
- seu
- data
- selector de camps de participants
- `Pujar logo`
- `Treure`
- `Desar dades export`

Que fan:

- personalitzen l'aspecte de l'Excel
- decideixen quina informacio surt dins cada casella
- afegeixen o treuen el logo de la capcalera

Exemple senzill:

- poses titol i data
- selecciones que es vegi `Nom i cognoms`
- prems `Desar dades export`
- exportes l'Excel

Exemple avancat:

- puges el logo de l'organitzacio
- tries diversos camps de participants
- exportes una versio per pantalla tecnica i una altra per paper

## 2.10. Missatges i comportaments normals a Rotacions

Missatges habituals:

- `Guardant...`
- `Guardat.`
- `Ordre columnes guardat.`
- `Programa netejat.`
- `Extrapolat.`
- errors si falta alguna hora o si el format d'hora es incorrecte

Bloquejos o errors habituals:

- no pots crear franges si l'hora final no es posterior a la inicial
- no pots extrapolar una franja buida
- no pots exportar amb dades incoherents sense corregir abans el programa

# 3. Classificacions

## 3.1. Per a que serveix aquesta pantalla

Classificacions te tres usos principals:

1. definir com es calcula cada classificacio
2. previsualitzar si la configuracio dona el resultat esperat
3. publicar el resultat en viu, en mode pestanyes, en mode loop o en mode public

## 3.2. Les tres cares de Classificacions

### Constructor

Es la pantalla on es creen i s'editen classificacions.

### Live

Es la vista en directe amb pestanyes.

### Loop

Es la vista que va passant sola per classificacions i particions.

### Portal public

Es la mateixa idea de live o loop, pero compartida mitjancant un enllac o un QR public.

## 3.3. Quan entres al constructor

L'usuari veu habitualment:

- llista de configuracions a l'esquerra
- editor complet a la dreta
- botons superiors per crear, guardar o eliminar
- una franja de plantilles
- un boto `Ajuda`
- navegacio interna per seccions

Si no hi ha aparells actius a la competicio:

- el programa no deixa crear classificacions
- t'envia primer a preparar els aparells de competicio

## 3.4. Botons principals del constructor

### `Configuracio`

Torna a la configuracio general.

### `Plantilles globals`

Porta a la biblioteca general de plantilles.

### `+ Afegir`

Crea una classificacio nova.

### `Guardar`

Desa la configuracio actual.

Comportament visible:

- surt un missatge curt de confirmacio
- si hi ha algun error de configuracio, no desa i mostra el problema

### `Eliminar`

Elimina la configuracio actual.

Comportament:

- demana confirmacio abans d'esborrar

## 3.5. Gestio de plantilles

La zona de plantilles te:

- selector `Les meves plantilles...`
- `Recarregar`
- `Comprovar`
- `Aplicar`
- `Desar com plantilla`

Que fa cada boto:

- `Recarregar`: torna a carregar la llista de plantilles
- `Comprovar`: diu si una plantilla encaixa amb la competicio actual
- `Aplicar`: crea una classificacio nova a partir d'una plantilla
- `Desar com plantilla`: guarda la configuracio actual per reutilitzar-la

Comportaments importants:

- si una plantilla no encaixa del tot, el sistema pot avisar i proposar una aplicacio mes assistida
- l'usuari pot veure avisos abans de confirmar
- una classificacio nova aplicada des de plantilla sol quedar inactiva al principi, per revisar-la abans de publicar-la

## 3.6. La llista de configuracions

A l'esquerra hi ha la llista de classificacions creades.

Que hi mostra:

- nom
- tipus
- si esta activa o inactiva
- alguns avisos de compatibilitat o d'herencia antiga

Ordre de visualitzacio:

- la vista live i la vista loop segueixen l'ordre en que aquestes configuracions estan guardades
- la primera configuracio activa acostuma a ser la primera que es veu al live

## 3.7. Seccio `Metadades`

Aqui es defineix:

- `Nom`
- `Tipus`
- si esta `Activa`

Quan el tipus es `Equips`, poden apareixer opcions extra:

- context d'equips
- mode d'equips

Que significa per a l'usuari:

- `Nom`: el text que veuras a les pestanyes del live
- `Tipus`: si la classificacio ordena persones o equips
- `Activa`: si es publica o queda amagada del live

## 3.8. Seccio `Particions`

Serveix per dividir una mateixa classificacio en subblocs visibles.

Exemples de particio:

- per categoria
- per subcategoria
- per forquilla de data de naixement
- per combinacions de diversos camps

Botons i accions:

- afegir o treure nivells de particio
- pujar o baixar nivells
- definir grups manuals dins una particio
- `+ Particio` en configuracions d'equips
- `+ Forquilla` en les forquilles de naixement

Que aporta:

- en lloc d'una unica taula gran, pots obtenir diverses taules petites
- facilita publicar classificacions separades sense duplicar la logica de calcul

## 3.9. Seccio `Puntuacio`

Es el bloc central del constructor.

Aqui decideixes:

- quins aparells entren
- quins camps es fan servir
- com es trien els exercicis
- com se sumen o comparen els resultats

Elements visibles habituals:

- llista d'aparells per marcar
- selectors de camps per aparell
- `Base de seleccio`
- `Seleccio exercicis`
- `Mode d'exercicis`
- camps com `N`, `Index`, `Max N per participant`
- diferents tipus d'agregacio

Que significa en llenguatge planer:

- tries d'on surt la nota
- decideixes si comptes tots els exercicis o nomes alguns
- decideixes si ho sumes, fas mitjana o un altre criteri

Casos habituals:

- classificacio general: sumes el resultat dels aparells seleccionats
- classificacio que nomes compta el millor exercici
- classificacio d'equips on primer es mira cada membre i despres es suma
- classificacio d'equips on es treballa sobre un sac comu amb limit per membre

Avisos visibles:

- hi ha missatges de compatibilitat si barreges coses que no tenen sentit
- hi ha advertiments si un camp no es pot fer servir directament per puntuar

## 3.10. Seccio `Desempat`

Aquesta part serveix per decidir com es resolen els empats.

Botons:

- `+ Afegir criteri`
- a cada fila: pujar, baixar, eliminar

Que pots definir:

- sobre quin aparell es mira
- quin camp es compara
- quins exercicis compten
- en quin ordre s'apliquen aquests criteris

## 3.11. Seccio `Filtres`

Serveix per decidir qui entra a la classificacio abans de calcular-la.

Filtres visibles:

- entitats
- categories
- subcategories
- grups

Que fa:

- no canvia la forma de calcular
- canvia qui participa en aquell calcul

## 3.12. Seccio `Presentacio`

Es la part on decideixes com es veura el resultat.

Elements principals:

- `Top N`
- `Mostrar empats`
- `Previsualitzar`
- `+ Builtin`
- `+ Camp`

Que fan:

- `Top N`: limita quantes posicions es mostren
- `Mostrar empats`: decideix si els empats es mantenen visibles
- `Previsualitzar`: calcula una vista de prova
- `+ Builtin`: afegeix columnes estandard, com posicio, nom o punts
- `+ Camp`: afegeix columnes mes especifiques

Exemple senzill:

- vols ensenyar nomes el podi
- poses `Top N = 3`
- prems `Previsualitzar`

Exemple avancat:

- afegeixes columnes de detall per aparell
- mantens el live mes ric per pantalla gran o public

## 3.13. Ajuda contextual i avisos del constructor

Al llarg del constructor hi ha molts botons `Ajuda` o `?`.

Per a que serveixen:

- expliquen que fa cada bloc
- donen exemples d'us
- avisen de combinacions poc recomanables

Altres avisos que l'usuari pot veure:

- configuracio invalida
- problemes de compatibilitat
- classificacio que ha quedat desfasada i necessita revisio
- avisos especials quan una plantilla s'aplica amb adaptacions

## 3.14. Previsualitzacio

El boto `Previsualitzar` es clau per treballar be.

Que fa:

- calcula el resultat amb la configuracio guardada
- mostra les particions resultants
- ensenya les columnes tal com es veurien al live

Que passa si la configuracio encara no esta desada:

- la previsualitzacio et pot demanar que guardis primer

Bona practica:

- canvia una cosa
- guarda
- previsualitza
- nomes quan el resultat sigui correcte, activa la classificacio

## 3.15. Vista `Live`

La vista live es la presentacio en directe amb pestanyes.

Que veu l'usuari:

- una pestanya per cada classificacio activa
- dins de cada pestanya, una o diverses particions
- estat de connexio
- hora de l'ultima actualitzacio

Botons visibles:

- `Excel (tot)`
- `Excel (pestanya)`
- `Notes`
- `Configurar`
- `Inscripcions`

Que fan:

- `Excel (tot)`: exporta totes les classificacions actives
- `Excel (pestanya)`: exporta nomes la classificacio actual
- `Notes`: torna al directe de notes
- `Configurar`: obre el constructor
- `Inscripcions`: torna a la preparacio de participants

Comportament clau:

- s'actualitza automaticament quan canvien notes o configuracions
- si no hi ha classificacions actives, ho indica clarament

## 3.16. Vista `Loop`

La vista loop esta pensada per pantalles o projectors.

Que fa:

- va passant automaticament per les classificacions actives
- si una classificacio te diverses particions, les va mostrant una darrere l'altra
- si hi ha moltes files, les reparteix en pagines

Botons visibles:

- `Notes`
- `Live tabs`
- `Configurar`

Exemple d'us:

- tens diverses categories
- actives el loop en una pantalla gran
- el programa va rotant per totes elles automaticament

## 3.17. Portal public

El portal public permet compartir la classificacio sense entrar al panell intern.

Normalment es prepara des de la zona de QR public.

Alla l'usuari organitzador pot:

- `Crear token`
- `Imprimir QRs`
- `Obrir`
- `Loop`
- `QR`
- `Revocar`

Que significa cada opcio:

- `Crear token`: genera un acces public nou
- `Obrir`: obre la versio publica live
- `Loop`: obre la versio publica en rotacio automatica
- `QR`: mostra el codi QR d'aquell acces
- `Revocar`: anulla el token

Tambe hi ha una opcio per permetre o no la visualitzacio de multimedia publica.

Exemple senzill:

- crees un token per a la pantalla del pavello
- prems `QR`
- el projectes o l'imprimeixes

## 3.18. Ordre de visualitzacio a Classificacions

L'usuari final veu:

1. les classificacions actives
2. dins de cada classificacio, les particions
3. dins de cada particio, les files ordenades segons la logica definida

En mode live:

- l'ordre es veu en pestanyes

En mode loop:

- el sistema va passant per aquest mateix ordre de manera automatica

## 3.19. Avisos i situacions especials a Classificacions

Situacions normals que poden apareixer:

- no hi ha cap classificacio activa
- la configuracio no es valida i no es pot guardar
- una plantilla es pot aplicar, pero amb avisos
- una classificacio d'equips pot demanar revisar el context o el mode
- una previsualitzacio pot sortir buida si els filtres no deixen cap participant

Bona practica:

- primer crear
- despres guardar
- despres previsualitzar
- finalment activar i publicar

## Tancament

Si es treballa en aquest ordre:

1. Inscripcions ben preparades
2. Rotacions coherents
3. Classificacions revisades i publicades

el programa respon com un flux molt logic i estable. La majoria d'errors d'us no venen de botons complicats, sino de voler saltar-se aquest ordre o de voler publicar abans d'haver revisat la previsualitzacio.

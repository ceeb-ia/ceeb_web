# Informe narratiu i tecnic de la V1 de calendaritzacions

## Introduccio

Aquest document reescriu l'analisi anterior en un format mes narratiu i mes exhaustiu. La idea no es nomes enumerar peces del codi, sino explicar quin model de negoci implementa la V1, com va passant de les dades d'entrada al resultat final, i quins punts son especialment importants si s'ha de plantejar una v2.

La primera conclusio que surt de la lectura del repositori es que la V1 no es un simple script que reparteix equips de manera mes o menys automatica. Tampoc es un solver formalitzat d'una manera del tot neta. Es una solucio heuristica amb coneixement de domini real: te una idea clara de que significa un numero de sorteig, intenta mantenir coherencia de casa i fora entre categories, incorpora criteris d'equilibri entre entitats, tracta de separar equips del mateix club i, a segona fase, prova de fer servir classificacions previes.

Per tant, el valor de la V1 no esta nomes en el fet que "funciona", sino en que ha anat condensant decisions operatives que ja responen a necessitats reals. El problema principal del sistema no es que la logica sigui pobra. El problema es que aquesta logica esta molt repartida entre heuristiques, molt acoblada amb la capa de reporting i massa concentrada a pocs punts del codi.

Aquest informe s'ha basat en la revisio de:

- `app.py`
- `main.py`
- `assignacions.py`
- `consulta_resultats.py`
- `logs.py`
- `map_modalitat_nom.csv`
- exemples de sortida a `csv_generats/`

No s'ha modificat cap fitxer de codi del programa. L'unic resultat nou d'aquest treball es aquest document.

## 1. Com esta organitzat avui el programa

Vist des de fora, el projecte sembla tenir quatre blocs: una API, un motor d'assignacio, una integracio amb classificacions externes i una sortida final en Excel. Aquesta visio es correcta, pero incompleta, perque el pes real del sistema no esta gaire repartit.

### 1.1. `app.py`: la porta d'entrada

`app.py` exposa una API FastAPI amb un esquema bastant directe:

- rep una ruta de fitxer
- engega el processament en segon pla
- desa l'estat a Redis
- permet consultar el progrés
- permet descarregar el resultat

Els endpoints principals son:

- `POST /process_async`
- `POST /process_async_segona_fase`
- `GET /status/{job_id}`
- `GET /download/{job_id}`

Ja aqui es veu una primera caracteristica del disseny actual: la primera i la segona fase no estan modelades com una mateixa operacio parametrizable, sino com dos circuits molt semblants que conviuen en paral lel.

### 1.2. `main.py`: el centre real del producte

Tot i que existeix una API, el cervell del sistema es `main.py`. En aquest fitxer hi viu gairebe tot el que, en una arquitectura mes separada, estaria repartit en diversos serveis o capes:

- lectura i validacio de l'Excel
- generacio d'identificadors
- normalitzacio de dades
- resolucio global de peticions `CASA/FORA`
- consulta de classificacions externes a segona fase
- bucle per categories
- crida al motor d'assignacio
- construccio de validacions
- generacio de l'Excel final

En la practica, `main.py` no es nomes l'orquestrador. Es alhora capa d'aplicacio, capa de negoci, capa d'integracio i capa de sortida. Aquest es un dels punts mes importants a retenir de cara a una v2.

### 1.3. `assignacions.py`: el motor d'assignacio

`assignacions.py` conte la part mes algorismica:

- calcul del nombre de grups
- construccio dels slots
- calcul de costos
- execucio de l'algoritme hongares
- reparacio de conflictes d'entitat
- homogenietzacio posterior

Es el fitxer que mes s'assembla al nucli del solver, pero fins i tot aqui la logica no es completament autonoma: depen de decisions que s'han pres abans a `main.py`, especialment el mapping de `CASA/FORA` a numeros concrets.

### 1.4. `consulta_resultats.py`: la dependencia externa

Aquest fitxer consulta el servei XML del CEEB i converteix la resposta en estructures Python i pandas. Es especialment rellevant quan s'executa la segona fase.

El que fa es clar i funcional, pero tambe deixa veure diverses debilitats de la V1:

- depen d'un servei remot en temps real
- la identificacio d'equips es fa per nom, no per ID extern robust
- hi ha credencials hardcodejades

### 1.5. `logs.py`: mes que logs

`logs.py` no nomes conté la part de Redis. També conté la definicio dels calendaris de primera i segona fase. Aquest detall es fonamental, perque el comportament del solver depen directament d'aquests calendaris.

## 2. La idea de negoci central: que significa un numero de sorteig

Per entendre la V1, hi ha una pregunta imprescindible: que es, exactament, un numero de sorteig?

El codi respon d'una manera molt precisa:

un numero de sorteig no es nomes una etiqueta entre l'1 i el 8. Es una posicio dins d'un patró de calendari que defineix, jornada a jornada, si l'equip jugaria a casa o a fora.

Aquesta idea canvia del tot la lectura del programa.

No estem davant d'un sistema que primer crea grups i, al final, posa un `1`, un `2` o un `3` per ordenar. El sistema interpreta el numero com un patró competitiu. Per tant:

- demanar `1` es demanar un patró concret
- demanar `6` es demanar un altre patró concret
- demanar `CASA` no es demanar "m'agradaria ser local un dia", sino demanar orientacio cap a una familia de patrons

Aquest es, probablement, el coneixement de domini mes valuos que la V1 ja te capturat.

## 3. Com entra la informacio i com es normalitza

Abans d'assignar res, la V1 ha d'entendre que li han passat.

### 3.1. Columnes minimes

`processar_dades_2()` espera com a minim:

- `Nom`
- `Entitat`
- `Nom Lliga`
- `Núm. sorteig`
- `Nivell`
- `Dia partit`
- `Categoria`

Pot treballar tambe amb:

- `Id`
- `Modalitat`
- `Subcategoria`
- `Pista joc`

Des del punt de vista de negoci, aquestes columnes barregen tres classes d'informacio:

- qui es l'equip
- en quin context competitiu juga
- quines restriccions o preferencies porta a sobre

### 3.2. Generacio d'IDs

Si l'input no porta `Id`, el sistema en genera un de deterministic fent hash de:

- `Nom`
- `Nom Lliga`
- `Categoria`

Aixo te sentit: no depen de l'ordre del fitxer i permet referenciar els equips amb estabilitat dins del proces.

### 3.3. La semantica real de `Núm. sorteig`

La columna `Núm. sorteig` admet, de facto, tres tipus de valor:

- enters `1..8`
- valors textuals `CASA` i `FORA`
- qualsevol altre valor, com ara `Indiferent`, buit o text no numeric

La interpretacio funcional es:

- `1..8`: preferencia explicita per un patró concret
- `CASA/FORA`: preferencia textual que s'ha de resoldre abans
- la resta: sense preferencia efectiva

A la practica, `Indiferent` no te una logica pròpia al solver. Simplement es tracta com una dada que no genera cost.

### 3.4. Validacio de coherencia de `CASA/FORA`

La V1 comprova que un mateix equip no demani `CASA` en una categoria i `FORA` en una altra. Aquesta validacio deixa clara una hipotesi de domini:

la preferencia `CASA/FORA` es una necessitat estructural d'aquell equip, no una preferencia independent i puntual de cada categoria.

## 4. El gran pas global abans del solver: convertir `CASA/FORA` en numeros

Una de les decisions mes interessants de la V1 es que `CASA/FORA` no es resol dins del solver de cada categoria. Es resol abans, a escala global del fitxer.

La idea sembla ser la seguent: si una entitat te diversos equips i necessita coherencia entre categories, no te sentit decidir-ho localment cada vegada. Cal fixar una orientacio comuna i despres projectar-la a totes les categories.

Des del punt de vista de negoci, aquesta idea es bona. Des del punt de vista tecnic, la implementacio actual es una heuristica seqüencial.

### 4.1. El graf d'enllacos entre entitats

El codi construeix `entitats_links`, una estructura que identifica quines entitats es condicionen entre elles. El mecanisme es:

- es detecten entitats amb peticions `CASA/FORA`
- es miren les categories on fan aquestes peticions
- dins d'aquestes categories, es busquen altres equips d'altres entitats que tambe hagin demanat `CASA/FORA`

El resultat es una mena de graf de coexistencia competitiva: qui esta "connectat" amb qui perque comparteixen categories on aquestes peticions importen.

### 4.2. Les 4 duples possibles

La V1 no tria qualsevol combinacio de numeros. Treballa amb quatre duples fixes:

- `(1,5)`
- `(6,2)`
- `(7,3)`
- `(8,4)`

La idea es que cadascuna representa una orientacio coherent `casa/fora` entre patrons complementaris.

### 4.3. Com es decideix la dupla d'una entitat

L'algorisme no es aleatori. Tampoc es una optimitzacio global completa. Es una heuristica amb tres capes:

1. es calcula una preferencia de duples per a cada entitat
2. aquesta preferencia es basa en el que ja s'observa a les categories rellevants
3. les entitats es processen en ordre de criticitat i es mira de minimitzar conflictes amb duples ja assignades a entitats connectades

Si no hi ha prou informacio, es fa un fallback deterministic mitjancant hash del nom de l'entitat. Aixo es important: la V1 no introdueix aleatorietat gratuïta en aquest punt.

### 4.4. Quina clau d'entitat fa servir

Hi ha un matis de domini important: si existeix `Pista joc`, el codi la fa servir en lloc de `Entitat`. Per tant, la coherencia `CASA/FORA` es pot aplicar per pista i no per club.

Aquesta no es una simple decisio d'implementacio. Es una regla funcional que una v2 hauria de fer visible i configurable.

### 4.5. Exemple narratiu

Imaginem un `Club X` amb tres equips:

- equip A demana `CASA`
- equip B demana `CASA`
- equip C demana `FORA`

Suposem que la dupla assignada a l'entitat es `(8,4)`. A partir d'aqui:

- A i B deixen de ser "CASA" en abstracte i passen a ser "prefereixo el patró 8"
- C deixa de ser "FORA" en abstracte i passa a ser "prefereixo el patró 4"

Quan el solver per categoria treballi, ja no veura paraules. Veura patrons concrets.

## 5. Els calendaris de primera i segona fase

Els patrons 1..8 no son inventats dinamicamente. Venen de `logs.py`, on hi ha definides les jornades de primera i segona fase.

### 5.1. Primera fase

La primera fase te 7 jornades. A partir d'aquestes jornades, el programa deriva per a cada numero `1..8` una sequencia `C/F`.

Exemples:

- `1` -> `CFCFCFC`
- `5` -> `FCFCFCF`
- `6` -> `CFFCFCF`
- `2` -> `FCCFCFC`

Ja amb aquests exemples s'entén la idea: alguns numeros formen parelles oposades.

### 5.2. Que vol dir a la practica

Si un equip vol `1`, esta demanant:

- casa a la jornada 1
- fora a la jornada 2
- casa a la jornada 3
- i aixi successivament

Si li toca una altra posicio, el sistema podra mesurar exactament quines jornades no coincideixen amb el patró demanat.

### 5.3. Segona fase

La segona fase amplia la durada a 14 jornades. La V1 construeix els patrons llargs a partir d'aquesta definicio quan cal.

## 6. Com es formen els grups

Quan el programa entra al processament d'una categoria concreta, el primer que fa es decidir quants grups hi haurà.

### 6.1. `crear_grups_equilibrats()`

La funcio calcula el nombre minim de grups necessari per no superar 8 equips per grup i despres reparteix els equips de la manera mes equilibrada possible.

Exemples:

- 14 equips -> `[7, 7]`
- 17 equips -> `[6, 6, 5]`
- 10 equips -> `[5, 5]`
- 4 equips -> `[4]`

### 6.2. El minim de 6 no es realment obligatori

Tot i que existeix `min_grup=6`, el codi no el fa servir com a restriccio dura. Si surten grups de 5, els accepta. Aquest punt es important perque el nom de la funcio podria fer pensar en un repartiment realment limitat entre 6 i 8, i no es aixi.

### 6.3. El model intern sempre es de 8 posicions

Aquest es un dels punts mes estructurals de la V1.

Encara que el grup real tingui 5, 6 o 7 equips, el motor construeix sempre 8 posicions per grup. Es a dir:

- un grup de 5 no te 5 slots
- te 8 slots

Les posicions sobrants les omple amb equips artificials `Descans`.

### 6.4. Exemple clar

Si hi ha 10 equips i es reparteixen en 2 grups de 5:

- slots totals = `2 * 8 = 16`
- equips reals = `10`
- dummies afegits = `6`

Aixo vol dir que la V1 no modela "grups petits". Modela sempre quadres de 8 posicions i converteix les mancances en descansos.

## 7. El problema matematic que resol el solver

Per a cada categoria, la V1 formula un problema d'assignacio.

- files: equips
- columnes: slots `(grup, posicio)`
- cost: que tan dolent es posar aquell equip en aquell slot

Despres aplica `linear_sum_assignment()` de SciPy.

La lectura funcional es important:

el sistema no fa primer els grups i despres reparteix numeros. Fa una sola assignacio equip-slot. La decisio de grup i la decisio de numero neixen al mateix temps.

## 8. La funcio de cost: el cor real del solver

La funcio central es `cost_calc()`. Aqui es on el programa tradueix les preferencies en nombres.

### 8.1. Primer: determinar el numero realment desitjat

El codi fa:

- si el valor era `CASA/FORA`, consulta el mapping global i obté un enter `1..8`
- si el valor ja era numeric, el fa servir
- si no hi ha preferencia valida, retorna cost `0`

Per tant, els equips "indiferents" queden lliures de pressio en aquesta part del model.

### 8.2. Segon: comparar patrons

El sistema construeix la sequencia `C/F` del numero que l'equip desitja i la compara amb la sequencia `C/F` de la posicio del slot.

### 8.3. Tercer: penalitzar les diferencies

La penalitzacio real es exponencial:

- 0 diferencies -> `1`
- 1 diferencia -> `4`
- 2 diferencies -> `16`
- 3 diferencies -> `64`

Si la peticio original era `CASA/FORA`, s'afegeix una bonificacio de `-5`.

La interpretacio es clara: la V1 dona molta prioritat a no deformar el patró de local i visitant.

### 8.4. Un detall molt important

Tot i que la funcio rep `g` i `p`, el cost depen essencialment de `p`, la posicio dins del grup. A la practica:

- posicio 1 del grup A i posicio 1 del grup B costen igual per a un equip concret

Per tant, el cost base optimitza sobretot l'encaix amb el numero de sorteig, no la qualitat de la composicio del grup. La qualitat del grup apareix despres amb reparacions i heuristiques.

### 8.5. Parametres configurables que no ho son del tot

El codi parla de `w_dif_sorteig`, pero la formula real fa servir `4 ** difs` de manera fixa. Això es una inconsistencia important:

- l'API sembla suggerir un pes configurable
- la implementacio real el fixa

Una v2 hauria d'aclarir o corregir aquest punt.

## 9. Fairness entre entitats al llarg de categories

Un dels aspectes mes sofisticats de la V1 es que no tracta cada categoria com un mon tancat. Intenta recordar quines entitats han acumulat més "cost" i compensar-les en categories posteriors.

### 9.1. Com ho fa

Despres de cada categoria, el sistema calcula un cost base per entitat i l'acumula a `entity_costs`.

Quan construeix la matriu de la categoria seguent:

- mira el cost acumulat historíc
- construeix un factor per entitat
- multiplica el cost base dels seus mals encaixos per aquest factor

La idea es que una entitat ja perjudicada no torni a ser igualment fàcil de perjudicar.

### 9.2. Valor i limitacio

La idea funcional es bona. La limitacio és que aquesta fairness es seqüencial i depen de l'ordre en què es processen les categories.

Com que les categories es processen ordenades per `Nom Lliga`:

- l'ordre importa
- les primeres categories no poden beneficiar-se de compensacions futures
- el resultat global pot canviar si canvia l'ordre

Per a una v2, aquest punt mereix decisio explicita.

## 10. La primera solucio: l'algoritme hongares

Amb la matriu de costos construida, el sistema executa l'algoritme hongares. Aquest pas es el nucli mes net des del punt de vista matematic.

Pero convé entendre be que significa "solucio optima" aqui:

vol dir optima respecte a la matriu que el sistema ha definit, no pas respecte a totes les regles de negoci imaginables.

En aquest moment, la solucio encara pot tenir problemes com:

- equips de la mateixa entitat dins del mateix grup
- grups menys equilibrats del desitjable
- concentracio excessiva de `Descans`

Per això la V1 continua treballant després de l'hongares.

## 11. Reparacio de conflictes d'entitat

Despres de la solucio inicial, el sistema reconstrueix els grups i comprova si hi ha entitats repetides dins del mateix grup.

### 11.1. Com funciona la reparacio

`repair_by_hungarian_per_position()` fa una reparacio local:

- detecta els grups conflictius
- identifica quines posicions estan implicades
- mira tots els equips que ocupen aquella mateixa posicio en tots els grups
- construeix un petit problema d'assignacio només per aquesta "columna"
- imposa una penalitzacio enorme (`1e6`) a qualsevol assignacio que repetiria el conflicte

### 11.2. Que vol dir això funcionalment

La V1 no imposa la separacio d'entitats com a restriccio dura en el problema original. La tracta com una propietat que, si es vulnera, s'intenta reparar despres.

La tecnica es raonable i pragmatica, pero no equivalent a resoldre un model amb restriccions fortes des del principi.

## 12. La fase posterior de swaps i homogenietzacio

Quan ja hi ha una solucio "acceptablement bona", el sistema encara no s'atura. Fa una segona fase heuristica per refinar-la.

### 12.1. `homogeneitzar_nivell()`

Primer intenta fer swaps entre grups mantenint la mateixa posicio.

En teoria:

- a primera fase, per reduir dispersio de nivell
- a segona fase, per tenir en compte classificacio prèvia

### 12.2. Que passa realment amb el nivell

La funcio `level_entropy()` penalitza diferencies de nivell de manera molt suau. Amb el mapping A=1, ..., E=5, el cas clarament penalitzat es sobretot la barreja molt extrema, especialment A/E.

Per tant, la V1 si que intenta homogenitzar nivells, pero ho fa d'una manera més feble del que el nom de la funcio podria suggerir.

### 12.3. Que passa realment a segona fase

La branca de segona fase dins de `homogeneitzar_nivell()` es basa en el recompte boolea de `Posició Classificació`. Com que un swap no altera el total agregat d'aquests valors entre dos grups, aquesta part sembla tenir poca capacitat real de millora.

La sensacio que deixa el codi es que la intencio hi es, pero la part forta de l'equilibri per classificacio recau mes avall.

### 12.4. `homogeneitzar_costs()`: la capa forta de refinament

La segona funcio, `homogeneitzar_costs()`, es molt mes rica. Prova swaps i els accepta si milloren una combinacio de:

- cost de sorteig
- equilibri de nivell o de classificacio
- equilibri de `Dia partit`
- distribucio de `Descans`

També:

- evita nous conflictes d'entitat
- protegeix swaps d'equips amb mapping `CASA/FORA`
- recalcula factors de fairness quan toca

Aquest pas ja no es un optimitzador global. Es una recerca local greedy. Pero es, segurament, la capa que dona a la V1 bona part del seu comportament operatiu final.

## 13. Ordenacio final dels grups i construccio del resultat

Un cop la composicio es dona per bona, encara falta la presentacio.

### 13.1. Reordenacio dels grups

Els grups es reordenen segons la suma dels nivells dels seus equips. Despres es renomren com `G1`, `G2`, etc.

Aixo facilita una lectura operativa del resultat, pero introdueix una petita tensio conceptual:

- la segona fase s'ha intentat condicionar per classificacio previa
- pero la presentacio final continua ordenant per nivell

No es un error greu, pero si una barreja de criteris que val la pena explicitar.

### 13.2. `Diferències jornades`

El resultat final no es limita a dir si la peticio s'ha respectat o no. El sistema conserva, per a cada equip, les jornades on el patró assignat no coincideix amb el patró desitjat.

I no ho fa de forma abstracta, sino amb detall de:

- jornada
- costat real (`Casa` o `Fora`)
- rival que tocaria en aquella graella

Aquest detall dona molt valor explicatiu al resultat.

## 14. Quina sortida operativa genera realment el sistema

La sortida principal actual es un Excel `.xlsx`.

### 14.1. Contingut habitual

L'Excel final inclou:

- full `Resum`
- full `Incidències`
- un full per categoria
- a segona fase, fulls addicionals per equips no trobats o no utilitzats

### 14.2. Paper dels CSV de `csv_generats/`

Els CSV presents al repositori semblen rastres d'un flux anterior o d'execucions antigues. El bloc que els genera a `main.py` esta comentat. Per tant, avui el contracte de sortida viu es l'Excel.

### 14.3. Consequencia

La V1 esta molt orientada a revisio humana:

- colors
- filtres
- fulls de resum
- incidencies textuals

Aixo es molt bo per a operacio manual, pero menys adequat si es vol integrar el motor amb altres eines o consumir la sortida com a dades estructurades.

## 15. Exemple narratiu complet d'una categoria

Imaginem una categoria amb 14 equips.

### 15.1. Repartiment

El sistema decideix `[7, 7]`.

### 15.2. Model intern

No crea 14 posicions, sino 16:

- 8 per al primer grup
- 8 per al segon

Per tant afegeix 2 `Descans`.

### 15.3. Preferencies

Suposem que:

- 3 equips demanen nombres explicits
- 4 equips demanen `CASA`
- 1 equip demana `FORA`
- la resta son indiferents

Abans d'entrar al solver:

- els `CASA/FORA` ja han estat convertits a nombres concrets segons l'entitat
- els equips indiferents tenen cost base zero

### 15.4. Solucio inicial

L'hongares reparteix equips en slots intentant respectar sobretot el patró de sorteig i la fairness acumulada.

### 15.5. Sanejament i refinament

Despres:

- es busquen conflictes d'entitat
- es fan reparacions locals
- es proven swaps per millorar nivell, dies, classificacio o repartiment de descansos

### 15.6. Resultat final

La sortida son dos grups de 8 posicions. Algunes d'aquestes posicions poden ser `Descans`. Per a cada equip es pot veure:

- que demanava
- quin numero li ha tocat
- en quines jornades es desvia del patró ideal

Aquest exemple resumeix molt be la naturalesa real del producte: no intenta nomes fer grups, intenta construir una graella de calendari consistent.

## 16. Fortaleses reals de la V1

Abans de parlar de millores, val la pena deixar clar que la V1 te qualitats importants.

### 16.1. Model de domini potent

La idea que el numero de sorteig representa un patró real de calendari es bona i dona sentit funcional al solver.

### 16.2. Determinisme

La major part del comportament es deterministic. Aixo es molt valuos en un context on els resultats s'han de poder justificar.

### 16.3. Memoria entre categories

El fairness acumulat entre entitats es una capacitat madura, encara que la seva implementacio actual sigui heuristica.

### 16.4. Capacitat d'explicar incidencies

El sistema no nomes retorna un resultat. Genera resum, validacions i detall d'incidencies.

### 16.5. Segona fase integrada

La V1 no tracta la segona fase com un simple afegit cosmetic. Intenta fer que les classificacions prèvies influeixin en l'assignacio.

## 17. Limitacions i riscos detectats

També hi ha limitacions estructurals que expliquen per que una v2 tindria molt sentit.

### 17.1. Massa concentracio en pocs punts del codi

`main.py` concentra massa logica i massa responsabilitats.

### 17.2. Restriccions dures i preferencies barrejades

La V1 no separa prou clarament:

- el que no pot passar
- del que seria desitjable que passes

### 17.3. Infactibilitat no formalitzada

Si una entitat te mes equips que grups, el sistema ho detecta, pero no retorna una resposta estructurada d'infactibilitat. Continua.

### 17.4. Heuristiques potents pero opaques

Hi ha decisions que funcionalment poden tenir sentit, pero que no son gaire auditables:

- eleccio de duples `CASA/FORA`
- factors de fairness
- swaps acceptats o rebutjats

### 17.5. Dependencia de l'ordre de categories

La fairness inter-categories introdueix dependència de l'ordre de processament.

### 17.6. Segona fase fràgil

La integracio externa depen de:

- servei remot
- matching per nom
- credencials al codi

### 17.7. Gestio d'errors poc robusta

El motor fa servir `sys.exit()` en punts de logica de negoci. En una v2 seria millor modelar errors de domini o respostes estructurades.

### 17.8. Deute tecnic visible

Hi ha incoherencies menors, com parametres aparentment configurables que no governen realment el calcul, o docstrings que ja no reflecteixen del tot la sortida real.

### 17.9. Absencia visible de proves

No s'han trobat tests al repositori. Per a un motor amb tantes heuristiques, aquest es un risc tecnic gran.

## 18. Que hauria de conservar una v2

Una v2 no hauria d'oblidar el que la V1 ja ha entes del negoci. Hauria de conservar:

- la idea de patró de calendari associat al numero
- la coherencia global de `CASA/FORA`
- la capacitat d'explicar incidencies
- el suport a primera i segona fase
- la idea de fairness entre entitats, si funcionalment es vol mantenir

Aquestes peces son coneixement de domini, no simples detalls accidentals.

## 19. Cap a on hauria d'anar una v2

Si s'ha de fer una v2, la direccio natural sembla aquesta:

### 19.1. Separar capes

Caldria diferenciar:

- models de domini
- ingesta i validacio
- solver
- integracions externes
- reporting

### 19.2. Declarar clarament regles i objectius

La v2 hauria de poder dir explicitament:

- quines restriccions son dures
- quines son preferencies
- quines relaxacions es permeten

### 19.3. Millorar auditabilitat

Per a cada equip seria ideal poder explicar:

- quins slots tenia
- quin cost tenia cada slot
- per que se n'ha triat un i no un altre
- quina part del cost ha pesat mes

### 19.4. Replantejar fairness global

Cal decidir si:

- es manté com a proces seqüencial i ordre-dependent
- o es modela d'una manera mes global

### 19.5. Fer robusta la segona fase

Caldria:

- treure credencials del codi
- introduir cache
- afegir identificadors externs o matching assistit
- permetre corregir equips no trobats abans del solver final

### 19.6. Obrir la sortida a formats estructurats

L'Excel es útil i probablement s'hauria de mantenir, pero una v2 seria molt mes flexible si, a mes, pogués retornar una representacio de dades neta i reutilitzable.

### 19.7. Construir proves de regressio

Si es vol evolucionar el motor sense perdre el coneixement acumulat, caldra una bateria de casos reals anonimitzats per comparar resultats entre V1 i V2.

## Conclusions

La V1 es un sistema mes ric i mes interessant del que pot semblar d'entrada. No es un repartidor aleatori de grups. Es un motor heurístic que intenta conciliar:

- patrons de calendari
- coherencia global de `CASA/FORA`
- fairness entre entitats
- separacio de clubs dins dels grups
- certa homogenietat competitiva
- sortida operativa explicable

El seu principal problema no es conceptual, sino estructural. Hi ha bones idees de domini, pero viuen massa acoblades, massa barrejades i amb poca frontera entre logica, integracio i presentacio.

Per tant, la millor lectura de cara a una v2 es aquesta:

- conservar el coneixement de domini existent
- fer-lo explicit i auditable
- separar-lo de la infraestructura
- gestionar millor la infactibilitat i els errors
- i dotar-lo de proves i de contractes de sortida mes nets

Si es fa aixo, la v2 no nomes sera millor tecnicament. Sera també molt mes facil d'explicar, defensar i mantenir.

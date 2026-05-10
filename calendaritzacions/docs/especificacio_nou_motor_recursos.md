# Especificacio inicial del nou motor de recursos

## 0. Objectiu

Aquest document defineix una primera versio del motor futur de calendaritzacio
basat en recursos fisics. Esta pensat perque subagents o desenvolupadors puguin
implementar-lo per fases sense haver de redissenyar el problema.

El pla executable d'implementacio viu a:

```text
docs/pla_implementacio_nou_motor_recursos.md
```

El canvi conceptual es aquest:

```text
Abans:
  peticio Num. sorteig / CASA / FORA -> numero esperat -> motor intenta encaixar

Nou motor:
  recursos fisics + grups possibles + numeros possibles -> solver decideix
  grup i numero minimitzant incidencia global
```

El motor legacy continua sent la referencia de compatibilitat. Aquest document
descriu una variant nova, no una modificacio directa de la V1.

## 1. Principis de model

### 1.1. La pista real es un recurs de capacitat

La columna `Pista joc` no s'ha d'interpretar com una pista individual exacta,
sino com una seu o instal.lacio.

Una seu pot tenir diverses pistes disponibles en una mateixa franja. Per tant,
el recurs base no es:

```text
equip contra equip
```

sino:

```text
seu + dia + franja horaria + jornada/data
```

Exemple:

```text
Pavello X + Divendres + 18:00 + Jornada 3
```

Aquest recurs te una capacitat:

```text
capacitat = nombre de partits locals que hi caben alhora
```

Si la capacitat es 2, poden coincidir dos equips locals en aquella seu/franja i
jornada sense incidencia.

### 1.2. Els numeros de sorteig son decisions del solver

El nou motor no ha de preassignar duples al principi. El solver ha de decidir
els numeros finals.

La columna `Num. sorteig` no desapareix, pero baixa de categoria:

```text
CASA/FORA -> dada d'entrada auditable, sense cost en l'MVP
1..8      -> dada d'entrada auditable, sense cost en l'MVP
buit      -> llibertat total
```

Per tant, en la primera versio del nou motor, el solver pot escollir el numero
de sorteig al 100% segons recursos, grups, descansos i restriccions esportives.
No s'ha d'afegir cost per acostar-se al `Num. sorteig` demanat.

En una versio futura, la configuracio podria reactivar `Num. sorteig` com a
preferencia o restriccio. Pero l'MVP ha de partir de llibertat total de numeros.

### 1.3. La dupla es una consequencia, no el centre del problema

Les duples contraries continuen sent utils:

```text
1-5
2-6
3-7
4-8
```

Pero nomes son una representacio simple del fet que dos patrons no coincideixen
a casa dins el calendari de fase del run.

La regla general del nou motor ha de ser:

```text
no superar la capacitat del recurs en cada jornada/data
```

En aquest domini, els grups no tenen calendaris propis diferents. La fase es
constant per run (`primera_fase` o `segona_fase`) i tots els grups reutilitzen
el mateix calendari base. Per tant, la comparacio de recursos s'ha de fer per
jornada/data real i numero de sorteig, no per grup.

Exemple:

```text
Equip A a G1 + numero 1 juga a casa a J1
Equip B a G2 + numero 1 juga a casa a J1
```

Si tots dos equips comparteixen `seu + dia + franja`, consumeixen el mateix
recurs a J1 encara que estiguin en grups diferents.

## 2. Normalitzacio previa de recursos

### 2.1. Franges horaries

Les hores s'han de normalitzar per blocs d'una hora.

Exemples:

```text
18:00 -> 18:00
18:15 -> 18:00
18:30 -> 18:00
18:45 -> 18:00
19:00 -> 19:00
19:30 -> 19:00
```

El resultat conceptual es:

```text
resource_slot = seu + dia + franja_hora
```

### 2.2. Pressio previa

Abans de formar grups, ja es pot calcular una radiografia d'entrada:

```text
pressio_base(seu, dia, franja) =
  demanda_equips(seu, dia, franja) / capacitat_estimada(seu, dia, franja)
```

Aquesta pressio no decideix assignacions. Serveix per detectar recursos
critics i donar pesos al solver.

### 2.3. Estimacio inicial de capacitat

Si no hi ha una taula explicita de pistes disponibles, es pot calcular una
capacitat estimada per seu/franja.

La proposta inicial es:

```text
N = max(nombre_equips_per_franja_horaria) / 2 - 1
```

Aquesta formula s'ha de tractar com a heuristica inicial, no com a veritat de
domini. Recomanacions d'implementacio:

```text
N = max(1, floor(N))
N ha de poder ser sobreescrit per configuracio
N ha de quedar auditat en un JSON de recursos
```

Si en el futur hi ha dades reals de pistes per seu, aquestes dades han de tenir
prioritat sobre l'estimacio.

## 3. Categories, grups i calendaris

Per cada modalitat + categoria + subcategoria + nivell/fase, el sistema ha de
calcular els grups possibles.

La fase es una propietat global del run:

```text
run primera fase -> calendari de primera fase per a tots els grups
run segona fase  -> calendari de segona fase per a tots els grups
```

El grup no es un calendari diferent. El grup es el contenidor d'equips i de
posicions `1..8`. Els numeros de sorteig sempre existeixen conceptualment de
`1` a `8` dins de cada grup, pero no tots han d'estar assignats a un equip real.
En grups de 7 equips o menys, les posicions sobrants son numeros buits i actuen
com a descans.

Per tant:

```text
G1 + numero 1 -> mateix patro casa/fora que G2 + numero 1
G1 + numero 6 -> mateix patro casa/fora que G2 + numero 6
```

El grup dona mes opcions al solver per encaixar equips, separar entitats i
respectar mides de grup. El patro casa/fora i el consum de recursos depenen del
numero de sorteig, de la fase i de les dades de pista/dia/franja de l'equip, no
del grup.

Els descansos han d'estar repartits de forma equivalent entre els grups d'una
mateixa categoria. No es acceptable, si hi ha alternativa, que un grup tingui dos
numeros buits i un altre cap. La diferencia de numeros buits entre grups ha de
ser com a maxim 1, excepte si una configuracio explicita de grups ho fixa
d'una altra manera.

## 4. Candidats

Un candidat es una opcio concreta d'assignacio per a un equip.

Si els grups encara no estan decidits, el candidat ha de ser:

```text
candidat = equip + grup_possible + numero_possible
```

Exemple:

```text
Equip A -> G1 + numero 1
Equip A -> G1 + numero 6
Equip A -> G2 + numero 1
Equip A -> G2 + numero 6
```

Cada candidat implica:

```text
1. a quin grup aniria l'equip
2. quin numero de sorteig rebria
3. en quines jornades juga a casa
4. quins recursos consumeix quan juga a casa
```

El camp `grup` continua formant part del candidat perque el solver ha de decidir
la composicio dels grups i garantir numeros unics dins de cada grup. Pero, amb
fase constant per run, dos candidats que nomes difereixen pel grup i tenen el
mateix numero projecten el mateix patro casa/fora.

### 4.1. Generacio de numeros possibles

Regla inicial:

```text
CASA -> 1..8
FORA -> 1..8
1..8 -> 1..8
buit -> 1..8
```

El valor original de `Num. sorteig` s'ha de conservar per auditoria i comparacio
amb el legacy, pero no ha de limitar ni penalitzar les opcions del solver en
l'MVP.

Opcio futura, fora de l'MVP:

```text
mode lliure: sempre 1..8, sense cost de preferencia
mode soft: numero/patro preferit, alternatives permeses amb penalitzacio
mode hard: nomes numeros compatibles amb la peticio
```

## 5. Consum de recursos per candidat

Per cada candidat cal construir una llista de recursos potencials.

Exemple:

```text
Equip A:
  seu = Pavello X
  dia = Divendres
  franja = 18:00

Candidat:
  Grup G1 + numero 1

Patro:
  casa a J1, J3, J5, J7

Consumeix:
  Pavello X + Divendres + 18:00 + J1
  Pavello X + Divendres + 18:00 + J3
  Pavello X + Divendres + 18:00 + J5
  Pavello X + Divendres + 18:00 + J7
```

El mateix equip amb `Grup G2 + numero 1` tindria el mateix patro i consumiria
els mateixos recursos a les mateixes jornades. El grup no canvia la projeccio a
recursos; nomes canvia la composicio esportiva del grup.

Hi ha una excepcio important en grups incomplets. Si en una jornada el numero
assignat a l'equip juga contra un numero que no te cap equip assignat dins del
mateix grup, aquella jornada es descans per a l'equip i no consumeix cap recurs.

Exemple:

```text
Jornada: numero 1 contra numero 2
Grup G1: numero 1 = Equip A, numero 2 = buit

Resultat:
Equip A descansa a aquesta jornada
No es consumeix Pavello X + Divendres + 18:00 + J
```

Per tant, la projeccio final a recursos no pot comptar automaticament totes les
jornades on el numero surt com a local. Ha de comptar nomes els partits reals,
es a dir, jornades on tambe existeix l'oponent dins del grup.

Si el calendari treballa amb dates reals, el recurs ha d'incloure data real en
lloc de jornada abstracta. Aquesta data tambe deriva de la fase comuna del run,
no d'un calendari propi del grup.

## 6. Auditoria local per seu/franja

El model principal no ha de decidir numeros a partir d'un cataleg local. La
decisio ha de ser global dins CP-SAT, amb restriccions directes de capacitat:

```text
locals[recurs, jornada] <= capacitat[recurs]
```

Les combinacions locals per `seu + dia + franja` poden existir, pero nomes com a
auditoria opcional o explicabilitat, especialment en blocs petits, saturats o
amb incidencia final.

Exemple:

```text
Pavello X + Divendres + 18:00
Equips: A, B, C
Capacitat: 2
```

Combinacio local plausible:

```text
A -> numero 1
B -> numero 6
C -> numero 5
```

Mesures de la combinacio:

```text
per cada jornada:
  locals = equips de la combinacio que juguen a casa
  exces = max(0, locals - capacitat)
```

Metricas locals recomanades:

```text
max_locals_per_jornada
jornades_amb_exces
exces_total
cost_exces
descansos
partits_reals
```

### 6.1. Quan enumerar combinacions locals

Enumerar combinacions locals es util nomes per auditoria si el bloc es petit:

```text
3 equips amb 4 opcions = 64 combinacions
5 equips amb 4 opcions = 1024 combinacions
```

No s'ha d'enumerar si el bloc es gran. En blocs grans, la capacitat ja queda
coberta per les restriccions globals del CP-SAT.

Llindar inicial recomanat:

```text
si producte(opcions_per_equip) <= 50_000 i el bloc es critic:
  es pot enumerar cataleg local per auditoria
si no:
  no enumerar
```

### 6.2. El cataleg local no decideix

El cataleg local no ha de fixar numeros abans del solver ni afegir una
restriccio extra si ja s'han modelat les capacitats directament.

Ha de servir per:

```text
1. explicar per que un bloc era critic abans del solver
2. contrastar la solucio del solver amb combinacions locals plausibles
3. mostrar incidencies per jornada i capacitat
4. calcular alternatives properes en blocs petits
```

La decisio final continua sent global i ve del CP-SAT.

### 6.3. Capes d'auditoria local

Auditoria recomanada:

```text
1. Pressio d'entrada:
   equips candidats, capacitat, pressio del recurs.

2. Solucio del solver:
   locals per jornada, capacitat, exces, equips locals, descansos.

3. Alternatives locals properes:
   canvis petits de numero/grup que reduirien una incidencia,
   indicant per que no son aplicables o quin cost/restriccio trencarien.
```

No cal comparar contra totes les combinacions possibles. Les alternatives locals
son una eina d'explicacio, no una demostracio d'optimalitat. La prova
d'optimalitat, si s'assoleix, correspon al CP-SAT.

## 7. Model de solver CP-SAT / ILP

El motor es pot implementar amb CP-SAT d'OR-Tools o amb ILP/MILP. La primera
opcio recomanada es CP-SAT.

### 7.1. Variables principals

Variable binaria:

```text
x[equip, grup, numero] = 1
```

Significat:

```text
l'equip queda assignat a aquest grup amb aquest numero
```

### 7.2. Restriccio: un candidat per equip

Cada equip ha de tenir exactament una assignacio:

```text
sum(x[equip, grup, numero] per tots els seus candidats) = 1
```

### 7.3. Restriccio: numeros unics dins un grup

Dins un grup no es pot repetir numero:

```text
sum(x[equip, grup, numero] per tots els equips candidats) <= 1
```

per cada `grup, numero`.

El fet que un numero no tingui equip assignat es valid en grups incomplets. En
aquest cas el numero queda buit i genera descansos per als rivals que s'hi
haurien d'enfrontar segons el calendari de fase.

### 7.4. Restriccio: mida del grup

Cada grup ha de tenir la mida esperada o quedar dins un rang valid:

```text
min_size[grup] <= sum(x[equip, grup, numero]) <= max_size[grup]
```

Si el repartiment de grups ja esta decidit, aquesta restriccio pot ser exacta.

### 7.4.1. Restriccio: repartiment equivalent de descansos

Els grups d'una mateixa categoria han de tenir un nombre de numeros buits tan
equilibrat com sigui possible.

Si `buits[grup] = 8 - equips_assignats[grup]`, llavors:

```text
max(buits[grup]) - min(buits[grup]) <= 1
```

per als grups comparables de la mateixa categoria.

Aixo evita resultats com:

```text
G1 -> 6 equips, 2 numeros buits
G2 -> 8 equips, 0 numeros buits
```

quan el mateix total d'equips permetria:

```text
G1 -> 7 equips, 1 numero buit
G2 -> 7 equips, 1 numero buit
```

### 7.5. Restriccio: mateixa entitat separada

Equips de la mateixa entitat no poden anar al mateix grup. Aquesta restriccio ha
de ser dura sempre que sigui factible:

```text
sum(x[equip, grup, numero] per equips de la mateixa entitat) <= 1
```

per cada `entitat, grup`.

L'unica excepcio es el cas infactible: si una entitat te mes equips dins la
categoria que grups disponibles, no es possible separar-los tots. En aquest cas
el solver ha d'acceptar la incidencia, pero minimitzant-la al maxim.

Model recomanat per al cas general:

```text
exces_entitat[entitat, grup] >=
  sum(x[equip, grup, numero] per equips de la mateixa entitat) - 1
exces_entitat[entitat, grup] >= 0
```

Si `num_equips_entitat <= num_grups`, l'exces ha d'estar forcat a 0 o tenir una
penalitzacio prou alta per actuar com a restriccio dura. Si
`num_equips_entitat > num_grups`, l'exces inevitable entra a l'objectiu amb
penalitzacio alta i el solver reparteix el conflicte de la manera menys dolenta
possible.

### 7.6. Restriccio: capacitat de recursos

Per cada recurs amb jornada/data:

```text
locals[recurs] =
  sum(partits reals on un equip fa de local i consumeix aquest recurs)
```

Un partit nomes es real si els dos numeros del calendari de fase estan ocupats
per equips del mateix grup. Si el numero rival esta buit, aquella jornada es
descans i no suma a `locals[recurs]`.

Si la capacitat es dura:

```text
locals[recurs] <= capacitat[recurs]
```

Si es vol permetre incidencia:

```text
exces[recurs] >= locals[recurs] - capacitat[recurs]
exces[recurs] >= 0
```

I l'exces entra a l'objectiu amb penalitzacio alta.

### 7.7. Restriccions de nivell i esportives

El motor ha de poder afegir restriccions o costos per:

```text
nivell
modalitat
categoria
subcategoria
dia de joc
equilibri entre grups
classificacio en segona fase
```

No totes han de ser dures. La configuracio ha de marcar quines son obligatories
i quines son preferencies.

## 8. Objectiu global

El solver ha de minimitzar:

```text
cost_total =
cost_exces_recursos
+ cost_exces_entitat
+ cost_grups
+ cost_descansos
+ cost_nivells
+ cost_fairness
```

### 8.1. Cost d'exces de recursos

Ha de ser el cost dominant si no es permet saturar seus/franges:

```text
cost_exces_recursos =
  sum(exces[recurs] * pes_exces_recurs)
```

Pes inicial recomanat:

```text
pes_exces_recurs molt superior als altres pesos
```

### 8.1.1. Cost d'exces d'entitat

La separacio d'equips de la mateixa entitat per grup es dura quan es pot
complir. Quan no es pot complir perque una entitat te mes equips que grups, la
incidencia es inevitable i s'ha de penalitzar fort.

```text
cost_exces_entitat =
  sum(exces_entitat[entitat, grup] * pes_exces_entitat)
```

Aquest pes ha de ser alt, pero ha de permetre solucio en casos inevitables.

### 8.1.2. Cost de descansos desequilibrats

El repartiment de numeros buits entre grups ha de ser equivalent. Si es modela
com a restriccio dura, cal imposar directament:

```text
max(buits[grup]) - min(buits[grup]) <= 1
```

Si es modela com a preferencia forta, el desequilibri entra a l'objectiu:

```text
cost_descansos =
  desequilibri_buits * pes_descansos
```

La primera versio recomanada es tractar aquest repartiment com a restriccio dura
sempre que el nombre total d'equips i grups ho permeti.

### 8.2. Peticions `Num. sorteig` en l'MVP

En l'MVP no hi ha `cost_desviacio_num_sorteig` ni `cost_casa_fora`.

El solver ha de poder escollir qualsevol numero `1..8` per a qualsevol equip,
respectant unicitat de numeros dins del grup i la resta de restriccions. La
columna `Num. sorteig` s'ha de conservar al resultat i als JSONs per:

```text
auditar que havia demanat l'equip
comparar contra el legacy
calcular indicadors informatius sense afectar la solucio
```

Si mes endavant es vol recuperar aquesta semantica, s'ha d'afegir com a mode
configurable i no com a comportament per defecte.

### 8.3. Pressio previa

En l'MVP, la pressio previa no ha d'entrar com a cost de l'objectiu. La
capacitat ja queda governada per restriccions directes:

```text
locals[recurs, jornada] <= capacitat[recurs]
```

La pressio previa serveix per:

```text
detectar recursos critics abans del solver
prioritzar quins blocs auditar amb mes detall
explicar per que una franja era dificil
decidir si val la pena enumerar alternatives locals post-solver
```

Si en una versio futura es vol usar com a cost, ha de ser configurable i s'ha de
vigilar que no dupliqui ni distorsioni la restriccio real de capacitat.

### 8.4. Combinacions locals

Les combinacions locals no han d'afegir cost a l'objectiu en l'MVP. Si es
generen, han de servir per auditoria i explicacio post-solver.

La capacitat real ja queda representada per les restriccions directes del model:

```text
locals[recurs, jornada] <= capacitat[recurs]
```

## 9. Com s'arriba a la resolucio

El flux complet del motor ha de ser:

```text
1. Llegir input normalitzat.
2. Construir recursos base: seu + dia + franja.
3. Estimar o carregar capacitats.
4. Calcular pressio previa.
5. Identificar modalitats/categories i nombre de grups.
6. Generar candidats equip + grup + numero.
7. Projectar cada candidat a recursos potencials i rival per jornada.
8. Construir model CP-SAT/ILP amb restriccions directes.
9. Afegir restriccions dures.
10. Afegir variables d'incidencia per restriccions soft locals inevitables.
11. Definir objectiu global ponderat.
12. Executar solver amb limit de temps.
13. Llegir la solucio: grup i numero final per equip.
14. Construir calendari final i indicadors.
15. Generar auditoria explicable.
16. Opcionalment enumerar alternatives locals per blocs petits o amb incidencia.
```

La part important es que el solver no rep "aquest equip ha de ser numero 6".
Rep:

```text
aquest equip pot anar a aquests grups i numeros,
cada opcio pot consumir aquests recursos si el partit es real,
cada opcio te aquests costos,
tria una opcio per equip sense saturar recursos.
```

## 10. Artefactes d'auditoria recomanats

El nou motor ha de produir JSONs especifics, a mes dels KPIs generals.

### 10.1. `resource_pressure.json`

Contingut:

```text
seu
dia
franja
demanda_equips
capacitat_estimada
pressio
metode_capacitat
equips_afectats
```

### 10.2. `candidate_catalog.json`

Contingut:

```text
equip
grups_possibles
numeros_possibles
peticio_original
recursos_potencials
numero_rival_per_jornada
```

### 10.3. `local_combinations.json`

Contingut:

```text
seu
dia
franja
equips
capacitat
combinacions_avaluades
solucio_solver_local
combinacions_plausibles
alternatives_properes
restriccions_que_impedeixen_alternatives
```

Aquest artefacte es opcional i pot ser parcial si el bloc era massa gran per
enumerar. No es una entrada obligatoria del solver.

### 10.4. `solver_model_summary.json`

Contingut:

```text
num_variables
num_restriccions
num_equips
num_candidats
num_recursos
num_restriccions_capacitat
pesos_objectiu
time_limit
```

### 10.5. `resource_solution.json`

Contingut:

```text
per equip:
  grup_assignat
  numero_assignat
  peticio_original
  recursos_on_juga_a_casa
  jornades_descans

per recurs:
  locals_assignats
  capacitat
  exces
  equips_locals

per grup:
  numeros_assignats
  numeros_buits
  descansos_generats
  exces_entitat
```

### 10.6. `solver_explanations.json`

Contingut:

```text
incidencies inevitables
recursos saturats
equips on el numero final difereix del `Num. sorteig` original, nomes informatiu
motiu principal de la decisio si es pot inferir
alternatives properes si es poden calcular
```

## 11. Moduls proposats

Estructura inicial:

```text
calendaritzacions/
  engine/
    variants/
      resource_solver/
        __init__.py
        service.py
        config.py
        resources.py
        capacities.py
        groups.py
        candidates.py
        local_combinations.py
        model.py
        objective.py
        solution.py
        audit.py
```

### 11.1. `config.py`

Responsabilitats:

```text
pesos de l'objectiu
limit de temps
mode peticions numeriques: lliure en l'MVP
mode CASA/FORA: lliure en l'MVP
llindar d'enumeracio local
metode d'estimacio de capacitat
pes exces entitat inevitable
mode repartiment descansos: hard/soft
```

### 11.2. `resources.py`

Responsabilitats:

```text
normalitzar seu
normalitzar dia
normalitzar hora a franja
crear recursos base
crear recursos amb jornada/data
```

### 11.3. `capacities.py`

Responsabilitats:

```text
carregar capacitats si existeixen
estimar capacitats si no existeixen
calcular pressio previa
marcar recursos critics
```

### 11.4. `groups.py`

Responsabilitats:

```text
calcular grups possibles per modalitat/categoria/nivell
calcular mida minima/maxima per grup
validar que tots els grups usen la fase comuna del run
calcular repartiment equilibrat de numeros buits
```

### 11.5. `candidates.py`

Responsabilitats:

```text
generar equip + grup + numero
conservar peticio original per auditoria
projectar recursos potencials per numero i jornada
identificar numero rival per jornada
```

### 11.6. `local_combinations.py`

Responsabilitats:

```text
agrupar solucio i candidats per seu/dia/franja
enumerar combinacions locals si el bloc es petit o critic
calcular saturacio local de la solucio del solver
tenir en compte descansos per numeros rivals buits
retornar alternatives locals auditables
```

### 11.7. `model.py`

Responsabilitats:

```text
crear variables x[equip, grup, numero]
crear variables d'exces
afegir restriccions dures
afegir restriccions de numeros buits equilibrats
afegir exces d'entitat nomes quan sigui inevitable
connectar candidats amb partits reals i consum de recursos
executar CP-SAT/ILP
```

### 11.8. `objective.py`

Responsabilitats:

```text
construir cost total ponderat
separar costos per familia
facilitar explicacions posteriors
```

### 11.9. `solution.py`

Responsabilitats:

```text
convertir variables actives en assignacions finals
crear DataFrame equivalent al legacy
calcular incidencies finals
calcular descansos per equip i numeros buits per grup
```

### 11.10. `audit.py`

Responsabilitats:

```text
generar JSONs del nou motor
explicar pressio, candidats, solucio i incidencies
explicar conflictes inevitables d'entitat i descansos
```

## 12. Pla d'implementacio per subagents

### AGENT-RS-01 resources-and-pressure

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/resources.py
calendaritzacions/engine/variants/resource_solver/capacities.py
tests/test_resource_solver_resources.py
```

Objectiu:

```text
normalitzar franges per hora
estimar capacitats
calcular pressio per seu/dia/franja
```

### AGENT-RS-02 groups-and-candidates

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/groups.py
calendaritzacions/engine/variants/resource_solver/candidates.py
tests/test_resource_solver_candidates.py
```

Objectiu:

```text
generar candidats equip + grup + numero
projectar candidats a jornades locals
conservar peticions originals per auditoria, sense cost en l'MVP
```

### AGENT-RS-03 local-combinations

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/local_combinations.py
tests/test_resource_solver_local_combinations.py
```

Objectiu:

```text
enumerar combinacions petites per seu/dia/franja
calcular exces per jornada
produir cataleg auditable
```

### AGENT-RS-04 cp-sat-model

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/model.py
calendaritzacions/engine/variants/resource_solver/objective.py
tests/test_resource_solver_model.py
```

Objectiu:

```text
crear model CP-SAT
afegir restriccions d'un candidat per equip
afegir numeros unics per grup
afegir repartiment equilibrat de numeros buits
afegir separacio d'entitats dura excepte infactibilitat
afegir capacitat de recursos
minimitzar objectiu ponderat
```

### AGENT-RS-05 service-and-audit

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/engine/variants/resource_solver/solution.py
calendaritzacions/engine/variants/resource_solver/audit.py
tests/test_resource_solver_service.py
```

Objectiu:

```text
connectar el motor al registre de motors
retornar resultat compatible
generar artefactes d'auditoria
```

## 13. Decisions pendents

Abans d'implementar el solver complet cal tancar aquestes decisions:

```text
1. La capacitat estimada N es suficient o cal una taula editable de seus?
2. En una versio futura, cal reactivar `Num. sorteig` com a cost o restriccio?
3. En una versio futura, CASA/FORA ha de tenir semantica propia o seguir lliure?
4. La capacitat de recursos es sempre dura o pot generar incidencia amb cost?
5. Els grups es decideixen dins el nou solver o venen preformats per una fase previa?
6. Hi ha dates reals per jornada o nomes jornada abstracta?
7. Quin limit de temps es acceptable per categoria/modalitat/run complet?
```

## 14. Primera versio minima viable

La primera versio implementable no ha d'intentar resoldre tot el producte.

MVP recomanat:

```text
1. Treballar amb una sola modalitat/categoria.
2. Usar grups possibles calculats pel repartiment actual.
3. Generar candidats equip + grup + numero.
4. Fer `Num. sorteig` completament lliure, sense cost de preferencia.
5. Fer capacitat de recursos soft amb penalitzacio molt alta.
6. No enumerar combinacions locals grans.
7. Produir auditoria completa encara que el resultat no substitueixi legacy.
```

Objectiu de l'MVP:

```text
comparar el cost de recursos del motor nou contra el legacy en fixtures petites
```

No ha de substituir la V1 fins que hi hagi comparatives i golden runs.

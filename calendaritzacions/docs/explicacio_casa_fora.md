# Explicacio de la resolucio CASA/FORA

## Resum curt

Les peticions textuals `CASA` i `FORA` no entren directament al solver com a
text. Primer es resolen globalment a numeros de sorteig concrets.

El sistema assigna a cada clau de pista/entitat una de quatre duples fixes:

- `(1, 5)`
- `(6, 2)`
- `(7, 3)`
- `(8, 4)`

El primer numero de cada dupla es el numero que es dona als equips amb peticio
`CASA`. El segon numero es el numero que es dona als equips amb peticio `FORA`.

Exemple: si una clau rep la dupla `(6, 2)`, els equips d'aquella clau que han
demanat `CASA` passen a tenir expectativa `6`, i els que han demanat `FORA`
passen a tenir expectativa `2`.

## On viu el codi

La resolucio principal viu a:

- `calendaritzacions/engine/legacy/home_away.py`

El pipeline la crida des de:

- `calendaritzacions/application/legacy_pipeline.py`

El motor consumeix el resultat des de:

- `calendaritzacions/application/category_runner.py`
- `calendaritzacions/engine/legacy/service.py`
- `calendaritzacions/engine/legacy/matrix.py`
- `calendaritzacions/engine/legacy/costs.py`

## Quan es resol

L'ordre actual es:

1. Es llegeix l'Excel.
2. Es prepara l'input legacy:
   - validacio de columnes;
   - regeneracio d'`Id`;
   - lectura de `map_modalitat_nom.csv`.
3. Es resolen globalment les peticions `CASA/FORA`.
4. Si es segona fase, es consulten classificacions CEEB.
5. Es processen les categories una a una amb el motor legacy.

Per tant, `CASA/FORA` es resol abans de la segona fase i abans del bucle per
categories. La decisio es global per tot l'input del run, no independent per
cada categoria.

## Quina clau s'utilitza

El codi no usa sempre `Entitat`.

La regla es:

- si existeix la columna `Pista joc`, la clau de resolucio es `Pista joc`;
- si no existeix `Pista joc`, la clau de resolucio es `Entitat`.

Aixo vol dir que, si el fitxer te columna `Pista joc`, una mateixa entitat pot
tenir duples diferents per pistes diferents.

No es fa servir una clau combinada `Entitat + Pista joc`. Es una opcio o
l'altra, amb prioritat per `Pista joc`.

## Condicions d'entrada

Per poder resoldre `CASA/FORA`, el DataFrame ha de tenir:

- `Id`;
- `Nom Lliga`;
- `Num. sorteig` / `Núm. sorteig` segons el nom real de columna del fitxer;
- `Pista joc` si aquesta columna existeix i s'usa com a clau;
- si no hi ha `Pista joc`, `Entitat`.

Nomes es consideren peticions textuals exactes, normalitzades amb strip i
lowercase:

- `casa`;
- `fora`.

Els numeros de sorteig numerics no es resolen en aquest pas; ja son peticions
concretes.

## Validacio principal

Abans d'assignar duples, el sistema comprova que un mateix `Id` no tingui alhora
peticions textuals `CASA` i `FORA` en files diferents.

Aixo es considera incoherent:

- mateix equip amb `Id = X`;
- en una categoria demana `CASA`;
- en una altra categoria demana `FORA`.

Aquest cas falla abans d'entrar al motor.

En canvi, una mateixa entitat o pista pot tenir equips diferents amb `CASA` i
equips diferents amb `FORA`. En aquest cas tots comparteixen la mateixa dupla:
els `CASA` agafen el numero casa de la dupla i els `FORA` agafen el numero fora.

## Com es creen els vincles entre entitats o pistes

Per cada clau amb peticions textuals, el codi mira en quines categories apareix
aquesta clau amb `CASA/FORA`.

Despres, dins aquestes mateixes categories, busca altres claus que tambe tinguin
peticions textuals. Els equips textuals d'aquestes altres claus es guarden com a
vincles.

La idea practica es:

- si dues entitats/pistes tenen peticions `CASA/FORA` dins una mateixa lliga,
  interessa que no acabin totes amb la mateixa dupla;
- per aixo es calcula una mena de xarxa local de conflictes potencials.

Les claus es processen ordenades per criticitat:

1. primer les que tenen mes vincles;
2. en empat, ordre alfabetica/casefold de la clau.

## Com es decideix la dupla preferida

Per cada clau, el sistema calcula preferencies de dupla.

Per fer-ho, mira les categories on aquella clau te peticions textuals. Dins
d'aquestes categories, revisa els numeros de sorteig ja existents i compta en
quina dupla cau cada numero:

- `1` o `5` compten per la dupla `(1, 5)`;
- `6` o `2` compten per la dupla `(6, 2)`;
- `7` o `3` compten per la dupla `(7, 3)`;
- `8` o `4` compten per la dupla `(8, 4)`.

Les duples amb menys presencia numerica en aquelles categories queden abans en
la llista de preferencia.

Si no hi ha cap numero numeric que serveixi de referencia, es fa un fallback
determinista:

- hash estable del nom de la clau;
- modul 4;
- resultat: una de les quatre duples.

Aixo evita aleatorietat entre execucions.

## Com evita xocs amb altres claus

Quan toca assignar una clau, el sistema mira quins equips vinculats ja han estat
assignats abans a cada dupla.

Llavors escull, entre les duples preferides, la que genera menys conflictes amb
assignacions ja fetes.

Important: aixo es greedy, no una optimitzacio global. Les decisions anteriors
ja queden fixades.

## Que retorna la resolucio

La resolucio retorna tres peces principals:

- `equip_to_num_sorteig`: mapping `Id equip -> numero esperat`;
- `entitats_assigned`: mapping `clau pista/entitat -> index de dupla`;
- `duples_casa_fora`: la llista fixa de duples.

Exemple conceptual:

```python
equip_to_num_sorteig = {
    "EQ123": 6,
    "EQ456": 2,
}

entitats_assigned = {
    "Pista A": 1,  # index de (6, 2)
}
```

Aquest mapping nomes existeix per equips amb peticions textuals `CASA/FORA`.
Els equips amb numero numeric no apareixen necessàriament en aquest mapping.

## Com entra al motor

El mapping `equip_to_num_sorteig` es passa a cada categoria quan es crida el
motor legacy.

Dins el motor, quan es construeix la matriu de costos:

1. si l'equip tenia `CASA` o `FORA`, es busca el seu `Id` dins
   `equip_to_num_sorteig`;
2. aquest numero passa a ser el numero esperat de l'equip;
3. per cada slot possible del grup, es compara el patro casa/fora del numero
   esperat amb el patro casa/fora del slot candidat;
4. com mes diferencies de jornades hi ha, mes cost rep aquell slot.

El cost actual aplica:

- una bonificacio de `-5.0` per haver resolt una peticio textual;
- una penalitzacio `4 ** diferencies`, on `diferencies` es el nombre de jornades
  on el patro casa/fora no coincideix.

Per tant:

- encaix perfecte: cost baix, fins i tot negatiu;
- poques diferencies: cost moderat;
- moltes diferencies: cost molt alt.

El solver hongares minimitza aquesta matriu de costos.

## Es una restriccio dura?

No completament.

La peticio `CASA/FORA` entra com una preferencia forta dins el cost, no com una
restriccio matematicament impossible de violar.

En la practica, el solver intenta respectar-la molt perque les penalitzacions
creixen rapidament. Pero pot acabar assignant un numero diferent si el conjunt
de costos i restriccions del problema ho porta cap aqui.

Despres, els indicadors comparen:

- numero esperat;
- numero assignat;
- si hi ha mismatch;
- quines jornades queden diferents.

## Que passa despres de l'assignacio inicial

Despres de l'hongares, el motor fa reparacions i cerca local.

Hi ha un detall important:

- els swaps intra-grup ignoren equips d'entitats amb peticions `CASA/FORA`;
- els swaps inter-grup no estan bloquejats igual de fort; es recalcula el cost i
  el swap nomes s'accepta si millora el cost total i no genera conflictes
  d'entitat.

Aixo vol dir que el sistema protegeix parcialment les peticions textuals durant
la millora local, pero la proteccio principal continua sent el cost.

## Com s'audita

Actualment el pipeline genera artefactes i indicadors que permeten revisar el
resultat:

- `home_away_resolution_<fitxer>.json`;
- `solver_trace_<fitxer>.json`;
- `constraints_report_<fitxer>.json`;
- seccions de KPIs amb compliment `CASA/FORA`;
- incidencies quan el numero esperat no coincideix amb l'assignat.

Els indicadors calculen:

- `expected_seed`;
- `assigned_seed`;
- `is_mismatch`;
- `casa_fora_respected`;
- dupla assignada;
- numero casa i numero fora de la dupla.

## Punts forts

- Es global per tot el run, no local a una sola categoria.
- Es determinista: mateix input, mateixa resolucio.
- Permet que una entitat o pista tingui alhora equips `CASA` i equips `FORA`
  de forma coherent amb una mateixa dupla.
- Si existeix `Pista joc`, pot diferenciar pistes dins una mateixa entitat.
- Evita incoherencies fortes, com un mateix equip demanant `CASA` i `FORA`.
- Intenta repartir duples entre claus relacionades dins les mateixes categories.
- No bloqueja el solver: si hi ha una situacio complicada, el motor encara pot
  trobar una assignacio i despres auditar les desviacions.
- Els resultats queden explicables amb mapping, traces i KPIs.

## Punts febles

- No es una optimitzacio global exacta; es una heuristica greedy.
- L'ordre de processament importa: les claus mes critiques decideixen abans i
  les altres s'adapten.
- Si existeix `Pista joc`, s'ignora `Entitat` com a clau de resolucio. Aixo pot
  fragmentar una mateixa entitat en diverses duples.
- No usa una clau combinada `Entitat + Pista joc`.
- Si `Pista joc` existeix pero esta buida, mal normalitzada o inconsistent, pot
  generar decisions estranyes.
- Les preferencies de dupla es basen en numeros ja presents a les categories,
  no en una comprovacio completa de disponibilitat real de calendari.
- Les peticions entren com a costos, no com a restriccions dures. Per tant,
  poden no complir-se al 100%.
- La proteccio durant swaps locals no es simetrica: intra-grup esta mes
  protegit que inter-grup.
- No busca un rival concret ni una parella concreta d'equips. Nomes busca
  patrons casa/fora equivalents.
- El fallback per hash es estable, pero no sap res del context esportiu.

## Interpretacio correcta

La pregunta clau es si el sistema busca un equip contrari per assignar-li el
numero oposat.

La resposta es: no exactament.

El sistema no diu "aquest equip jugarà contra aquest altre i per tant li poso el
numero contrari". El que fa es:

1. convertir cada peticio textual en un numero esperat;
2. fer que `CASA` i `FORA` d'una mateixa clau comparteixin una dupla coherent;
3. penalitzar slots que no respecten el patro casa/fora d'aquell numero esperat.

El contrari es una propietat del numero dins el calendari, no una seleccio
directa d'un rival concret.

## Recomanacions si es vol millorar

Si en el futur es vol fer un motor nou, aquesta part seria candidata a millora:

- modelar `CASA/FORA` com a restriccio dura configurable;
- usar una clau explicita `Entitat + Pista joc` quan calgui;
- normalitzar i validar millor `Pista joc`;
- fer una optimitzacio global de duples en comptes d'una assignacio greedy;
- separar clarament peticions per disponibilitat de pista i peticions per
  preferencia esportiva;
- afegir un mode explicable que mostri per cada clau per que ha rebut una dupla
  concreta.

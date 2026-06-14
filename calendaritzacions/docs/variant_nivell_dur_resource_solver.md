# Variant de nivell dur estructural

El `resource_solver` pot executar-se amb `resource_solver_level_constraint_mode="hard"` des del selector de restriccio de nivell. Aquesta variant converteix el nivell en una restriccio estructural abans d'entrar al solver.

## Normalitzacio de nivells

Els nivells d'entrada es redueixen a tres families competitives:

- `A` -> familia `A`
- `B` -> familia `B`
- `C` i `D` -> familia flexible `B/C`
- `E` -> familia `C`
- nivell buit o no reconegut -> familia flexible `B/C`

Les compatibilitats dures son:

- equips `A` nomes poden competir en grups `A`
- equips `B` nomes poden competir en grups `B`
- equips `C` nomes poden competir en grups `C`
- equips `B/C` poden omplir grups `B` o `C`, pero el solver els assigna una sola vegada

## Planificacio de grups

La planificacio es fa per cada competicio real. El run permet triar el criteri d'agrupacio:

- `Auto`: comportament historic; usa `Modalitat`, `Categoria`, `Subcategoria` quan els tres camps hi son, i si no `Nom Lliga`
- `Nom Lliga`: força que la competicio sigui el valor de `Nom Lliga`
- `Modalitat / categoria / subcategoria`: força que la competicio siguin aquests tres camps

En mode dur es creen grups separats per familia de nivell dins de cada competicio resultant abans de generar candidats.

Les mides es valoren en dues passes:

1. Primer es busquen particions nomes amb grups de 6-8 equips. Si existeixen, no es crea cap grup excepcional.
2. Si no existeix cap particio 6-8, es permeten grups de 9-10 o grups petits inevitables.

Les categories de mida son:

- mida ideal: 6-8 equips
- mida excepcional: 9-10 equips, nomes quan no hi ha particio 6-8 acceptable
- mida baixa: 1-5 equips, permesa amb avis
- mida no suportada: mes de 10 equips en un mateix grup

Exemples:

- 10 equips d'una familia -> grup de 10
- 11 equips -> grups de 6 i 5, amb avis pel grup de 5
- 17 equips -> grups de 9 i 8
- 18 equips -> grups de 6, 6 i 6
- 20 equips -> grups de 7, 7 i 6

Un grup de 9 o 10 utilitza números de sorteig `1..10`. Un grup de 9 deixa un numero buit, que funciona com a descans.

## Calendaris de 8 i 10 slots

El calendari ja no es pot considerar global per tot el run. Els grups de 8 usen `PRIMERA_FASE` o `SEGONA_FASE`; els grups de 9/10 usen `PRIMERA_FASE_10` o `SEGONA_FASE_10` segons la fase del run.

Per tant, la generacio de candidats i la reconstruccio de partits resolen el calendari amb:

- fase del grup (`primera_fase` o `segona_fase`)
- nombre de slots del grup (`8` o `10`)

## Auditories

El run genera l'artefacte `level_group_planning`, amb:

- grups creats, mida objectiu i numeros disponibles
- avisos de grups petits inevitables
- grups excepcionals de 9/10
- repartiment de capacitat flexible `B/C` cap a families `B` i `C`

El solver no afegeix costos de nivell en mode `hard`; les incompatibilitats queden eliminades en la construccio de grups i candidats.

## Interaccio amb conflictes d'entitat

La restriccio de nivell dur te prioritat estructural sobre la separacio d'entitat.

La separacio d'entitat es mante dura nomes quan els equips d'una mateixa entitat es poden assignar a grups diferents segons els grups realment accessibles per cada equip. Si el filtratge de nivell deixa dos o mes equips de la mateixa entitat amb un unic grup compatible, la separacio passa a soft per aquell cas.

La penalitzacio es proporcional a la coincidencia dins del grup: `count - 1` per cada parella entitat/grup amb mes d'un equip assignat.

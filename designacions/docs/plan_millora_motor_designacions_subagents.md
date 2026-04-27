# Pla De Millora Del Motor De Designacions Per Casos Amb Seus Disperses I Pocs Tutors

## Objectiu

Aquest document descriu la problematica detectada en el motor de designacions quan hi ha moltes seus disperses, pocs tutors disponibles, pocs tutors amb vehicle o modalitats amb baixa densitat de partits. L'objectiu es donar context suficient a un subagent extern per estudiar i implementar millores sense necessitar context previ de la conversa.

No es proposa tocar la clusteritzacio com a unic mecanisme de millora. La clusteritzacio ajuda a validar mobilitat, pero el run 96 mostra que la incidencia alta tambe ve de com s'usen els tutors disponibles i de com s'optimitza la cobertura global.

## Context Funcional

El modul `designacions` assigna tutors de joc a partits. El motor principal esta a:

- `designacions/main_fixed.py`
- Entrada principal: `main(...)`
- Persistencia a BD: `persist_assignacions_to_db(...)`
- Diagnosi de viabilitat/mobilitat: `designacions/services/assignment_feasibility.py`
- Diagnosi manual i avisos: `designacions/services/manual_assignment.py`
- Models principals: `DesignationRun`, `Match`, `Availability`, `Assignment`, `AddressCluster` a `designacions/models.py`

El flux actual, simplificat, es:

1. Llegeix fitxers de partits i disponibilitats.
2. Filtra per modalitat, dates i fase.
3. Geocodifica adreces i calcula clusters geografics.
4. Construeix subgrups de partits per dia i pista.
5. Fusiona subgrups si son compatibles en temps i cluster.
6. Assigna tutors a subgrups amb Hungarian (`linear_sum_assignment`).
7. Fa una repesca segmentant subgrups fallits.
8. Desa assignacions, mapa i resum d'incidencies.

## Diagnosi Del Run 96

Run analitzat:

- `DesignationRun.id = 96`
- Nom: `Volei 24/4`
- Estat: `done`
- Modalitat: `VOLEIBOL`
- Partits: 101
- Assignats: 69
- No assignats: 32
- Incidencia aproximada: 31.7%
- Tutors amb disponibilitat: 60
- Tutors sense assignar al final: 4

Parametres rellevants del run:

- `cluster_eps_m = 600`
- `cluster_min_samples = 2`
- `max_partits_subgrup = 3`
- `gap_same_pitch_min = 90`
- `gap_diff_pitch_min = 120`
- `gap_diff_cluster_min = 150`
- `fase = FS2`

Desglossament dels 32 partits no assignats:

- `outside_availability_window`: 16
- `cross_cluster_without_vehicle`: 8
- `outlier_cluster_for_mobility_validation`: 8

Lectura important:

- La incidencia no es nomes un problema de clusteritzacio.
- Hi ha un problema d'optimitzacio global: alguns tutors poden estar sent usats en assignacions facilment cobertes mentre altres partits queden bloquejats per vehicle, finestra horaria o outliers.
- El sistema actual assigna inicialment un subgrup per tutor i nomes despres intenta rescatar. Aixo pot gastar recursos escassos, especialment tutors amb vehicle o tutors amb finestres llargues.

## Limitacions De L'Algorisme Actual

### 1. Optimitzacio Massa Local

L'assignacio inicial resol una matriu tutor-subgrup amb Hungarian. Aixo troba una combinacio barata entre tutors i subgrups, pero no modela be la ruta completa del tutor durant el dia.

Conseqüencia:

- Un tutor amb vehicle pot quedar assignat a un subgrup que tambe podria fer un tutor sense vehicle.
- Despres, quan cal cobrir una transicio entre clusters, ja no queda cap tutor adequat.
- La repesca reutilitza tutors, pero ja parteix d'una solucio inicial que pot haver pres decisions suboptimes.

### 2. Vehicle No Es Tracta Com A Recurs Escas

El motor valida mobilitat, pero no sembla reservar tutors amb vehicle per als casos que realment els necessiten.

En el run 96:

- 42 disponibilitats indiquen `No tinc Vehicle Propi`.
- Només 8 tenen `Cotxe`.
- 6 tenen `Moto`.
- 3 tenen `Bicicleta`.
- 1 te `Patinet electric`.

Si els tutors amb vehicle s'usen massa aviat en partits senzills, apareixen incidencies `cross_cluster_without_vehicle`.

### 3. Outliers Son Bloqueig Dur

Quan una seu queda com a outlier o sense cluster fiable, la validacio de mobilitat no pot decidir amb garanties. Ara aixo pot acabar com:

- `outlier_cluster_for_mobility_validation`
- `missing_cluster_for_mobility_validation`

En modalitats amb poques seus o seus disperses, aixo penalitza molt. L'usuari ara pot corregir clusters al preview, pero encara cal que el motor tingui una estrategia robusta quan queden outliers.

### 4. La Repesca Segmenta Pero No Reoptimitza Globalment

El rescue actual:

- Agafa subgrups fallits.
- Els parteix en segments contigus.
- Torna a provar amb tutors lliures.
- Despres prova reutilitzant tutors.

Pero no desfà assignacions inicials per millorar la cobertura total. Per tant, si una decisio inicial bloqueja 2 partits posteriors, el rescue pot no poder recuperar-los.

### 5. Avisos De Mobilitat Insuficients

Actualment s'avisen alguns conflictes de mobilitat, pero funcionalment interessa que qualsevol canvi de pista quedi avisat per revisio humana, encara que sigui viable.

Nova regla desitjada:

- Si un tutor te partits en mes d'una pista/seu en el mateix dia, s'ha de generar sempre un avis.
- Si el canvi es dins del mateix cluster i compleix gaps, ha de ser warning informatiu.
- Si el canvi es entre clusters i compleix gaps amb vehicle, ha de ser warning informatiu.
- Si el canvi es entre clusters sense vehicle o amb gap insuficient, ha de ser error o warning fort segons mode.
- Si hi ha outlier o cluster desconegut, ha de quedar avisat explicitament.

## Hipotesi Principal

La designacio actual pot no ser la mes optima possible. No vol dir que sigui incorrecta, sino que l'objectiu actual prioritza cost local de tutor-subgrup i despres intenta reparar. En casos tensos, caldria optimitzar primer la cobertura global i l'ús dels recursos escassos.

Objectiu recomanat:

1. Maximitzar nombre de partits assignats.
2. Minimitzar errors durs de mobilitat/disponibilitat.
3. Reservar tutors amb vehicle per necessitats reals de mobilitat.
4. Minimitzar warnings.
5. Minimitzar cost esportiu: nivell, classificacio, preferencies, etc.

## Proposta 1: Motor De Rutes Per Tutor

Canviar el model mental de "tutor contra subgrup" a "tutor contra ruta diaria".

Una ruta es una sequencia ordenada de segments que un tutor pot fer en un dia:

- Mateixa modalitat.
- Dins disponibilitat.
- Amb temps suficient entre partits.
- Amb mobilitat valida o avisada.
- Amb cost acumulat.

Exemple:

- Tutor A, 2026-04-24:
  - 18:00 Escola X
  - 19:30 Escola Y
  - 21:00 Escola Y

Cada transicio entre pistes calcula:

- mateix pitch?
- mateix cluster?
- clusters diferents?
- outlier?
- te vehicle?
- minuts disponibles?
- gap requerit?
- tipus d'avis/error?

Despres l'optimitzador escull un conjunt de rutes que maximitzi cobertura sense assignar un tutor dues vegades en conflicte.

Avantatge:

- Evita gastar tutors amb vehicle en assignacions que no els necessiten.
- Permet veure clarament quins tutors cobreixen mes partits.
- Dona millor base per explicar per que queden partits sense assignar.

Implementacio possible:

- Generar candidats de ruta per tutor i dia.
- Limitar combinatoria amb beam search o dynamic programming.
- Fer scoring multiobjectiu.
- Seleccionar rutes amb un solver simple inicialment: greedy iteratiu amb reoptimitzacio local, o ILP si es vol mes rigor.

## Proposta 2: Reserva De Tutors Amb Vehicle

Abans de l'assignacio inicial, classificar subgrups/segments segons necessitat de mobilitat:

- `vehicle_required`: segments o combinacions que impliquen canvi de cluster.
- `vehicle_preferred`: outliers o zones no fiables.
- `vehicle_not_needed`: mateixa pista o mateix cluster sense salt.

Regla recomanada:

- Tutors amb vehicle han de tenir una penalitzacio extra si s'assignen a feina que pot fer un tutor sense vehicle.
- Aquesta penalitzacio no ha de ser absoluta, pero ha de protegir recursos escassos.

Exemple de scoring:

- Tutor sense vehicle en mateixa pista: viable.
- Tutor sense vehicle dins mateix cluster: viable amb warning si canvia pista.
- Tutor sense vehicle entre clusters: no viable en mode estricte.
- Tutor amb vehicle entre clusters: viable si gap suficient, amb warning.
- Tutor amb vehicle en partit unic facil: viable pero amb cost extra si hi ha demanda pendent amb vehicle_required.

## Proposta 3: Outliers Com A Zona Virtual

No tractar sempre l'outlier com a bloqueig dur. Alternatives:

1. Nearest cluster:
   - Assignar temporalment l'outlier al cluster mes proper si esta dins un llindar ampli.
   - Marcar `cluster_status = virtual_nearest` o equivalent.
   - Generar warning sempre.

2. Zona manual:
   - Permetre que l'usuari assigni outliers a una zona/cluster des del preview.
   - Ja hi ha base per overrides manuals.

3. Distancia real:
   - Si es disposa de coordenades, calcular distancia aproximada entre seus.
   - Validar mobilitat per temps/distancia en lloc de cluster binari.

4. Mode permissiu amb warning:
   - Si no hi ha cluster pero la seu esta geocodificada, permetre assignacio amb warning si hi ha molt marge temporal.

## Proposta 4: Reoptimitzacio Despres De Rescue

El rescue actual recupera molt poc en el run 96:

- `rescue_segments_generated = 82`
- `rescue_matches_recovered = 1`

Aixo suggereix que segmentar mes no resol si els tutors adequats ja estan mal posicionats.

Millora proposada:

- Despres d'identificar pendents, detectar quins tutors assignats podrien desbloquejar-los.
- Provar swaps locals:
  - desassignar ruta/subgrup facil d'un tutor amb vehicle
  - passar-la a un tutor sense vehicle compatible
  - usar el tutor amb vehicle per recuperar pendent critic

Tipus de cerca:

- 1-swap: canviar assignacio entre dos tutors.
- 2-swap: alliberar un tutor amb vehicle fent dos canvis.
- augmenting path: trobar cadena de substitucions que incrementa cobertura.

Objectiu:

- Acceptar swaps si augmenten partits assignats.
- Si cobertura igual, acceptar si redueixen errors o warnings.

## Proposta 5: Pre-Diagnosi De Capacitat

Abans d'executar l'assignacio completa, calcular:

- Demanda per hora.
- Demanda per cluster.
- Demanda per zona/outlier.
- Tutors disponibles per hora.
- Tutors amb vehicle disponibles per hora.
- Tutors sense vehicle disponibles per cluster/pista.

Per al run 96, per exemple:

- A les 18:00 hi ha 38 partits, 12 pendents.
- A les 19:30 hi ha 16 partits, 6 pendents.
- Hi ha molts tutors sense vehicle i pocs amb vehicle.

Aquesta pre-diagnosi hauria de mostrar:

- Colls d'ampolla horaris.
- Colls d'ampolla de vehicle.
- Seus outlier que poden provocar bloqueig.
- Recomanacions concretes:
  - moure outlier a cluster manual
  - relaxar mobilitat
  - reduir buffer final
  - augmentar radi o usar zona virtual
  - demanar mes tutors amb vehicle

## Proposta 6: Modes De Rigor

Afegir perfils de motor configurables per run/modalitat:

### Mode Estricte

- Com ara o mes conservador.
- Cross-cluster sense vehicle prohibit.
- Outlier prohibit si afecta mobilitat.
- Canvi de pista sempre avisat.

### Mode Operatiu

- Cross-cluster sense vehicle pot ser warning si:
  - hi ha marge temporal molt superior al gap.
  - clusters son propers o distancia estimada baixa.
  - el tutor ja accepta mobilitat urbana.

### Mode Max Cobertura

- Prioritza reduir partits no assignats.
- Permet mes warnings.
- Mai hauria d'amagar avisos.
- Tot canvi de pista queda visible per revisio.

## Nova Regla D'Avis: Qualsevol Canvi De Pista

Requisit funcional explicit:

Sempre que un tutor tingui una sequencia de partits amb canvi de pista/seu en el mateix dia, el sistema ha de generar un avis revisable per l'usuari.

Categories suggerides:

- `same_cluster_pitch_change_warning`
  - Canvi de pista dins el mateix cluster.
  - Viable si compleix gap, pero revisar.

- `cross_cluster_with_vehicle_warning`
  - Canvi entre clusters amb vehicle i gap suficient.
  - Viable, pero revisar.

- `cross_cluster_without_vehicle`
  - Canvi entre clusters sense vehicle.
  - Error en mode estricte, warning fort en mode relaxat.

- `cross_cluster_gap_violation`
  - Canvi entre clusters amb gap insuficient.
  - Error.

- `outlier_mobility_warning`
  - Almenys una seu de la transicio no te cluster fiable.
  - Warning o error segons mode.

- `missing_cluster_mobility_warning`
  - Falta cluster o geocodificacio.
  - Warning o error segons mode.

La UI hauria de mostrar aquests avisos encara que la designacio sigui automatica i "valida".

## Indicadors Nous A Guardar Al Result Summary

Per fer el motor auditable, el `result_summary` hauria d'incloure:

- `coverage_by_hour`
- `coverage_by_cluster`
- `coverage_by_modality`
- `vehicle_usage_summary`
- `vehicle_reserved_count`
- `vehicle_used_on_easy_segments`
- `pitch_change_warning_count`
- `pitch_change_warnings`
- `route_summary_by_referee`
- `unassigned_by_reason_hour_cluster`
- `outlier_assignments_allowed`
- `relaxed_rule_applications`

## Recomanacio D'Implementacio Incremental

### Fase 1: Mes diagnosi i avisos

- Afegir warning per qualsevol canvi de pista.
- Separar warnings informatius d'errors bloquejants.
- Enriquir `result_summary` amb desglossaments per hora, cluster, vehicle i tutor.
- No canviar encara l'assignador.

### Fase 2: Penalitzacio de vehicles mal usats

- Afegir cost extra per usar tutor amb vehicle en subgrups que no requereixen vehicle quan hi ha demanda pendent vehicle_required.
- Comparar resultats amb run 96.

### Fase 3: Outliers virtuals

- Permetre nearest cluster o assignacio virtual amb warning.
- Integrar-ho amb el preview i amb les assignacions finals.

### Fase 4: Reoptimitzacio local

- Implementar swaps locals per desbloquejar pendents.
- Mesurar si augmenta cobertura sense multiplicar warnings greus.

### Fase 5: Motor de rutes

- Substituir progressivament l'assignacio tutor-subgrup per generacio i seleccio de rutes.
- Mantenir compatibilitat amb el format actual de `Assignment`.

## Criteris D'Exit

Per validar la millora, usar run 96 com a cas de prova:

- Reduir `unassigned_matches` per sota de 32.
- No introduir `mobility_errors` ocults.
- Generar warnings per tots els canvis de pista.
- Reduir `cross_cluster_without_vehicle`.
- Explicar clarament els pendents restants.
- Evitar que tutors amb vehicle quedin assignats a tasques facils si bloquegen pendents critics.

## Preguntes Per Al Subagent

1. Quants partits del run 96 es podrien recuperar nomes reassignant tutors amb vehicle?
2. Quins tutors amb vehicle estan usats en segments que no requerien vehicle?
3. Quins pendents `outside_availability_window` son realment impossibles i quins depenen del buffer final?
4. Quins outliers tenen coordenades i podrien rebre cluster virtual?
5. Quin impacte tindria avisar tots els canvis de pista en nombre de warnings?
6. Es suficient una reoptimitzacio local o cal un motor de rutes?


# Disseny De Rotacions: Ordre Competitiu I Franges Visuals

## Objectiu
- Fer coherent el comportament de les hores de les franges.
- Evitar que una franja creada "enmig" quedi funcionalment al final.
- Permetre franges visuals que poden solapar-se sense contaminar l'ordre real de competicio.
- Preparar el terreny per a moure elements amb drag and drop sense trencar notes ni jutges.

## Problema Actual

### Font de veritat equivocada per al cas d'us
- Avui la font de veritat del planner es `RotacioFranja.ordre`.
- `hora_inici` i `hora_fi` son dades visibles, pero no governen la posicio real de la franja.
- Quan es crea una franja nova manualment, sempre entra amb `max(ordre)+1`.
- Quan s'edita una franja, es reajusten les de sota segons l'ordre actual, no segons l'horari global.

### Consequencia funcional
- Una franja creada entre dues hores existents queda al final del programa.
- La taula es veu "estranya" respecte les hores que mostra.
- Notes, jutges i export consumeixen `franja__ordre`, de manera que la discrepancia no es nomes visual.

### Problema de model
- El mateix concepte `RotacioFranja` intenta representar dues coses diferents:
  - passos competitius reals del programa
  - elements visuals o de context com premis, descansos o separadors

### Problema de UI
- La graella actual es bona per a una sequencia lineal de files.
- No es bona per representar solapaments reals entre esdeveniments.
- Quan hi ha coincidencies com premis + escalfament, el template s'embolica perque esta modelant una timeline amb una taula de files.

## Principi De Disseny
- Hi ha d'haver una unica sequencia canonica per al que afecta ordre de pas, notes i jutges.
- Els elements visuals no han de modificar aquesta sequencia si no formen part del flux competitiu.
- El planner ha de distingir entre:
  - ordre competitiu
  - presentacio temporal del programa

## Proposta Recomanada

### Separar dos dominis

#### 1. Franges competitives
- Son les que defineixen l'ordre real de competicio.
- Governen:
  - assignacions a estacions
  - ordre efectiu a notes
  - ordre efectiu al portal de jutges
  - extrapolacio
  - export funcional del programa

#### 2. Esdeveniments visuals
- Son peces de timeline que descriuen el programa, pero no el pipeline de scoring.
- Exemples:
  - premis
  - escalfament general
  - obertura
  - separadors visuals
  - avisos de canvi de bloc
- Poden solapar-se entre elles o amb franges competitives.
- No tenen assignacions de grups o series.
- Es recomana distingir visualment amb colors de fons cada tipologia.

## Decisio De Model

### Opcio recomanada
- Mantenir `RotacioFranja` com a entitat del flux competitiu.
- Introduir una entitat nova per al programa visual.

### Nom possible
- `RotacioEvent`
- o `RotacioTimelineEvent`

### Camps proposats per a `RotacioTimelineEvent`
- `competicio`
- `hora_inici`
- `hora_fi`
- `tipus`
- `titol`
- `descripcio`
- `lane`
- `color`
- `scope`
- `estacio`
- `actiu`

### Significat dels camps nous
- `lane`
  - pista visual per separar esdeveniments solapats al planner
  - no te cap efecte funcional
- `scope`
  - `global`
  - `per_estacio`
- `estacio`
  - nomes s'utilitza si `scope = per_estacio`

## Invariants Funcionals

### Franges competitives
- Han de tenir una sequencia canonica unica.
- L'ordre canonic es el que consumeixen notes, jutges i export.
- No es poden solapar entre elles.
- Si una franja competitiva es mou temporalment, s'ha de recomputar la seva posicio canonica.
- Si una accio sobre una franja competitiva obliga a moure franges competitives posteriors, el sistema ha de proposar la reordenacio abans de persistir.

### Esdeveniments visuals
- Es poden solapar.
- No poden tenir assignacions.
- No poden influir en l'ordre competitiu.
- Es poden ocultar o simplificar en vistes que no siguin el planner.
- Son globals.
- Han d'apareixer a export.

## Regla Canonica Recomanada

### Per a franges competitives
- La posicio canonica s'ha de derivar de l'horari, no del simple ordre d'insercio.
- L'algoritme hauria de ser:
  - ordenar per `hora_inici`
  - desempat per `hora_fi`
  - desempat final per `id` o un `sort_key` explicit
- despres persistir `ordre` renumerat de forma compacta

### Consequencia
- `ordre` continua existint per compatibilitat i per consum intern.
- Pero deixa de ser "manual" i passa a ser una projeccio persistent de l'ordre temporal competitiu.
- El que mana es l'hora competitiva i el que importa funcionalment es la disposicio resultant a notes i jutges.

## Comportaments Esperats

### Crear franja competitiva manual
- Si es crea 09:20-09:40 entre 09:00-09:30 i 09:30-10:00:
  - s'insereix en la posicio temporal correcta
  - es renumera `ordre`
  - les vistes de notes i jutges passen a veure-la en aquesta posicio

### Editar hores d'una franja competitiva
- Si canvies una franja de 10:00-10:30 a 09:15-09:45:
  - la franja canvia de lloc dins la sequencia canonica
  - es renumera `ordre`
- Si el canvi afecta franges competitives posteriors:
  - el sistema calcula una proposta de reordenacio horaria
  - mante la durada de cada franja posterior
  - la primera posterior comenca a l'hora que acaba la franja editada
  - la resta queden encadenades
  - l'usuari pot acceptar o cancel.lar
- No s'hauria de persistir cap canvi parcial sense confirmacio quan hi ha efectes sobre franges posteriors.

### Inserir despres
- Ha de continuar existint com a accio rapida.
- Pero s'ha d'entendre com:
  - crear una franja nova contigua a la base
  - i recomputar ordre segons el temps resultant
- Si crea una cadena de canvis sobre franges competitives posteriors:
  - s'ha de mostrar la proposta abans de guardar

### Extrapolar
- Ha de seguir treballant nomes amb franges competitives.
- Els esdeveniments visuals no hi han d'entrar.

## Disseny D'UX Recomanat

### Vista principal
- Mantenir la graella central `franges competitives x estacions`.
- Aquesta graella nomes ha de mostrar franges competitives.

### Nova banda superior o paral.lela de timeline
- Afegir una capa visual separada per a esdeveniments globals.
- Pot ser:
  - una banda superior sobre la taula
  - o un panell lateral de timeline

### Que es veu a la timeline
- blocs temporals globals
- colors per tipus
- lanes separades quan hi ha solapaments

### Benefici
- La taula torna a ser simple i funcional.
- Els solapaments es resolen en un component visual dissenyat per aixo.
- No cal forcar premis o escalfaments a ser "files" amb el mateix pes que una franja competitiva.

## Drag And Drop

### Fase 1 recomanada
- Drag and drop nomes per a franges competitives.
- Moure una franja dins la llista competitiva equival a una reordenacio canonica coherent amb les hores.

### Recomanacio de comportament
- En deixar anar:
  - es calcula una proposta de nou horari
  - es recalcula `ordre`
  - es conserven durades
  - es recalculen hores en cadena
  - s'ha de confirmar abans de persistir
  - si alguna franja no te una durada fiable, el fallback predeterminat es 15 minuts

### Politica de durades al DnD
- La durada d'una franja existent s'ha de preservar sempre que sigui valida.
- El fallback de 15 minuts nomes s'ha d'utilitzar com a xarxa de seguretat.
- No s'ha d'utilitzar com a comportament normal si la durada original es coneguda.

### Mode recomanat de planner
- Introduir un concepte explicit de mode:
  - `horari encadenat`
  - `horari lliure`

### Horari encadenat
- Les franges competitives no se solapen.
- Moure una franja reencaixa la cadena.
- Es el millor mode per a competicions normals.

### Horari lliure
- Permet ajustar hores individualment.
- El sistema reordena `ordre` per hora, pero no forca continuitat exacta.
- Si hi ha buits, es respecten.
- Si hi ha solapaments competitius, es mostra error o advertencia forta.

### Recomanacio actual
- Amb les decisions de negoci tancades ara mateix, la prioritat real es `horari encadenat`.
- `horari lliure` es pot considerar una extensio futura si realment fa falta.

## Recomanacio Practica
- No intentaria resoldre DnD i solapaments visuals alhora en una sola fase.
- Primer faria coherent l'ordre competitiu.
- Despres afegiria la timeline visual.
- Finalment afegiria DnD a les franges competitives.

## Impacte Sobre Notes I Jutges

### Notes
- Han de continuar filtrant nomes franges competitives.
- Han de continuar ordenant per `franja__ordre`.
- La diferencia es que aquest `ordre` ja vindra derivat d'un ordre temporal coherent.

### Jutges
- Mateixa regla que notes.
- El portal nomes hauria de veure franges competitives.
- El portal no hauria de veure premis, escalfaments o separadors com a passos de competicio.

### Avantatge
- No cal reinventar el domini de scoring.
- Cal nomes protegir millor la frontera entre:
  - programa competitiu
  - programa visual

## Compatibilitat Amb El Codi Actual

### Compatible a curt termini
- El sistema actual ja tracta les franges no competitives com a gairebe alienes a scoring.
- Aixo facilita molt la separacio.

### Canvis de comportament importants
- `franja_create` no hauria de posar sempre al final.
- `franja_update_inline` no hauria d'encadenar sempre cap avall de forma cega.
- El planner no hauria de mostrar totes les files igual si no totes tenen el mateix rol.

### Politica legacy
- Legacy respecta el que hi ha.
- No s'ha de reinterpretar agressivament el programa historic existent.
- El nou comportament s'aplica a partir d'ara.
- La lectura de dades existents s'ha de mantenir compatible.

## Alternatives

### Alternativa A: mantenir un sol model i ordenar sempre per hora
- Pros:
  - menys migracio
  - menys models
- Contres:
  - continua barrejant competicio i programa visual
  - la UI seguira patint per representar solapaments
  - el domini quedara ambigu

### Alternativa B: mantenir un sol model i afegir DnD de files
- Pros:
  - sembla rapid
- Contres:
  - no resol la confusio entre hores i ordre
  - no resol els solapaments
  - converteix la UX en una capa per sobre d'un model ambigu

### Alternativa C: separar domini competitiu i domini visual
- Pros:
  - model net
  - millor base per timeline
  - menys risc sobre notes i jutges
- Contres:
  - requereix un petit salt de model i template

## Proposta De Fases

### Fase 1. Coherencia competitiva
- Reinterpretar `ordre` de franges competitives com a projeccio de l'ordre temporal.
- Crear i editar franges competitives inserint-les segons hora.
- Bloquejar els solapaments entre franges competitives.
- Quan una accio afecti franges competitives posteriors:
  - calcular proposta de reordenacio
  - mostrar dialeg de confirmacio
  - aplicar nomes si s'accepta
- No tocar encara la UX de solapaments visuals de forma ambiciosa.

### Fase 2. Timeline visual
- Crear `RotacioTimelineEvent`.
- Treure premis, escalfaments i separadors de la taula principal.
- Pintar-los en una banda de timeline separada.

### Fase 3. Drag and drop competitiu
- Afegir DnD de files competitives.
- La logica del DnD ha de ser consistent amb les hores.
- El drop ha de generar proposta, confirmacio i persistencia atomica.

## Fitxers A Modificar

### Fase 1. Necessaris
- `competicions_trampoli/models/rotacions.py`
  - si finalment es mante el model actual sense model nou, potser no caldra tocar-lo gaire
  - si afegim algun helper canonic o validacions de solapament, aquest es un punt natural
- `competicions_trampoli/views/rotacions/franges.py`
  - es el fitxer principal del canvi
  - `franja_create`
  - `franja_update_inline`
  - `franja_insert_after`
  - `franja_delete`
  - `rotacions_extrapolar`
  - probablement caldra extreure helpers comuns de reordenacio temporal
- `competicions_trampoli/views/rotacions/planner.py`
  - per decidir quines franges es mostren a la graella principal
  - per preparar millor el context si se separa mes clarament competitiu vs visual
- `competicions_trampoli/templates/competicio/rotacions_planner.html`
  - per ajustar la UI de creacio i edicio de franges
  - per deixar clar que la taula principal representa la sequencia competitiva
  - aqui tambe aniria el primer DnD de files si s'arriba a fase 3
- `competicions_trampoli/views/scoring/notes.py`
  - per revisar que continua consumint nomes franges competitives i que no depen de cap assumpcio antiga
- `competicions_trampoli/views/judge/portal.py`
  - mateix motiu que `notes.py`
- `competicions_trampoli/views/rotacions/export.py`
  - per assegurar que l'export segueix coherent amb la nova semantica de franges competitives i amb els esdeveniments globals
- `competicions_trampoli/tests/test_rotacions.py`
  - tests nous o ajustats per creacio, edicio, insercio i ordre temporal
- `competicions_trampoli/tests/test_team_scoring.py`
  - pot tenir proves que depenen de franges i ordre
- `competicions_trampoli/tests/test_inscripcions_sort_groups.py`
  - hi ha proves auxiliars que creen franges i poden necessitar ajust

### Fase 2. Si es crea model nou per timeline visual
- `competicions_trampoli/models/rotacions.py`
  - alta probabilitat d'afegir `RotacioTimelineEvent`
- `competicions_trampoli/migrations/...`
  - migracio nova per al model nou
- `competicions_trampoli/views/rotacions/planner.py`
  - carregar esdeveniments visuals separadament
- `competicions_trampoli/templates/competicio/rotacions_planner.html`
  - pintar banda o capa de timeline separada de la graella competitiva
- `competicions_trampoli/urls/rotacions.py`
  - si s'afegeixen endpoints propis per crear, editar o reordenar esdeveniments visuals
- `competicions_trampoli/views/rotacions/__init__.py`
  - per exportar noves vistes si es divideix el modul
- `competicions_trampoli/views/rotacions/export.py`
  - per incloure els esdeveniments globals a l'export

### Fase 3. Si es fa drag and drop de files competitives
- `competicions_trampoli/templates/competicio/rotacions_planner.html`
  - principal implementacio JS i markup del DnD de files
- `competicions_trampoli/urls/rotacions.py`
  - endpoint nou de reorder de franges competitives, si es fa servidor-side explicit
- `competicions_trampoli/views/rotacions/franges.py`
  - logica de persistencia del nou ordre i recalcul d'hores o de `ordre`
- `competicions_trampoli/tests/test_rotacions.py`
  - cobertura del contracte de reorder

### Fitxers Que No Haurien De Patir Canvis Grossos
- `competicions_trampoli/views/rotacions/assignments.py`
  - avui ja filtra les no competitives al guardar assignacions
  - en principi nomes requereix revisio, no refactor gran
- `competicions_trampoli/services/rotacions/rotacions_ordering.py`
  - en principi l'ordre intern per grups o series no hauria de canviar
  - nomes s'hauria de tocar si apareix una assumpcio forta sobre l'ordre de franges
- `competicions_trampoli/services/shared/competition_groups.py`
  - no sembla un punt principal del canvi

### Ordre Recomanat De Treball Sobre Fitxers
- primer `views/rotacions/franges.py`
- despres `views/rotacions/planner.py`
- despres `templates/competicio/rotacions_planner.html`
- despres validacio transversal a:
  - `views/scoring/notes.py`
  - `views/judge/portal.py`
  - `views/rotacions/export.py`
- finalment tests

## Decisions Que Et Recomano Validar
- Vols que les franges competitives permetin buits horaris reals o sempre han d'anar encadenades?
- Vols preservar `RotacioFranja.tipus` per compatibilitat un temps o prefereixes separar net des del principi?

## Decisions De Negoci Ja Tancades
- Les franges competitives no es poden solapar entre elles.
- Quan una insercio, edicio o moviment provoca conflicte temporal, el sistema ha de proposar una reordenacio horaria de les franges competitives posteriors.
- Aquesta reordenacio ha de:
  - mantenir la durada de cada franja posterior
  - fer que la primera posterior comenci a l'hora que acaba la franja inserida o moguda
  - encadenar la resta
- L'usuari ha de poder acceptar o cancel.lar aquesta proposta.
- Mana l'hora i `ordre` es deriva.
- El criteri funcional final es la disposicio resultant a notes i jutges.
- Premis, escalfaments i separadors son globals.
- Aquests esdeveniments visuals han d'apareixer a export.
- Els jutges nomes veuen franges competitives.
- Legacy respecta el que hi ha.
- El nou comportament s'aplica a partir d'ara.
- El drag and drop ha de ser coherent amb les hores.
- El drag and drop s'ha de confirmar abans de persistir si altera l'horari.
- La durada de les franges s'ha de preservar quan sigui coneguda.
- El fallback de durada per defecte es 15 minuts nomes com a xarxa de seguretat.

## Contracte Del Dialeg De Reordenacio Horaria

### Quan s'ha de mostrar
- Nomes quan una accio sobre una franja competitiva afecta temporalment una o mes franges competitives posteriors.
- Casos tipics:
  - crear franja competitiva
  - editar hores d'una franja competitiva
  - inserir despres
  - drag and drop de franges competitives

### Quan no s'ha de mostrar
- Si el canvi no afecta cap altra franja competitiva.
- Si l'operacio nomes toca esdeveniments visuals globals.

### Informacio minima que ha de mostrar
- Franja origen afectada.
- Tram antic i tram nou de la franja origen.
- Llista de franges competitives posteriors afectades.
- Per cada franja afectada:
  - titol
  - hora antiga
  - hora nova
  - durada preservada

### Missatge funcional que ha d'explicar
- Que l'ordre competitiu es recalculara a partir del nou horari.
- Que notes i jutges continuaran seguint la sequencia competitiva resultant.
- Que els esdeveniments visuals globals no entren en aquest recalcul.

### Accions del dialeg
- `Acceptar i reordenar`
- `Cancel.lar`

### Contracte de persistencia
- Si l'usuari accepta:
  - s'aplica tot en una sola operacio atomica
  - es persisteixen noves hores i nou `ordre`
- Si l'usuari cancel.la:
  - no s'ha de persistir cap canvi parcial
- Si no hi ha franges afectades:
  - no cal mostrar dialeg

## Recomanacio Final
- Faria aquest canvi amb una estrategia clara de separacio.
- No intentaria arreglar-ho nomes al template.
- No faria DnD abans de definir quina es la font de veritat.

La proposta que considero mes robusta es:
- `RotacioFranja` = sequencia competitiva canonica
- `RotacioTimelineEvent` = programa visual i solapable
- `ordre` = projeccio persistent de l'ordre temporal competitiu
- notes i jutges continuen vivint nomes sobre la sequencia competitiva

## Criteri D'Acceptacio Del Disseny
- Crear una franja competitiva "enmig" la situa on toca visualment i funcionalment.
- Moure o editar una franja competitiva no trenca l'ordre de notes ni jutges.
- Premis i escalfaments poden coexistir visualment sense embrutar la graella principal.
- El planner explica millor el programa i el pipeline real de competicio.

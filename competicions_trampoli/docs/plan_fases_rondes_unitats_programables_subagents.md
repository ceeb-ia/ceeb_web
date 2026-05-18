# Pla D'Arquitectura I Implementacio De Fases, Rondes I Unitats Programables

## Objectiu
- Dissenyar una evolucio del modul de competicions per suportar:
  - multiples instancies locals del mateix aparell base dins una competicio
  - fases o rondes per cada instancia local d'aparell
  - branques d'un arbre de fases
  - unitats programables precreades abans de saber els participants finals
  - ompliment posterior d'aquestes unitats a partir de classificacions confirmades
  - confirmacio total o parcial per particions
  - suport futur per individuals, equips i classificacions individuals que classifiquen equips
- Deixar un pla executable per futurs agents i subagents sense necessitat del context de conversa original.
- Evitar que futurs agents inventin contractes nous quan trobin buits: els dubtes oberts han de quedar explicitats.

## Estat Actual Del Sistema

### Models rellevants actuals
- `Aparell`
  - cataleg base d'aparells.
  - viu a `competicions_trampoli/models/competicio.py`.
- `CompeticioAparell`
  - representa avui un aparell dins una competicio.
  - te restriccio unica `competicio + aparell`.
  - aquesta restriccio impedeix tenir dues instancies locals del mateix aparell base dins una competicio.
- `ScoreEntry`
  - representa la nota individual.
  - clau unica legacy: `competicio + inscripcio + exercici + comp_aparell` quan `fase is null`.
  - clau unica scoped: `competicio + inscripcio + exercici + comp_aparell + fase` quan hi ha fase explicita.
  - `fase = null` representa la preliminar/flux legacy implicit.
- `TeamScoreEntry`
  - equivalent per unitats competitives d'equip.
  - tambe pot quedar scoped per fase amb la mateixa semantica de `fase = null` per legacy.
- `GrupCompeticio`
  - representa grups globals de competicio.
  - avui s'usen per la primera organitzacio de participants.
- `RotacioEstacio` i `RotacioAssignacio`
  - programen grups o series en franges i estacions.
  - apunten a `CompeticioAparell`, no a fase.
- `ClassificacioConfig`
  - calcula resultats amb schema declaratiu.
  - avui selecciona aparells per `comp_aparell_id`.
  - pot declarar abast de fase dins `schema.scope`:
    - implicit/preliminar
    - fase unica
    - per aparell en classificacions multiaparell.
- `JudgeDeviceToken`
  - avui esta lligat a un `CompeticioAparell`.
  - no coneix fases ni una home de portal.

### Estat funcional implementat a data d'aquesta actualitzacio
- Les fases avancades existeixen com a `CompeticioAparellFase`.
- Les unitats de fase existeixen com a `ProgramUnit` amb `ProgramUnitSlot`.
- La preliminar/default continua sent implicita i no es persisteix com a fase.
- El planner de fases permet:
  - crear fases avancades per aparell local
  - configurar origen i tall dins `phase.config`
  - crear unitats/places manuals
  - veure si una unitat esta programada a rotacions.
- El formulari d'origen i tall desa:
  - classificacio origen
  - regla `top_n`
  - nombre de classificats
  - reserves
  - mode global o per particio de classificacio
  - places per unitat
  - plantilla de nom per generar unitats.
- Encara no hi ha generacio automatica d'unitats/slots des d'aquest origen i tall.
- Notes pot seleccionar fase al panell central:
  - `Preliminar` continua usant `fase = null`
  - una fase avancada envia `fase_id`
  - les unitats de fase provenen de `ProgramUnitSlot`.
- El portal de jutges continua puntuant preliminar/legacy si no rep `fase_id`; la home de fases per jutges queda pendent.

### Limitacions actuals
- Ja es poden tenir dues instancies locals del mateix `Aparell` dins una competicio.
- Ja es poden separar notes de la mateixa inscripcio pel mateix `CompeticioAparell` en fases diferents.
- Encara falta portar aquesta separacio al portal de jutges amb una home de fases.
- Els grups actuals no serveixen com a grups de semifinal/final, perque son globals i no estan scoped per fase.
- Les rotacions actuals poden programar un grup mes d'una vegada en franges diferents, pero aixo no crea una segona participacio competitiva.
- Les classificacions calculen resultats i poden servir de font configurada per una fase, pero encara no materialitzen participants d'una fase posterior de manera automatica.

## Actualitzacio UI Snapshot - 2026-05-18

### Criteri de producte
- El planner ha de girar al voltant de l'arbre de fases. El drawer lateral es tracta com una eina suplementaria, no com el lloc principal on s'entenen les fases.
- `Origen i tall` desa una recepta: classificacio font, abast global/per particio, nombre de classificats, reserves i politica d'empats. No ha de crear grups ni congelar participants.
- `Grups dins de la fase` defineix l'estructura programable de la fase: contenidors, places i criteri de repartiment. Aquesta estructura ha de ser coherent amb la recepta de tall.
- `Estat de la fase` concentra el flux viu: previsualitzar el snapshot, congelar-lo, activar la fase per jutges i tancar/reobrir quan pertoqui.

### Implementacio UI aplicada
- Les accions de `preview_qualification`, `apply_qualification` i `regenerate_qualification` es mostren ara dins l'apartat `Estat de la fase` amb llenguatge de snapshot.
- L'apartat `Origen i tall` queda com a formulari de configuracio de recepta i usa el boto `Desar recepta`.
- L'apartat de grups parla de contenidors/grups de fase, no d'aplicar tall.
- La UI deixa una nota tecnica: el backend actual encara acobla `Congelar snapshot` amb l'ompliment de `ProgramUnit`/`ProgramUnitSlot`.

### Evolucio backend pendent
- Separar semanticament `preview snapshot`, `freeze snapshot` i `populate program units`.
- Fer que el snapshot congelat sigui el registre estable de participants classificats, reserves, particio d'origen i politica d'empats aplicada.
- Fer que la creacio/configuracio de grups sigui previa i independent del snapshot, validant que els slots totals no superen els classificats disponibles segons la recepta.
- Afegir doble validacio sempre que es modifiqui una recepta, grup o snapshot ja congelat, especialment si hi ha slots manuals, bloquejats, programats a rotacions o ja puntuats.
- Usar `Estat de la fase` per exposar el pas de `programada` a `activa` per al portal de jutges, i de `activa` a `tancada` quan el flux de competicio estigui complet.

## Decisions Tancades

### Separacio de conceptes
- `Aparell` continua sent el cataleg base.
- `CompeticioAparell` ha de passar a ser una instancia local d'aparell dins una competicio.
- Una competicio ha de poder tenir multiples `CompeticioAparell` que apunten al mateix `Aparell` base.
- Exemples valids:
  - `Trampoli masculi`
  - `Trampoli femeni`
  - `Trampoli pista A`
  - `Trampoli pista B`

### Fases
- Les fases no han de viure dins de `ClassificacioConfig`.
- Les fases han de viure sota la instancia local d'aparell (`CompeticioAparell`).
- El mode `simple` o `fases/rondes` es decideix per cada `CompeticioAparell`, no per tota la competicio.
- Una mateixa competicio pot tenir aparells locals simples i aparells locals amb fases alhora.
- Exemple:
  - `Trampoli masculi`: amb fases
  - `DMT mixt`: simple/legacy
- Una classificacio pot apuntar a una fase concreta com a ambit de calcul.
- Una fase pot tenir diverses classificacions associades.
- Una fase avancada ha de tenir una unica classificacio font per decidir com s'omple la fase seguent.
- Si calen dues semifinals amb fonts diferents, s'han de modelar com branques de l'arbre de fases.

### Arbre de fases
- Les fases no son nomes una llista plana.
- S'han de poder modelar com un arbre o grafic acotat:
  - preliminar
  - semifinal A
  - semifinal B
  - final
- En aquesta etapa conceptual es parla d'arbre, no de grafic arbitrari.
- Cada fase pot tenir una fase pare.
- Les fases paral.leles son branques.

### Programacio previa
- La competicio s'ha de poder programar abans de coneixer els participants finals.
- Aixo implica crear unitats programables i slots buits.
- Les unitats buides es poden publicar visualment com a previstes, pero no han de ser puntuables fins que estiguin omplertes i publicades.
- El sistema no ha d'inventar participants futurs.

### Ompliment des de classificacio
- Una classificacio calcula resultats.
- Una regla de pas o qualificacio interpreta aquests resultats.
- La regla de pas omple slots de la fase desti.
- La fase desti materialitza participants, reserves i pendents.

### Confirmacio
- La confirmacio pot ser:
  - completa per tota una fase
  - parcial per particions concretes
- Exemple:
  - confirmar `Infantil F` i obrir semifinal per aquesta particio mentre `Junior M` encara esta pendent.

### Particions
- Les particions no estan limitades a categoria.
- Les particions poden derivar de camps d'entrada Excel o de particions custom similars a classificacions.
- La classificacio font pot estar particionada d'una manera i la fase desti pot reagrupar amb un criteri mes concret.
- Exemple:
  - classificacio font per `categoria`
  - fase desti programada per `categoria + subcategoria`

### Quotes i talls
- Cada fase pot tenir regla comuna de places.
- Cada fase pot tenir overrides per particio.
- Exemple:
  - top 8 per defecte
  - `Infantil F`: top 6
  - `Junior M`: top 4
- Si hi ha menys participants disponibles que places, no es un error.
- S'ha de generar avis:
  - "Nomes hi ha 5 participants disponibles de 8 places configurades."

### Empats
- La classificacio font aplica primer els seus desempats propis.
- Si despres encara hi ha empat real a la zona de tall, la politica es de fase.
- La politica d'empats ha de ser configurable a la fase o regla de pas.
- Modes previstos:
  - `classification_order`: respectar l'ordre final de la classificacio
  - `include_all_at_cut`: incloure tots els empatats al tall
  - `manual_decision`: deixar els empatats com a pendents de decisio

### Equips
- El disseny ha de ser general, no nomes per inscripcions individuals.
- Una regla pot classificar:
  - inscripcions
  - equips
  - `TeamCompetitiveSubject`
  - equips derivats d'una classificacio individual
- Quan una classificacio individual classifica un equip, el default ha de ser:
  - passa l'equip complet dins el context de la classificacio font
- Aquesta politica ha de ser configurable.

### Reserves
- Reserva es un estat mes dins els slots o participants de fase.
- Les reserves poden sortir de la mateixa regla de pas.
- Una reserva pot passar a classificat manualment si hi ha baixa o retirada.

### Portal de jutges
- El portal de jutges hauria d'evolucionar cap a una home.
- La home mostra les fases que el jutge pot puntuar.
- Les fases pendents no han de ser puntuables fins que estiguin confirmades/publicades.
- Exemple:
  - `Trampoli masculi / Preliminar`: oberta
  - `Trampoli masculi / Semifinal`: pendent
  - `Trampoli masculi / Final`: pendent

## No Objectius Inicials
- No implementar un grafic arbitrari de dependencias entre fases.
- No automatitzar canvis destructius en fases ja publicades sense confirmacio humana.
- No substituir de cop tot el sistema de grups actual.
- No obligar tota una competicio a activar fases/rondes si nomes alguns aparells locals ho necessiten.
- No canviar la semantica de classificacions mes del necessari per apuntar a fases.
- No exigir que tots els fluxos antics usin fases des del primer dia.
- No trencar competicions existents que nomes tenen una fase implicita per aparell.

## Model Conceptual Proposat

### `CompeticioAparell`
- Passa a ser instancia local de l'aparell.
- Continua apuntant a `Aparell` base.
- Ha de tenir nom local configurable.
- Exemples:
  - `Trampoli masculi`
  - `Trampoli femeni`
- Ha de poder heretar schema/config de l'aparell base.
- Ha de poder tenir overrides locals.

### `CompeticioAparellFase`
- Nova entitat proposada.
- Representa una fase o node de l'arbre dins un `CompeticioAparell`.
- Camps conceptuals:
  - `competicio`
  - `comp_aparell`
  - `parent`
  - `nom`
  - `codi`
  - `ordre`
  - `estat`
  - `source_mode`
  - `source_classificacio`
  - `qualification_config`
  - `grouping_config`
  - `publish_config`
  - `created_at`
  - `updated_at`

### Estats de fase
- Estats orientatius:
  - `planned`: configurada pero no omplerta
  - `generated`: unitats i slots creats
  - `partially_confirmed`: algunes particions confirmades
  - `confirmed`: participants confirmats
  - `published`: visible i puntuable pels jutges
  - `closed`: notes tancades
  - `stale`: depen d'una classificacio font que ha canviat

### `ProgramUnit`
- Nova entitat proposada.
- Unitat programable generica dins una fase.
- No s'ha de limitar a "grup".
- Pot representar:
  - grup de fase
  - serie
  - bloc
  - equip
  - unitat custom
- Camps conceptuals:
  - `fase`
  - `nom`
  - `tipus`
  - `ordre`
  - `partition_key`
  - `partition_values`
  - `capacity`
  - `status`
  - `metadata`

### `ProgramUnitSlot`
- Nova entitat proposada.
- Representa una placa programable dins una unitat.
- Permet programar abans d'omplir.
- Camps conceptuals:
  - `unit`
  - `slot_index`
  - `ordre`
  - `status`
  - `subject_kind`
  - `subject_id`
  - `source_classificacio`
  - `source_particio_key`
  - `source_position`
  - `source_score`
  - `source_row`
  - `locked`

### Estats de slot
- Estats orientatius:
  - `empty`
  - `filled`
  - `reserve`
  - `pending_decision`
  - `withdrawn`
  - `manual`

### `FasePartitionState`
- Nova entitat o estructura proposada.
- Permet confirmar per particio.
- Camps conceptuals:
  - `fase`
  - `partition_key`
  - `status`
  - `source_snapshot_hash`
  - `confirmed_at`
  - `published_at`
  - `warnings`

### `QualificationRun`
- Nova entitat o estructura proposada.
- Representa una execucio de la regla de pas.
- Camps conceptuals:
  - `fase_origen`
  - `fase_desti`
  - `source_classificacio`
  - `status`
  - `generated_at`
  - `confirmed_at`
  - `snapshot_hash`
  - `warnings`
  - `summary`

## Shape Conceptual De Configuracio

### Fase inicial
```json
{
  "source_mode": "initial",
  "grouping": {
    "mode": "from_base_groups"
  },
  "publish": {
    "judge_visible_when": "published"
  }
}
```

### Fase avancada
```json
{
  "source_mode": "classification",
  "source_classificacio_id": 123,
  "target_partition": {
    "fields": ["categoria", "subcategoria"]
  },
  "quota": {
    "default": 8,
    "overrides": {
      "categoria=Infantil|subcategoria=F": 6,
      "categoria=Junior|subcategoria=M": 4
    }
  },
  "reserves": {
    "default": 2
  },
  "tie_policy": {
    "mode": "manual_decision"
  },
  "subject_policy": {
    "mode": "same_subject",
    "team_from_individual": "whole_team_in_source_context"
  },
  "grouping": {
    "mode": "one_unit_per_partition",
    "slot_order": "classification_reverse"
  }
}
```

### Modes de grouping inicials recomanats
- `from_base_groups`
  - converteix els `GrupCompeticio` actuals en unitats de la primera fase.
- `one_unit_per_partition`
  - crea una unitat per cada particio desti.
- `split_by_capacity`
  - divideix una particio en diverses unitats de mida maxima.
- `manual`
  - crea estructura base i permet edicio manual.

### Modes d'ordre de slots inicials recomanats
- `classification_order`
- `classification_reverse`
- `base_order`
- `random_seeded`
- `manual`

## Compatibilitat Amb El Sistema Actual

### Mode per aparell local
- La compatibilitat i el mode nou s'han de decidir per `CompeticioAparell`.
- No hi ha d'haver una bandera global de competicio que obligui tots els aparells a funcionar igual.
- Una competicio pot barrejar:
  - aparells simples que continuen usant el flux actual
  - aparells amb fases/rondes i unitats programables
- Aquesta decisio queda tancada a Fase 0.

### Flux simple/legacy
- El flux actual continua sent valid com a mode simple.
- El mode simple usa:
  - `GrupCompeticio`
  - `RotacioAssignacio`
  - notes actuals scoped per `CompeticioAparell`
- El mode simple s'ha de mantenir especialment per:
  - competicions existents
  - aparells locals nous que no necessiten rondes
  - casos operativament petits on una fase implicita es suficient

### Fase implicita
- La fase inicial/preliminar es implicita i no es persisteix com a `CompeticioAparellFase`.
- La fase inicial surt del flux existent:
  - grups creats a inscripcions
  - grups o series presents al planner de rotacions
  - notes actuals scoped per `CompeticioAparell`
- El codi `DEFAULT` queda reservat i no s'ha de crear des de la capa de fases.
- Si un aparell no te fases avancades configurades, no cal cap registre de fase.

### Grups actuals
- `GrupCompeticio` continua existint.
- Ha de quedar definit com:
  - grup base de competicio
  - usat com a entrada natural de primeres fases
- No s'ha d'utilitzar com a grup de semifinal/final.
- Les fases avancades han d'usar `ProgramUnit`.

### Rotacions actuals
- Al principi, les rotacions poden continuar funcionant amb `GrupCompeticio` per flux legacy.
- El nou flux ha d'anar cap a rotacions de `ProgramUnit`.
- No s'ha de forcar una substitucio total en la primera migracio.
- Recomanacio tancada de Fase 0:
  - crear una assignacio paral.lela per `ProgramUnit` abans que barrejar totes les responsabilitats dins `RotacioAssignacio`.
- Motiu:
  - `RotacioAssignacio` queda com a contracte estable per flux simple/legacy.
  - les unitats programables de fase poden evolucionar sense fer ambigu el model antic.

### Jutges actuals
- Els tokens actuals apunten a `CompeticioAparell`.
- El flux nou ha de permetre tokens que apuntin a:
  - una instancia local d'aparell
  - un conjunt de fases
  - eventualment una fase concreta
- La home del portal pot ser una capa compatible que segueixi acceptant tokens antics.

## Arquitectura Recomanada Per Fases De Canvi

## Fase 0. Contracte I ADR

### Objectiu
- Congelar contractes abans d'escriure migracions.
- Documentar decisions irreversibles.

### Owner
- Integrador principal.

### Write set
- `competicions_trampoli/docs/plan_fases_rondes_unitats_programables_subagents.md`
- Opcionalment un ADR separat si es vol.

### Done
- Decisions de model confirmades.
- Mode fases/rondes confirmat com a configuracio per `CompeticioAparell`, no per `Competicio`.
- Convivencia confirmada entre aparells simples i aparells amb fases dins la mateixa competicio.
- Flux simple/legacy confirmat com a suportat, no obsolet immediatament.
- Recomanacio confirmada:
  - `CompeticioAparellFase`
  - `ProgramUnit`
  - `ProgramUnitSlot`
  - `FasePartitionState`
  - `QualificationRun`
- Recomanacio confirmada per rotacions:
  - model/assignacio paral.lela per `ProgramUnit`, mantenint `RotacioAssignacio` per legacy.
- Dubtes oberts revisats.
- No hi ha implementacio productiva encara.

## Fase 1. Multiples Instancies Locals Del Mateix Aparell

### Objectiu
- Relaxar la restriccio actual `competicio + aparell`.
- Permetre dues instancies locals del mateix `Aparell` dins una competicio.
- No introduir encara fases funcionals.

### Write set principal
- `competicions_trampoli/models/competicio.py`
- migracio nova
- formularis i UI de configuracio d'aparells
- tests d'aparells/competicio

### Tasques
- Afegir camps locals a `CompeticioAparell`:
  - `nom_local` o equivalent
  - possible `codi_local`
- Substituir la restriccio unica `competicio + aparell`.
- Nova restriccio suggerida:
  - `competicio + codi_local` o `competicio + nom_local` si es decideix fer-lo unic.
- Ajustar formulari de creacio d'aparell de competicio.
- Permetre seleccionar el mateix aparell base mes d'una vegada.
- Assegurar que tots els llistats mostren el nom local si existeix.

### Guardrails
- No duplicar massivament schemas.
- No crear copies fisiques d'`Aparell`.
- `Aparell` continua sent el root/base.
- `CompeticioAparell` es la instancia local.

### Tests
- Una competicio pot tenir `Trampoli masculi` i `Trampoli femeni` apuntant al mateix `Aparell`.
- Les notes continuen separades per `comp_aparell_id`.
- Els builders de classificacions mostren instancies locals diferenciades.

### Tancament Implementat
- Estat: completada.
- Implementacio feta:
  - `CompeticioAparell` te `nom_local` i `codi_local`.
  - `Aparell` continua sent el cataleg base/root.
  - `CompeticioAparell` es la instancia local dins una competicio.
  - S'ha eliminat la unicitat `competicio + aparell`.
  - S'ha afegit la unicitat `competicio + codi_local` quan `codi_local` no es buit.
  - El formulari de configuracio permet afegir el mateix aparell base mes d'una vegada.
  - Si el codi local es deixa buit, es genera a partir del codi base amb sufixos tipus `TRA-2`.
  - La UI i els payloads principals mostren `display_nom` i `display_codi`.
  - Les plantilles de classificacions resolen els aparells de competicio amb codi local.
  - Els clones/baselines copien tambe la identitat local.
- Migracio:
  - `0059_competicioaparell_local_identity.py`.
  - Backfill inicial:
    - `nom_local` hereta `Aparell.nom`.
    - `codi_local` hereta `Aparell.codi`.
- Guardrails respectats:
  - No s'han creat copies fisiques d'`Aparell`.
  - No s'han introduit fases funcionals.
  - No s'ha modificat la semantica de `ScoreEntry`.
  - No s'ha substituit el sistema antic de grups ni rotacions.
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py sqlmigrate competicions_trampoli 0059`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.access.test_aparell_catalog_ownership --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.classificacions.test_templates_global competicions_trampoli.tests.classificacions.test_templates_competition --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - La fase 2 ha de construir sobre `CompeticioAparell` com a instancia local.
  - Encara no hi ha cap camp `mode simple/fases`; aixo queda pendent per fases posteriors.
  - En una mateixa competicio ja poden conviure diferents instancies locals, pero totes segueixen funcionant en mode simple/legacy fins que s'introdueixi el model de fases.

### Tancament Addicional: Schema Local
- Motiu:
  - La primera implementacio de Fase 1 separava identitat local (`nom_local`, `codi_local`), pero el builder de puntuacio de competicio encara podia editar el `ScoringSchema` global de l'`Aparell` base.
  - Aixo feia que dues instancies locals del mateix aparell compartissin canvis tecnics de schema, que no encaixa amb el concepte d'instancia local.
- Decisio:
  - El `ScoringSchema` global de `Aparell` queda com a plantilla/base.
  - El flux de competicio per `CompeticioAparell` ha de crear i editar un `ScoringSchema` local lligat a `comp_aparell`.
  - Si no existeix schema local, la lectura pot heretar el global.
  - En el moment d'editar des d'una competicio, es crea un override local copiant l'schema global efectiu.
- Implementacio feta:
  - Afegida resolucio comuna:
    - lectura efectiva: local si existeix, si no global.
    - edicio de competicio: assegurar schema local per `CompeticioAparell`.
  - Actualitzats els fluxos de:
    - builder de schema de puntuacio
    - guardat de notes
    - actualitzacions incrementals
    - pantalla de notes
    - API de notes
    - builder i validacions de classificacions
  - Ajustada validacio de `ScoringSchema` per permetre schemas locals sense ocupar la unicitat global de `aparell`.
  - Corregit el formulari legacy de `CompeticioAparell`:
    - el boto `Puntuacio` en mode edicio apunta a `scoring_schema_update` amb `competicio.id + comp_aparell.id`.
    - ja no apunta a `aparell_scoring_schema_update`, que edita el schema global del cataleg.
    - en mode creacio, el boto queda desactivat fins que existeixi la instancia local.
- Contracte resultant:
  - Editar el schema global d'un `Aparell` afecta nomes els aparells locals que encara no tenen override.
  - Editar el schema des d'una competicio afecta nomes aquell `CompeticioAparell`.
  - Dues instancies locals del mateix `Aparell` poden tenir schemas diferents.
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.team.test_builder_and_schema_resolution --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.access.test_aparell_catalog_ownership --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.classificacions.test_builder_hydration competicions_trampoli.tests.classificacions.test_templates_competition --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.judge.test_package_contract competicions_trampoli.tests.scoring.judge.test_updates_cursor --verbosity 1 --keepdb`.

## Fase 2. Model De Fases Sense Canviar Runtime De Notes

### Objectiu
- Introduir `CompeticioAparellFase` com a estructura de dades.
- No crear cap fase unica/default persistent.
- La fase inicial/preliminar continua sent implicita i gestionada per inscripcions + rotacions.
- Encara no obligar el scoring runtime a usar fase.

### Write set principal
- nou model a `models/competicio.py` o modul nou dedicat
- migracio nova
- admin basic
- tests de migracio/model

### Tasques
- Crear model de fase amb camps minims:
  - `competicio`
  - `comp_aparell`
  - `parent`
  - `nom`
  - `codi`
  - `ordre`
  - `estat`
  - `config`
- No fer backfill de fases per aparells existents.
- Reservar el codi `DEFAULT` per evitar que la UI o serveis crein una fase inicial falsa.

### Guardrails
- No tocar encara `ScoreEntry`.
- No tocar encara `RotacioAssignacio`.
- No tocar encara `JudgeDeviceToken`.

### Tests
- Un `CompeticioAparell` nou no crea cap fase automatica.
- Una fase no pot pertanyer a un `CompeticioAparell` d'una altra competicio.
- L'arbre no permet parent d'una altra instancia.
- El codi `DEFAULT` queda rebutjat.

### Tancament Implementat
- Estat: completada i reconduida.
- Implementacio feta:
  - Afegit `CompeticioAparellFase` a `models/competicio.py`.
  - Camps implementats:
    - `competicio`
    - `comp_aparell`
    - `parent`
    - `nom`
    - `codi`
    - `ordre`
    - `estat`
    - `config`
    - `created_at`
    - `updated_at`
  - Estats disponibles:
    - `planned`
    - `generated`
    - `partially_confirmed`
    - `confirmed`
    - `published`
    - `closed`
    - `stale`
  - Afegida unicitat `competicio + comp_aparell + codi`.
  - Afegides validacions de coherencia:
    - la fase ha de pertanyer a la mateixa competicio que el seu `comp_aparell`
    - la fase pare ha de pertanyer al mateix `CompeticioAparell`
    - es rebutgen cicles directes o indirectes en l'arbre de fases
    - `config` ha de ser un objecte JSON
  - Afegit admin basic per `CompeticioAparellFase`.
  - Afegit paquet de servei `services/fases`.
  - Rebutjat el codi reservat `DEFAULT`.
  - Eliminats els helpers de fase default persistent.
  - La fase inicial/preliminar queda fora del model de fases i continua vivint al flux existent d'inscripcions + rotacions.
- Migracio:
  - `0060_competicioaparellfase.py`.
  - Crea la taula de fases.
  - No fa backfill de cap fase default.
- Guardrails respectats:
  - No s'ha afegit dimensio de fase a `ScoreEntry`.
  - No s'ha afegit dimensio de fase a `TeamScoreEntry`.
  - No s'ha modificat `ClassificacioConfig`.
  - No s'ha modificat `JudgeDeviceToken`.
  - No s'ha modificat `RotacioAssignacio`.
  - El runtime de notes, classificacions, rotacions i portal de jutges continua funcionant per `CompeticioAparell` com abans.
- Tests afegits:
  - contracte del model de fase
  - scoping per `CompeticioAparell`
  - unicitat de codi dins un aparell local
  - validacio de parent d'un altre aparell local
  - validacio de `comp_aparell` d'una altra competicio
  - no creacio automatica de fases
  - codi `DEFAULT` reservat
  - guardrail que `ScoreEntry` i `TeamScoreEntry` encara no tenen camp de fase
  - migracio `0060` sense backfill
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.access.test_aparell_catalog_ownership --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - No hi ha fase default persistent.
  - La Fase 3 pot construir `ProgramUnit` i `ProgramUnitSlot` nomes sota fases avancades.
  - La Fase 5 podra fer que `ClassificacioConfig` apunti a una fase, pero aquesta iteracio ho ha deixat expressament fora.
  - La Fase 8 haura d'afegir fase a `ScoreEntry` i `TeamScoreEntry`; aquesta iteracio nomes deixa el punt d'ancoratge.

## Fase 3. Unitats Programables I Slots

### Objectiu
- Introduir la capa programable generica.
- Permetre crear unitats i slots buits abans de saber participants.

### Write set principal
- models nous:
  - `ProgramUnit`
  - `ProgramUnitSlot`
  - opcional `FasePartitionState`
- migracions
- serveis de generacio d'unitats
- tests unitaris

### Tasques
- Modelar unitats scoped per fase.
- Modelar slots amb `subject_kind` i `subject_id` opcionals.
- Implementar generador inicial:
  - `from_base_groups`
  - `one_unit_per_partition`
  - `split_by_capacity`
- Implementar estats:
  - unitat `planned/filled/confirmed/published`
  - slot `empty/filled/reserve/pending_decision/withdrawn/manual`

### Guardrails
- No assumir que tot subjecte es una `Inscripcio`.
- `subject_kind` ha de permetre extensio.
- No fer que `ProgramUnit` sigui nomes "grup".

### Tests
- Es poden crear unitats buides amb N slots.
- Una unitat pot tenir slots sense participant.
- Una unitat pot tenir slots de reserva.
- La mateixa inscripcio pot existir en unitats de fases diferents.

### Tancament Implementat
- Estat: completada com a base backend.
- Implementacio feta:
  - Afegit `ProgramUnit` a `models/competicio.py`.
  - Afegit `ProgramUnitSlot` a `models/competicio.py`.
  - `ProgramUnit` viu sota `CompeticioAparellFase`.
  - `ProgramUnitSlot` viu sota `ProgramUnit`.
  - Les unitats programables no depenen de `GrupCompeticio`.
  - Els slots poden existir sense participant.
  - Els slots poden apuntar genericament a subjectes amb:
    - `subject_kind`
    - `subject_id`
  - Els slots poden conservar traçabilitat d'origen amb:
    - `source_classificacio`
    - `source_particio_key`
    - `source_position`
    - `source_score`
    - `source_row`
  - Afegits estats de `ProgramUnit`:
    - `planned`
    - `generated`
    - `confirmed`
    - `published`
  - Afegits estats de `ProgramUnitSlot`:
    - `empty`
    - `filled`
    - `reserve`
    - `pending_decision`
    - `withdrawn`
    - `manual`
  - Afegit admin basic per `ProgramUnit` i `ProgramUnitSlot`.
- Migracio:
  - `0061_program_units.py`.
  - Crea taules per unitats programables i slots.
  - No fa backfill massiu automatic de grups legacy.
- Serveis afegits:
  - `services/fases/program_units.py`
  - `create_program_unit_with_empty_slots`
  - `create_program_unit_from_subjects`
  - `fill_program_unit_slots`
  - `create_units_one_per_partition`
  - `create_units_split_by_capacity`
  - `next_program_unit_order`
- Guardrails respectats:
  - No s'ha modificat `ScoreEntry`.
  - No s'ha modificat `TeamScoreEntry`.
  - No s'ha modificat el portal de jutges.
  - No s'ha modificat el runtime de notes.
  - No s'ha modificat el runtime de classificacions.
  - No s'ha modificat el planner de rotacions.
  - `GrupCompeticio` continua sent legacy/base; `ProgramUnit` es la nova capa programable per fases.
- Tests afegits:
  - creacio d'unitat amb slots buits
  - validacio que slots `filled/reserve/manual` requereixen subjecte
  - validacio que slots `empty` no poden tenir subjecte
  - unicitat d'ordre d'unitat dins una fase
  - mateixa inscripcio present en slots de fases diferents
  - generacio `one_unit_per_partition`
  - generacio `split_by_capacity`
  - guardrail que `ScoreEntry` i `TeamScoreEntry` encara no tenen `fase` ni `program_unit`
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - La Fase 4 pot construir un planner UI sobre `CompeticioAparellFase`, `ProgramUnit` i `ProgramUnitSlot`.
  - La Fase 5 pot fer que `ClassificacioConfig` calculi sobre fases, pero encara no ho fa.
  - La Fase 6 pot omplir slots a partir d'una classificacio font amb regles de pas reals.
  - La Fase 7 haura de decidir com programar `ProgramUnit` en rotacions.
  - La Fase 8 continuara sent la que separi notes per fase; aquesta fase nomes crea la capa programable.

## Fase 4. Planner De Fases I Plantilles Reutilitzables

### Objectiu
- Crear una UI/servei per configurar fases, branques, quotes, particions i grouping.
- Permetre guardar configuracions reutilitzables similars a plantilles.

### Write set principal
- models o serveis de plantilles de fases
- vistes de configuracio de `CompeticioAparell`
- templates nous o ampliats
- tests backend de persistencia

### Tasques
- Afegir planner de fases dins configuracio de l'aparell local.
- Permetre:
  - crear fase
  - crear branca
  - seleccionar classificacio font
  - configurar target partition
  - configurar quota default i overrides
  - configurar reserves
  - configurar tie policy
  - configurar grouping
  - generar/previsualitzar unitats i slots
- Afegir plantilles de fases:
  - globals o per usuari
  - reutilitzables entre competicions
  - sense IDs locals quan siguin exportables

### Guardrails
- No barrejar aquesta UI amb el builder de classificacions mes del necessari.
- Les classificacions es referencien com a font; no contenen les fases.
- Les plantilles no han de capturar IDs locals de competicio si son globals.

### Tests
- Es pot crear un arbre:
  - preliminar
  - semifinal A
  - semifinal B
  - final
- Es pot guardar i aplicar una plantilla.
- Els overrides de quota per particio persisteixen.

### Tancament Implementat
- Estat: completada com a planner basic.
- Implementacio feta:
  - Afegida vista `CompeticioAparellFasesPlanner`.
  - Afegida ruta:
    - `trampoli_aparell_fases`
    - `competicio/<pk>/notes/trampoli/aparells/<app_id>/fases/`
  - Afegit template:
    - `templates/competicio/fases_planner.html`
  - Afegit enllaç `Fases` a la llista d'aparells locals.
  - Afegits formularis:
    - `CompeticioAparellFaseForm`
    - `ProgramUnitManualForm`
    - `ProgramUnitPartitionForm`
  - Afegit servei d'orquestracio:
    - `services/fases/planner.py`
  - El planner permet:
    - veure fases d'un `CompeticioAparell`
    - no crear ni mostrar fase default persistent
    - crear fases avancades filles o paral.leles
    - crear unitats buides amb N slots
    - crear una unitat per particio manual
    - veure slots i subjectes assignats quan ja existeixen
- Guardrails respectats:
  - No s'ha barrejat amb el builder de classificacions.
  - No s'ha modificat `ClassificacioConfig`.
  - No s'ha modificat el runtime de classificacions.
  - No s'ha modificat el runtime de notes.
  - No s'ha modificat el portal de jutges.
  - No s'ha modificat rotacions.
  - El planner treballa sobre `CompeticioAparellFase`, `ProgramUnit` i `ProgramUnitSlot`.
- Abast ajornat:
  - Plantilles reutilitzables de fases.
  - Configuracio completa de quotes i overrides.
  - Configuracio completa de reserves.
  - Politica d'empats.
  - Seleccio de classificacio font com a regla de pas real.
  - Preview sofisticada o drag-and-drop.
  - Publicacio real cap al portal de jutges.
- Tests afegits:
  - el planner no crea fase default en obrir-se
  - el planner mostra fases avancades i unitats sense exposar payloads de score
  - la llista d'aparells enllaça al planner
  - es pot crear una fase avancada via POST
  - es pot crear una unitat manual amb slots buits via POST
  - es pot crear una unitat de particio via POST
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.access.test_aparell_catalog_ownership --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - La Fase 5 pot afegir `fase_id` o scope equivalent a classificacions.
  - La Fase 6 pot usar les unitats i slots existents per omplir fases desti des de classificacions font.
  - Les plantilles reutilitzables poden quedar com una extensio abans de Fase 10.

## Fase 4b. UI Comuna De Fases Per Competicio

### Objectiu
- Reconduir el planner basic de fases cap a una pantalla comuna de competicio.
- Tenir una sola entrada `Fases` on es vegin tots els aparells locals.
- Mantenir cada arbre de fases scoped per `CompeticioAparell`.
- Fer evident que la fase preliminar/default es implicita i no editable des de fases.

### Decisio UI
- La pantalla ha de ser comuna per competicio, no una pantalla aillada per aparell.
- Dins la pantalla comuna:
  - selector o tabs d'aparells
  - resum global d'estat per aparell
  - arbre de fases de l'aparell seleccionat
  - panell de blocs `ProgramUnit` de l'aparell seleccionat
- La preliminar/base nomes es mostra com a resum informatiu:
  - origen: grups creats a inscripcions
  - programacio: planner de rotacions
  - no te formularis d'edicio dins fases

### Tasques
- Crear o reconduir la ruta de fases cap a una vista comuna de competicio.
- Mostrar tots els `CompeticioAparell` actius amb estat resumit:
  - sense fases avancades
  - amb fases configurades
  - amb blocs generats
  - amb blocs pendents de programar a rotacions
- En seleccionar un aparell:
  - mostrar arbre de fases avancades
  - crear fase filla o paral.lela
  - configurar criteris basics de pas i agrupacio
  - generar o editar blocs `ProgramUnit`
  - mostrar slots buits/omplerts quan existeixin
- Afegir indicador de programacio a rotacions per cada `ProgramUnit`:
  - `Pendent de programar`
  - `Programat a rotacions`
  - si es possible, mostrar franja/estacio on esta programat
- Afegir enllac directe al planner de rotacions filtrable o amb context visual cap a l'aparell/bloc.

### Guardrails
- No crear fase default persistent.
- No permetre editar la preliminar/base des de fases.
- No duplicar la programacio de rotacions dins fases.
- No fer puntuable una `ProgramUnit` nomes pel fet d'estar programada a rotacions.
- No tocar `ScoreEntry`, `TeamScoreEntry` ni portal de jutges en aquesta fase.

### Criteris De Tancament
- Des de la pantalla comuna es pot entendre l'estat de fases de tots els aparells.
- Es pot crear i mantenir l'arbre de fases avancades per aparell.
- Es poden generar blocs `ProgramUnit` des de la UI comuna.
- Cada bloc mostra clarament si ja esta programat a rotacions.
- El flux mental queda clar:
  - fases defineix arbre, criteris i blocs previstos
  - rotacions agenda aquests blocs
  - scoring/jutges vindran en una fase posterior

### Tests
- La vista comuna mostra tots els aparells actius de la competicio.
- La vista no crea ni mostra cap fase default persistent.
- Crear una fase avancada des de l'aparell seleccionat persisteix correctament.
- Crear `ProgramUnit` des de l'aparell seleccionat persisteix sota la fase correcta.
- Un bloc programat a rotacions apareix marcat com a programat.
- Un bloc no programat apareix marcat com a pendent.

### Tancament Implementat
- Estat: completada.
- Implementacio feta:
  - S'ha reconduit la UI de fases cap a una pantalla comuna per competicio.
  - Afegida ruta comuna:
    - `trampoli_fases`
    - `competicio/<pk>/notes/trampoli/fases/`
  - La ruta antiga per aparell continua existint com a entrada compatible:
    - `trampoli_aparell_fases`
    - `competicio/<pk>/notes/trampoli/aparells/<app_id>/fases/`
  - La UI s'ha modularitzat dins el paquet `fases`, separant el context de vista, accions i presentacio del planner.
  - Afegit paquet de vistes:
    - `views/competition/fases/planner.py`
    - `views/competition/fases/actions.py`
  - Afegit servei de context:
    - `services/fases/dashboard.py`
  - Afegits templates parcials:
    - `templates/competicio/fases/planner.html`
    - `templates/competicio/fases/_header.html`
    - `templates/competicio/fases/_app_selector.html`
    - `templates/competicio/fases/_forms.html`
    - `templates/competicio/fases/_phase_flow.html`
    - `templates/competicio/fases/_phase_node.html`
    - `templates/competicio/fases/_program_unit_row.html`
  - La pantalla comuna permet veure els aparells locals de la competicio i seleccionar l'aparell actiu.
  - La pantalla queda continguda dins una superficie general amb fons propi per no confondre's amb la imatge/fons global de l'aplicacio.
  - Cada aparell conserva el seu arbre de fases avancades scoped per `CompeticioAparell`.
  - La preliminar implicita es mostra com a node arrel visual de l'arbre, encara que no existeixi com a registre persistent.
  - Les fases sense `parent` indiquen explicitament que pengen visualment de la preliminar implicita.
  - La gestio de `ProgramUnit` queda integrada en el flux de fases sense substituir el planner de rotacions.
  - Cada `ProgramUnit` mostra si esta programat a rotacions o pendent de programar.
  - Quan una unitat esta programada, la UI mostra una etiqueta de franja/estacio.
  - El planner s'ha fet mes explicit i menys ambigu:
    - mostra un flux de treball `crear fase -> origen i tall -> unitats i places -> rotacions/notes`
    - deixa clar que crear una fase nomes crea el contenidor
    - substitueix progressivament "bloc/slot" per "unitat competitiva/plaça" a la UI.
  - Afegit formulari real d'origen i tall:
    - `PhaseSourceCutForm`
    - accio POST `configure_source_cut`
    - persistencia dins `CompeticioAparellFase.config`
  - El `phase.config` desa actualment:
    - `source.classificacio_id`
    - `source.classificacio_nom`
    - `source.tipus`
    - `cut.mode`
    - `cut.qualifiers_count`
    - `cut.reserve_count`
    - `cut.partition_mode`
    - `cut.unit_capacity`
    - `cut.unit_name_template`
  - Cada fase mostra ara un resum d'estat:
    - fase creada
    - origen i tall configurats o pendents
    - places assignades
    - unitats programades a rotacions.
  - Afegida accio segura d'eliminacio de fases:
    - nomes es poden eliminar fases buides
    - nomes es poden eliminar fases sense fases filles
    - les fases amb blocs o branques mostren l'accio bloquejada
  - La preliminar/base queda tractada com a estat implicit i informatiu, no com a fase editable.
- Guardrails respectats:
  - No s'ha creat cap fase default persistent.
  - No s'ha fet editable la preliminar/base des de la UI de fases.
  - No s'ha duplicat la programacio de rotacions dins fases.
  - No s'ha convertit cap `ProgramUnit` en puntuable pel sol fet d'existir, estar prevista o estar programada a rotacions.
  - No s'han canviat `ScoreEntry`, `TeamScoreEntry` ni el portal de jutges.
  - Configurar origen i tall no genera unitats automaticament ni sobreescriu slots.
  - La classificacio continua sent font; no es converteix en propietaria de la fase.
- Tests afegits/ajustats:
  - La vista comuna mostra tots els aparells locals actius i respecta l'aparell seleccionat.
  - La vista no crea fase default en obrir-se.
  - La llista d'aparells enllaca a la nova ruta comuna amb `?app=<id>`.
  - La UI marca unitats programades i pendents de programar a rotacions.
  - Una fase buida i sense fills es pot eliminar.
  - Una fase amb blocs no es pot eliminar des de la UI.
  - Els POSTs legacy de crear fase, bloc manual i bloc per particio continuen funcionant.
  - El POST `configure_source_cut` desa `phase.config` i la UI mostra el resum resultant.
- Verificacio executada:
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.rotacions.test_program_unit_assignments --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - La Fase 5 pot afegir scope de classificacions per fase sense assumir cap fase default persistent.
  - La Fase 6 pot consumir `phase.config.source` i `phase.config.cut` per previsualitzar i omplir slots de `ProgramUnit`.
  - Encara falta una accio explicita de `previsualitzar/generar unitats` des del tall configurat.
  - La Fase 7 pot connectar el planner de rotacions amb les unitats de fases avancades mantenint fases com a definicio i rotacions com a agenda.
  - La Fase 8 i la Fase 10 hauran de decidir quan una fase o unitat passa a ser puntuable i visible per jutges.

## Fase 5. Classificacions Scoped Per Fase

### Objectiu
- Fer que `ClassificacioConfig` pugui calcular sobre una fase o conjunt acotat de fases.
- Mantenir compatibilitat amb classificacions existents per `comp_aparell`.

### Write set principal
- `models/classificacions.py`
- `services/classificacions/engine/loaders.py`
- `services/classificacions/engine/orchestrator.py`
- builder de classificacions
- tests de classificacions

### Tasques
- Afegir camp o schema per indicar `fase_id`.
- Adaptar loaders per carregar `ScoreEntry`/`TeamScoreEntry` de la fase quan el runtime ja la suporti.
- En fase transitoria, l'absencia de fase explicita equival al comportament inicial/preliminar actual.
- Builder ha de mostrar:
  - aparell local
  - fase
- Permetre classificacions multiples dins una fase.

### Guardrails
- No fer que una classificacio sigui propietaria de la fase.
- No impedir classificacions globals legacy sense fase explicita.

### Tests
- Classificacio legacy continua funcionant.
- Classificacio sense fase explicita dona el mateix resultat que abans.
- Classificacio scoped a fase avancada nomes veu slots/participants/notes d'aquella fase.

### Tancament implementat
- Afegit scope de fase dins el schema de classificacions:
  - `scope.mode = implicit|phase`
  - `scope.fase_id`
  - `scope.mode = per_app`
  - `scope.apps[comp_aparell_id] = implicit|phase`
- La preliminar implicita continua sent el default i no es crea cap fase persistent.
- Afegit servei `services/classificacions/phase_scope.py` per normalitzar i validar l'abast de fase.
- El motor de classificacions propaga el scope fins als loaders.
- En mode transitori, una classificacio scoped a fase avancada filtra participants pels `ProgramUnitSlot` de la fase:
  - `subject_kind=inscripcio`
  - `subject_kind=team_unit`
  - estats `filled` o `manual`
- El schema legacy i el normalitzador de particions preserven el nou `scope`.
- El builder de classificacions exposa les fases configurades de la competicio i permet seleccionar:
  - `Preliminar implicita`
  - una fase avancada compatible amb els aparells seleccionats.
- En classificacions multiaparell, el builder mostra una fila per aparell seleccionat:
  - cada aparell pot quedar a `Preliminar implicita`
  - o apuntar a una fase avancada propia.
- Validacions afegides:
  - la fase ha d'existir dins la mateixa competicio
  - si hi ha aparells seleccionats, la fase ha de pertanyer a un d'aquests aparells.
  - en `per_app`, cada fase ha de pertanyer exactament a l'aparell de la seva fila.
- No s'ha afegit cap camp de fase a `ScoreEntry` ni a `TeamScoreEntry`; aixo queda per la Fase 8.
- No s'ha convertit `ClassificacioConfig` en propietari de cap fase.
- Tests afegits:
  - `competicions_trampoli.tests.classificacions.test_phase_scope`
  - cobertura de filtre per slots de fase
  - cobertura de filtre independent per aparell amb `scope.per_app`
  - cobertura de validacio de fase vs aparell seleccionat
  - cobertura de persistencia del scope.
- Verificacio:
  - `docker compose exec -T web python manage.py check`
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.classificacions.test_phase_scope competicions_trampoli.tests.classificacions.test_builder_hydration competicions_trampoli.tests.fases --verbosity 1 --keepdb`

### Notes per fases seguents
- La Fase 6 pot consumir classificacions scoped com a font per omplir slots d'una fase desti.
- La Fase 8 haura de decidir la separacio real de notes per fase/unitat i ajustar el portal de jutges.

## Fase 6. Regles De Pas I Ompliment De Slots

### Objectiu
- Implementar el servei que agafa una classificacio font i omple slots d'una fase desti.
- Consumir la configuracio d'origen i tall ja desada a `CompeticioAparellFase.config`.

### Write set principal
- serveis nous:
  - `services/fases/qualification.py`
  - `services/fases/program_units.py`
- models opcionals:
  - `QualificationRun`
  - `FasePartitionState`
- tests de qualificacio

### Tasques
- Llegir `phase.config.source` i `phase.config.cut` com a contracte inicial.
- Carregar la classificacio font seleccionada (`ClassificacioConfig`).
- Calcular/previsualitzar files candidates abans de modificar slots.
- Calcular proposta de qualificats per particio.
- Aplicar:
  - `cut.qualifiers_count`
  - `cut.reserve_count`
  - `cut.partition_mode`
  - `cut.unit_capacity`
  - `cut.unit_name_template`
  - quota default
  - quota overrides
  - reserves
  - tie policy
  - subject policy
  - target partition
- Generar warnings:
  - menys participants que places
  - empat al tall
  - classificacio incompleta
  - slots insuficients
  - participants retirats/exclosos
- Omplir slots buits o actualitzar proposta.
- Permetre confirmacio parcial per particio.
- Calcular `snapshot_hash` de la classificacio font.
- Marcar `stale` si la font canvia despres.

### Guardrails
- No publicar automaticament als jutges sense confirmacio.
- No sobreescriure slots manuals sense avis/confirmacio.
- No assumir que el subjecte font i desti son del mateix tipus.

### Tests
- Top N normal.
- Menys participants que places.
- Empat al tall amb cada politica.
- Reserves.
- Confirmacio parcial.
- Recalcul amb font canviada marca `stale`.
- Classificacio individual que classifica equip complet per defecte.

### Prerequisit implementat
- El planner de fases ja permet desar una configuracio basica d'origen i tall.
- Contracte actual dins `phase.config`:
```json
{
  "source": {
    "classificacio_id": 123,
    "classificacio_nom": "Preliminar TRA",
    "tipus": "individual"
  },
  "cut": {
    "mode": "top_n",
    "qualifiers_count": 8,
    "reserve_count": 2,
    "partition_mode": "source_partitions",
    "unit_capacity": 4,
    "unit_name_template": "{fase} - {particio}"
  }
}
```
- Aquest prerequisit nomes desa configuracio.
- Encara falta:
  - preview de classificats/reserves
  - generacio automatica de `ProgramUnit`
  - ompliment de `ProgramUnitSlot`
  - confirmacio parcial
  - deteccio de stale/snapshot.

### Tancament inicial implementat
- Estat: implementacio inicial del tall congelat completada.
- Decisio funcional aplicada:
  - La classificacio es continua calculant al motor de classificacions.
  - La fase desti no queda dependent en viu de la classificacio font.
  - En aplicar el tall, el resultat queda congelat dins `ProgramUnit` i `ProgramUnitSlot`.
  - Canvis posteriors a la classificacio o a les notes d'origen no reescriuen automaticament la fase desti.
- Implementacio feta:
  - Afegit servei:
    - `services/fases/qualification.py`
  - Afegides operacions:
    - `preview_qualification(fase)`
    - `apply_qualification(fase)`
    - `qualification_is_stale(fase)`
  - El servei llegeix el contracte existent dins `phase.config`:
    - `source.classificacio_id`
    - `cut.mode`
    - `cut.qualifiers_count`
    - `cut.reserve_count`
    - `cut.partition_mode`
    - `cut.unit_capacity`
    - `cut.unit_name_template`
  - Suport inicial implementat:
    - tall `top_n`
    - mode global
    - mode per particions de la classificacio font
    - reserves
    - avis si hi ha menys participants que places
    - avis d'empat real a la zona de tall
  - En aplicar el tall:
    - es creen `ProgramUnit` en estat `generated`
    - s'omplen `ProgramUnitSlot` amb estat `filled` o `reserve`
    - es desa `source_classificacio`
    - es desa `source_particio_key`
    - es desa `source_position`
    - es desa `source_score`
    - es desa `source_row`
    - es desa `qualification.snapshot_hash` dins `fase.config`
    - la fase desti passa a estat `generated`
  - Si la classificacio font esta scoped a una fase persistent, `apply_qualification` exigeix que la fase origen estigui:
    - `confirmed`
    - o `closed`
  - La preliminar implicita continua sense fase persistent i pot actuar com a font legacy.
  - Si la fase desti ja te unitats, l'aplicacio queda bloquejada per defecte per evitar sobreescriptures accidentals.
  - S'ha deixat un cami intern `replace_existing` protegit contra slots manuals o bloquejats.
- UI i planner:
  - Afegides accions al planner de fases:
    - `preview_qualification`
    - `apply_qualification`
  - Afegida seccio `Qualificacio congelada` a la pantalla comuna de fases.
  - El preview mostra resum de participants/reserves, places, unitats i warnings.
- Guardrails respectats:
  - No s'ha creat cap fase default persistent.
  - No s'ha convertit `ClassificacioConfig` en propietaria de la fase.
  - No es recalculen ni reescriuen slots automaticament quan canvia la font.
  - No s'ha canviat encara el portal de jutges.
  - No s'ha implementat confirmacio parcial persistent per particio.
- Tests afegits/ajustats:
  - `competicions_trampoli.tests.fases.test_qualification`
  - Ajustos al contracte basic del planner de fases.
  - Cobertura de:
    - preview i aplicacio del tall
    - congelacio de participants/reserves en slots
    - bloqueig si la fase origen persistent no esta confirmada/tancada
    - deteccio `stale` sense reescriure slots
    - exposicio d'accions al planner
- Verificacio executada:
  - `docker compose run --rm web python manage.py check`
  - `docker compose run --rm web python manage.py test competicions_trampoli.tests.fases.test_qualification competicions_trampoli.tests.fases.test_basic_planner_contract --verbosity 1`
  - `docker compose run --rm web python manage.py test competicions_trampoli.tests.fases competicions_trampoli.tests.classificacions.test_phase_scope competicions_trampoli.tests.rotacions.test_program_unit_assignments competicions_trampoli.tests.scoring.notes.test_notes_api --verbosity 1`
- Pendent identificat a la iteracio inicial:
  - Resolts en el tancament complet: `QualificationRun`, `FasePartitionState`, confirmacio parcial, politica configurable d'empats i controls de regeneracio.
  - Es mante fora de Fase 6 el flux complet per equips derivats quan una classificacio individual classifica un equip complet.

### Tancament complet de Fase 6
- Estat: Fase 6 tancada a nivell intern de planner, sense entrar encara a portal ni publicacio a jutges.
- Persistencia d'execucions:
  - Afegits i connectats `QualificationRun` i `FasePartitionState`.
  - El preview del planner desa un run `previewed`.
  - Cada `apply_qualification` crea un run `applied` amb fase desti, classificacio font, hash, resum, warnings i payload.
- Confirmacio per particio:
  - En aplicar el tall, cada particio queda en `FasePartitionState.status=generated`.
  - `confirm_qualification_partition(fase, partition_key)` confirma nomes aquella particio.
  - Si totes les particions estan confirmades, la fase passa a `confirmed`; si nomes una part esta confirmada, passa a `partially_confirmed`.
  - Les unitats de la particio confirmada passen a `ProgramUnit.status=confirmed`.
- Stale i regeneracio:
  - `qualification_is_stale(fase)` compara el hash congelat amb un preview recalculat.
  - El planner mostra indicador de font canviada quan la classificacio font ja no coincideix amb el hash congelat.
  - `mark_qualification_stale_if_needed(fase)` marca run aplicat, particions i fase com `stale`.
  - La regeneracio nomes substitueix la proposta amb confirmacio explicita.
  - Si hi ha slots manuals o bloquejats, el servei requereix confirmacio especifica (`allow_replace_protected=True`).
  - No hi ha reescriptura automatica de slots per canvis de la font.
- Empats:
  - `classification_order`: respecta l'ordre calculat per la classificacio.
  - `include_all_at_cut`: inclou tots els empatats al tall com a `filled`.
  - `manual_decision`: deixa tots els empatats al tall com a `pending_decision`.
  - La politica es desa a `phase.config.cut.tie_policy` des del planner.
- UI minima del planner:
  - Accio `Previsualitzar tall`.
  - Accio `Aplicar tall` per generar unitats, slots, run i particions `generated`.
  - Llista de particions generades dins cada fase.
  - Boto `Confirmar particio` per particio generada.
  - Indicador `Font canviada` / `Stale` quan la font ha canviat.
- Guardrails mantinguts:
  - No es publica res automaticament als jutges.
  - No es crea cap fase default persistent.
  - No es toca el portal de jutges.
  - No es reescriuen unitats existents sense accio explicita de l'usuari.
- Tests afegits/ajustats:
  - Runs persistits i particions generades.
  - Confirmacio de particio.
  - Empats `manual_decision` i `include_all_at_cut`.
  - Regeneracio protegida amb slots bloquejats/manuals.
  - Contracte del planner amb apply, confirmacio de particio i regeneracio.
- Verificacio executada:
  - `docker compose run --rm web python manage.py check`
  - `docker compose run --rm web python manage.py test competicions_trampoli.tests.fases.test_qualification competicions_trampoli.tests.fases.test_basic_planner_contract --verbosity 1`
- Fora de Fase 6:
  - Publicacio al portal de jutges.
  - Flux complet per equips derivats quan una classificacio individual classifica un equip complet.

## Fase 7. Rotacions Sobre Unitats Programables

### Objectiu
- Fer que el planner de rotacions pugui programar `ProgramUnit`.
- No trencar rotacions legacy de `GrupCompeticio`.

### Write set principal
- models de rotacions o model paral.lel
- `views/rotacions/*`
- `services/rotacions/*`
- templates de planner
- tests de rotacions

### Opcio A
- Estendre `RotacioAssignacio` amb suport a `ProgramUnit`.

### Opcio B
- Crear taula nova:
  - `RotacioAssignacioProgramUnit`

### Recomanacio inicial
- Preferir Opcio B si evita fer massa ambigu el model actual.
- Mantenir legacy estable.

### Tasques
- Permetre arrossegar unitats programables a franges/estacions.
- Mostrar placeholders:
  - `Semifinal Infantil F - 8 places pendents`
- Quan els slots s'omplen, la rotacio conserva la unitat.
- Evitar que el canvi de participants trenqui la programacio de la unitat.

### Tests
- Una unitat buida es pot programar.
- Una unitat omplerta conserva franja/estacio.
- Les rotacions legacy continuen funcionant.

### Tancament Implementat
- Estat: completada.
- Implementacio feta:
  - Afegit `RotacioAssignacioProgramUnit` com a taula d'enllac entre una cel.la del planner (`RotacioAssignacio`) i una `ProgramUnit`.
  - `RotacioAssignacio` continua sent el contracte estable de la graella de rotacions.
  - Les claus del planner passen a admetre:
    - `g:<id>` per grups d'inscripcions
    - `s:<id>` per series d'equip
    - `pu:<id>` per blocs/unitats de fases avancades
  - El backend valida que una `ProgramUnit` nomes es pugui programar a una estacio del seu mateix `CompeticioAparell`.
  - El planner de rotacions mostra les `ProgramUnit` en una seccio propia de `Fases`, separada de `Grups` i `Equips`.
  - El desat de rotacions persisteix els enllacos `pu:<id>` i els retorna en el `grid_json` en recarregar.
  - L'extrapolador de franges conserva les unitats programables a la seva estacio d'aparell, sense fer-les rotar cap a altres aparells.
  - L'export de rotacions carrega tambe els enllacos a `ProgramUnit` i pot resoldre labels de blocs de fase.
- Migracio:
  - `0062_rotacioassignacioprogramunit.py`.
- Guardrails respectats:
  - No s'ha fet que fases programin literalment la competicio.
  - No s'ha canviat el runtime de notes ni de jutges.
  - No s'han eliminat ni modificat els fluxos legacy de grups i series.
  - No s'ha convertit la fase preliminar/default en cap registre persistent.
- Tests afegits:
  - `competicions_trampoli.tests.rotacions.test_program_unit_assignments`.
  - Cobertura de sidebar `pu:<id>`, persistencia de l'enllac, recarrega de grid, i compatibilitat legacy de grups/series.
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py migrate`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.rotacions.test_program_unit_assignments --verbosity 1 --keepdb`.
- Nota de verificacio:
  - El paquet complet `competicions_trampoli.tests.rotacions` continua mostrant una fallada existent en `RotationOrderingDisplayTests.test_judge_portal_uses_first_app_franja_order_by_default_and_allows_override`, esperant `Base 3` al portal de jutges. La fallada es reprodueix aillada amb test DB neta i no toca el flux `ProgramUnit` implementat en aquesta fase.

## Fase 8. Scoring I Notes Scoped Per Fase

### Objectiu
- Fer que les notes estiguin lligades a fase o a unitat programable.
- Evitar col.lisions entre preliminar, semifinal i final del mateix aparell local.

### Write set principal
- `models/scoring.py`
- migracions
- `services/scoring/scoring_subjects.py`
- `views/scoring/*`
- `views/judge/*`
- templates de notes
- tests de scoring/jutges

### Tasques
- Afegir dimensio de fase a `ScoreEntry` i `TeamScoreEntry`.
- Actualitzar claus uniques:
  - incloure fase o una unitat equivalent.
- Actualitzar `score_store_key` per incloure fase quan pertoqui.
- Actualitzar resolucio de subjectes:
  - subjectes puntuables provenen de slots publicats de la fase.
- Actualitzar panell de notes per mostrar fases i unitats.
- Preservar comportament legacy quan no hi ha fase explicita.

### Guardrails
- Migracio de dades ha de deixar scores existents sense fase explicita o mapejats a un valor nul/implicit compatible.
- No perdre videos existents.
- No trencar endpoints legacy sense fase explicita.

### Tests
- Mateixa inscripcio pot tenir score a preliminar i final.
- Score legacy continua accessible sense fase explicita.
- Panell de notes nomes mostra slots publicats.
- Slots pendents no son puntuables.

### Tancament Implementat
- Estat: completada per al panell central de Notes i runtime administratiu; el portal de jutges scoped per fase queda a Fase 9.
- Implementacio feta:
  - `ScoreEntry` te camp opcional `fase`.
  - `TeamScoreEntry` te camp opcional `fase`.
  - `fase = null` representa la preliminar/flux legacy implicit.
  - Les claus uniques s'han separat en:
    - unicitat legacy quan `fase is null`
    - unicitat scoped per fase quan `fase is not null`
  - S'ha afegit validacio que la fase pertanyi a la mateixa competicio i al mateix `CompeticioAparell`.
  - Els helpers de scoring poden crear o recuperar notes amb `fase_id`.
  - Els loaders de classificacions ara carreguen notes de la fase seleccionada quan el scope es de fase.
  - Els fluxos legacy de notes i jutges filtren `fase is null` per no barrejar notes de fases avancades.
  - El panell central de Notes mostra un filtre de `Fase`:
    - `Preliminar` equival a `fase = null`
    - una fase avancada envia `fase_id`.
  - El manifest lazy de Notes exposa fases per aparell i unitats de fase.
  - Les unitats de fase en Notes provenen de `ProgramUnit` i `ProgramUnitSlot`.
  - Les taules lazy de Notes carreguen participants de slots `filled` o `manual`.
  - Les claus locals de Notes i el guardat inclouen `fase_id` quan toca.
  - Els avisos de Notes respecten la fase seleccionada.
  - S'ha afegit un servei central d'elegibilitat de fase:
    - `fase = null` continua sent preliminar/legacy i es considera puntuable.
    - una fase avancada es puntuable si la fase esta `published` o si la `ProgramUnit` concreta esta `published`.
    - nomes els slots `filled` i `manual` son puntuables.
    - slots `pending_decision`, `reserve`, `empty` i equivalents no entren a Notes ni accepten guardat.
  - El manifest i les taules de Notes amaguen fases/unitats que encara no son puntuables.
  - `scoring_save` i `scoring_save_partial` rebutgen amb `403` subjectes que no formen part d'un slot publicat/puntuable de la fase demanada.
  - El context multimedia del panell central de Notes accepta `fase_id` i carrega el video de jutge del score d'aquella fase, no el legacy.
  - Els payloads de cerca/context de Notes propaguen `fase_id`/`phase_id` per mantenir els deep links interns i el playback dins la mateixa fase.
- Migracio:
  - `0063_score_entries_phase_scope.py`.
- Guardrails respectats:
  - No s'ha creat cap fase default persistent.
  - Les notes existents queden com a legacy amb `fase = null`.
  - Els endpoints legacy sense `fase_id` continuen filtrant `fase is null`.
  - No s'ha canviat encara el portal de jutges cap a home de fases; aquest tall queda a Fase 9.
- Fora d'abast i traslladat a Fase 9:
  - Deep links i tokens de jutge scoped per fase.
  - Home del portal de jutges amb selector de fases disponibles.
  - Publicacio cap a jutges i control d'acces per token de fase.
- Nota important:
  - El portal de jutges continua puntuant preliminar/legacy si no rep `fase_id`.
  - La home de fases per jutges queda dins Fase 9.
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases competicions_trampoli.tests.classificacions.test_phase_scope --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.scoring.notes.test_notes_api --verbosity 1 --keepdb`.
  - `docker compose run --rm web python manage.py test competicions_trampoli.tests.scoring.notes.test_phase_eligibility competicions_trampoli.tests.scoring.notes.test_notes_api --verbosity 1 --noinput`.

## Fase 9. Portal De Jutges Amb Home De Fases

### Objectiu
- Fer que el portal de jutges mostri fases disponibles per puntuar.

### Write set principal
- `models/judging.py`
- `views/judge/portal.py`
- `views/judge/admin.py`
- templates de portal
- tests de jutges

### Tasques
- Evolucionar permisos de token:
  - per aparell local
  - per fase
  - per conjunt de fases
- Crear home de portal:
  - llista fases puntuables
  - estat de cada fase
  - acces a unitats publicades
- Permetre que una fase aparegui quan:
  - esta `published`
  - te unitats amb slots puntuables
  - el token te permis
- Mantenir deep links legacy quan token apunta a un sol aparell/fase.

### Guardrails
- No mostrar fases pendents com puntuables.
- No deixar que un jutge entri a slots `empty` o `pending_decision`.
- Els tokens antics han de continuar sent utilitzables en el flux inicial/preliminar implicit.

### Tests
- Portal home mostra preliminar oberta.
- Semifinal pendent no es puntuable.
- Semifinal apareix despres de confirmacio/publicacio.
- Token restringit a una fase no veu altres fases.

## Fase 10. Publicacio, Estat I Recalculs

### Objectiu
- Formalitzar el cicle de vida.
- Gestionar fonts canviades, stale state i regeneracions.

### Write set principal
- serveis de fase
- views del planner
- tests d'estat

### Tasques
- Tancar fase.
- Confirmar particio.
- Publicar particio/fase.
- Reobrir fase.
- Detectar classificacio font canviada.
- Marcar desti com `stale`.
- Permetre regenerar proposta sense trepitjar canvis manuals sense confirmacio.

### Guardrails
- No fer actualitzacions destructives automaticament.
- Sempre conservar traçabilitat de l'origen.

### Tests
- Reobrir preliminar marca semifinal com stale.
- Regenerar respecta slots manuals o demana resolucio.
- Publicacio parcial nomes obre les particions confirmades.

## Orquestracio Recomanada Per Subagents

### Regla general
- Cada subagent rep aquest document com a context principal.
- Cap subagent ha d'inventar decisions noves.
- Si una decisio no esta en aquest document, ha de reportar dubte o bloqueig.
- Els write sets s'han de mantenir disjunts sempre que sigui possible.

### Batch 1
- S1: multiples instancies locals d'aparell
- S2: model de fases
- S3: proves de compatibilitat sense fase default persistent

### Batch 2
- S4: unitats programables i slots
- S5: serveis de generacio de unitats
- S6: planner basic de fases

### Batch 3
- S7: classificacions scoped per fase
- S8: regles de pas i `QualificationRun`
- S9: confirmacio parcial per particions

### Batch 4
- S10: rotacions sobre unitats programables
- S11: scoring scoped per fase
- S12: portal de jutges home

### Batch 5
- S13: estat, stale, regeneracions
- S14: plantilles reutilitzables de fases
- S15: integracio final i suite completa

## Dubtes Oberts

### D1. Noms finals de models
- Alternatives:
  - `CompeticioAparellFase`
  - `FaseCompeticioAparell`
  - `RondaCompeticioAparell`
- Recomanacio provisional:
  - `CompeticioAparellFase`

### D2. Nom final de la unitat programable
- Alternatives:
  - `ProgramUnit`
  - `FaseUnitat`
  - `FaseProgramUnit`
- Recomanacio provisional:
  - `ProgramUnit` si es vol generalitat
  - `FaseUnitat` si es vol UI mes catalana

### D3. Rotacions
- Cal decidir si estendre `RotacioAssignacio` o crear model paral.lel.
- Recomanacio provisional:
  - model paral.lel per no fer ambigu el legacy.

### D4. Plantilles de fases
- Cal decidir si son:
  - globals per usuari
  - per competicio
  - totes dues
- Recomanacio provisional:
  - començar per plantilla per competicio i despres fer exportable/global.

### D5. Snapshot hash
- Cal definir exactament que entra al hash:
  - IDs de files classificades
  - posicions
  - scores
  - ties
  - particio
  - timestamp de calcul
- Recomanacio provisional:
  - hash semantic de files, posicio, score i particio; no timestamp.

### D6. Publicacio parcial
- Cal decidir si una `ProgramUnit` pot tenir alguns slots publicats i altres no.
- Recomanacio provisional:
  - publicar a nivell de particio/unitat completa, no slot individual.

## Criteris De Done Globals
- Una competicio pot tenir dues instancies locals del mateix aparell base.
- Cada instancia local pot tenir un arbre de fases.
- Les fases poden tenir unitats programables i slots buits.
- Les unitats es poden programar abans de coneixer participants.
- Una classificacio pot calcular sobre una fase.
- Una regla de pas pot omplir una fase desti a partir d'una classificacio font.
- Es poden confirmar particions concretes.
- Les reserves son estat suportat.
- El portal de jutges mostra nomes fases publicades i puntuables.
- Les competicions legacy continuen funcionant sense fase explicita.

## Suite De Verificacio Recomanada
- Tests de models i migracions:
  - aparells locals duplicats
  - no backfill de fase default
  - unitats i slots
- Tests de classificacions:
  - legacy
  - scoped per fase
  - fonts per regla de pas
- Tests de scoring:
  - notes separades per fase
  - videos preservats
- Tests de rotacions:
  - legacy
  - unitats programables
- Tests de jutges:
  - token legacy
  - home de fases
  - fases pendents no puntuables
- Tests d'estat:
  - confirmacio parcial
  - stale
  - regeneracio amb canvis manuals

## Notes Finals Per A Futurs Agents
- La classificacio calcula, no decideix participants de fases futures.
- La regla de pas decideix candidats, reserves i pendents.
- La fase materialitza participants en slots.
- La rotacio programa unitats, no participants solts.
- Els jutges puntuen fases publicades, no fases planificades.
- La programacio previa crea unitats i slots buits, no participants inventats.
- El sistema ha de ser general per subjectes individuals i equips.
- Qualsevol canvi que assumeixi que tot subjecte es una `Inscripcio` es massa estret.
- Qualsevol canvi que reutilitzi `GrupCompeticio` com a grup de final o semifinal probablement esta barrejant capes.

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
  - clau unica actual: `competicio + inscripcio + exercici + comp_aparell`.
  - no te dimensio de fase.
- `TeamScoreEntry`
  - equivalent per unitats competitives d'equip.
  - no te dimensio de fase.
- `GrupCompeticio`
  - representa grups globals de competicio.
  - avui s'usen per la primera organitzacio de participants.
- `RotacioEstacio` i `RotacioAssignacio`
  - programen grups o series en franges i estacions.
  - apunten a `CompeticioAparell`, no a fase.
- `ClassificacioConfig`
  - calcula resultats amb schema declaratiu.
  - avui selecciona aparells per `comp_aparell_id`.
  - no coneix fases.
- `JudgeDeviceToken`
  - avui esta lligat a un `CompeticioAparell`.
  - no coneix fases ni una home de portal.

### Limitacions actuals
- Una competicio no pot tenir dues instancies locals del mateix `Aparell`.
- Una mateixa inscripcio no pot competir dues vegades al mateix `CompeticioAparell` en fases diferents sense col.lisionar conceptualment.
- Els grups actuals no serveixen com a grups de semifinal/final, perque son globals i no estan scoped per fase.
- Les rotacions actuals poden programar un grup mes d'una vegada en franges diferents, pero aixo no crea una segona participacio competitiva.
- Les classificacions calculen resultats, pero no materialitzen participants d'una fase posterior.

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
- Per preservar compatibilitat, cada `CompeticioAparell` existent ha de poder tenir una fase implicita.
- Durant migracions, es pot crear una fase `Fase unica` per cada `CompeticioAparell`.
- Totes les notes existents es poden considerar assignades conceptualment a aquesta fase unica.

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
- Crear fase unica per defecte.
- Encara no obligar el scoring runtime a usar fase.

### Write set principal
- nou model a `models/competicio.py` o modul nou dedicat
- migracio nova
- admin basic
- serveis de creacio/assegurament de fase default
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
- Crear fase unica per cada `CompeticioAparell` existent.
- Afegir helper:
  - `ensure_default_phase_for_comp_aparell`
- Afegir propietat o helper:
  - `default_phase`

### Guardrails
- No tocar encara `ScoreEntry`.
- No tocar encara `RotacioAssignacio`.
- No tocar encara `JudgeDeviceToken`.

### Tests
- Cada `CompeticioAparell` nou crea o pot assegurar fase unica.
- Una fase no pot pertanyer a un `CompeticioAparell` d'una altra competicio.
- L'arbre no permet parent d'una altra instancia.

### Tancament Implementat
- Estat: completada.
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
  - Afegits helpers:
    - `ensure_default_phase_for_comp_aparell`
    - `get_default_phase_for_comp_aparell`
  - La fase unica per defecte usa:
    - `nom`: `Fase unica`
    - `codi`: `DEFAULT`
    - `estat`: `published`
    - `config.source_mode`: `legacy_default`
    - `config.implicit`: `true`
  - El helper de fase default es idempotent i usa `get_or_create`.
- Migracio:
  - `0060_competicioaparellfase.py`.
  - Crea la taula de fases.
  - Fa backfill d'una fase `DEFAULT / Fase unica` per cada `CompeticioAparell` existent.
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
  - helper de fase default
  - idempotencia del helper
  - fases default separades per instancia local
  - guardrail que `ScoreEntry` i `TeamScoreEntry` encara no tenen camp de fase
  - backfill de migracio `0060`
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.access.test_aparell_catalog_ownership --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - La fase default ja existeix com a estructura persistent, pero encara no filtra ni separa notes.
  - La Fase 3 pot construir `ProgramUnit` i `ProgramUnitSlot` sota `CompeticioAparellFase`.
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
  - `create_units_from_base_groups`
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
  - generacio `from_base_groups`
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
    - assegurar i mostrar la fase default
    - crear fases filles o fases paral.leles
    - crear unitats buides amb N slots
    - crear una unitat per particio manual
    - generar unitats des de `GrupCompeticio` base
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
  - el planner mostra fase default i unitats sense exposar payloads de score
  - la llista d'aparells enllaça al planner
  - es pot crear una fase filla via POST
  - es pot crear una unitat manual amb slots buits via POST
  - es pot crear una unitat de particio via POST
  - es poden generar unitats des de grups base via POST
  - la generacio des del planner no toca `ScoreEntry` ni `TeamScoreEntry`
- Verificacio executada:
  - `python -m py_compile` dels fitxers Python tocats.
  - `docker compose exec -T web python manage.py check`.
  - `docker compose exec -T web python manage.py makemigrations --check --dry-run`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.fases --verbosity 1 --keepdb`.
  - `docker compose exec -T web python manage.py test competicions_trampoli.tests.access.test_aparell_catalog_ownership --verbosity 1 --keepdb`.
- Notes per fases seguents:
  - La Fase 5 pot afegir `fase_id` o scope equivalent a classificacions.
  - La Fase 6 pot usar les unitats i slots existents per omplir fases desti des de classificacions font.
  - Les plantilles reutilitzables poden quedar com una Fase 4b o com a extensio abans de Fase 10.

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
- En fase transitoria, la fase default pot equivaler al comportament actual.
- Builder ha de mostrar:
  - aparell local
  - fase
- Permetre classificacions multiples dins una fase.

### Guardrails
- No fer que una classificacio sigui propietaria de la fase.
- No impedir classificacions globals legacy sense fase explicita.

### Tests
- Classificacio legacy continua funcionant.
- Classificacio scoped a fase default dona el mateix resultat que abans.
- Classificacio scoped a fase avancada nomes veu slots/participants/notes d'aquella fase.

## Fase 6. Regles De Pas I Ompliment De Slots

### Objectiu
- Implementar el servei que agafa una classificacio font i omple slots d'una fase desti.

### Write set principal
- serveis nous:
  - `services/fases/qualification.py`
  - `services/fases/program_units.py`
- models opcionals:
  - `QualificationRun`
  - `FasePartitionState`
- tests de qualificacio

### Tasques
- Calcular proposta de qualificats per particio.
- Aplicar:
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
  - `RotacioProgramUnitAssignacio`

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
- Preservar comportament legacy via fase default.

### Guardrails
- Migracio de dades ha de mapar scores existents a fase default.
- No perdre videos existents.
- No trencar endpoints legacy sense fase explicita.

### Tests
- Mateixa inscripcio pot tenir score a preliminar i final.
- Score legacy continua accessible via fase default.
- Panell de notes nomes mostra slots publicats.
- Slots pendents no son puntuables.

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
- Els tokens antics han de continuar sent utilitzables en fase default.

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
- S3: proves de compatibilitat i migracio de fase default

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
- Les competicions legacy continuen funcionant amb fase default.

## Suite De Verificacio Recomanada
- Tests de models i migracions:
  - aparells locals duplicats
  - fase default
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

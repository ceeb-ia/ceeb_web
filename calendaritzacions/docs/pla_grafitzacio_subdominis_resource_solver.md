# Pla de grafitzacio i particio segura del resource_solver

## 0. Objectiu

Aquest document defineix un pla executable per afegir una capa de
grafitzacio previa al motor `resource_solver`.

L'objectiu inicial no es canviar la solucio del solver, sino observar i
auditar la magnitud real del problema:

```text
quins equips estan acoblats
quines competicions queden connectades
quines pistes/franges fan de pont
quants components independents apareixen
quina mida te cada illa
quin volum estimat de candidats, variables i constraints te cada illa
```

Quan aquesta auditoria sigui fiable, la mateixa capa ha de permetre executar
CP-SAT per components connexos segurs, sense partir mes del compte.

La idea central es construir un graf d'incidencia amb nodes tipats:

```text
team
competition
resource
linkage
```

Els components connexos d'aquest graf son subdominis independents sempre que
les arestes representin totes les dependencies que poden acoblar decisions
entre equips.

## 1. Principis tancats

Aquest pla assumeix aquestes decisions:

```text
1. La primera implementacio ha de ser nomes auditable.
2. No s'ha de canviar el resultat del solver fins que els components estiguin validats.
3. El tall segur es per components connexos del graf de dependencies.
4. No es parteix una competicio si el model actual permet que els seus equips comparteixin grups.
5. Les pistes no son els unics nodes, pero poden fer de pont entre competicions.
6. El recurs base segur es Pista joc + Dia partit + Horari partit.
7. El linkage ha d'usar la mateixa clau que el constraint real: venue + linkage_group.
8. Les entitats no necessiten node propi d'entrada si tota la competicio queda connectada.
9. Els plots han de ser explicatius i llegibles, no nomes fitxers tecnics.
10. La particio ha de tenir un mode conservador per defecte.
```

## 2. No objectius de la primera fase

No s'ha d'implementar d'entrada:

```text
particio heuristica dins una competicio gran
canvis en pesos o objectiu CP-SAT
filtratge de candidats per pista, nivell o entitat
warm starts
execucio paralela real de subsolvers
canvis a l'Excel final
canvis al legacy
UI nova obligatoria
```

La primera entrega ha de servir per respondre:

```text
si faig servir aquest graf, quantes illes surten?
quines illes son grans?
quines pistes o competicions creen els acoblaments grossos?
quina reduccio potencial tindria separar components?
```

## 3. Model conceptual

### 3.1. Nodes

Cada node ha de tenir un tipus i una clau estable.

Format recomanat:

```python
GraphNode = tuple[str, str]
```

Exemples:

```text
("team", "T123")
("competition", "fields|TRA|BENJAMI|FEMENI")
("competition", "league|Lliga Benjami Femeni")
("resource", "pavello-1|Dissabte|10:00")
("linkage", "Pavello 1|grup-a")
```

També es pot usar una dataclass si calen mes camps:

```python
@dataclass(frozen=True)
class DependencyNode:
    kind: str
    key: str
    label: str = ""
```

Per l'MVP, una tupla simple es suficient.

### 3.2. Arestes

Una aresta significa:

```text
aquest equip i aquest ambit de restriccio han d'estar al mateix subproblema
```

Arestes inicials:

```text
team -- competition
team -- resource
team -- linkage
```

Concretament:

```python
union(("team", team.team_id), ("competition", competition_key(team)))
union(("team", team.team_id), ("resource", base_resource_id_for_team(team)))

if team.linkage_group:
    union(("team", team.team_id), ("linkage", linkage_key(team)))
```

No cal assignar pesos a les arestes en la primera fase. El graf nomes decideix
connectivitat.

### 3.3. Per que nodes tipats

Es podria fer un graf nomes d'equips i afegir arestes directes:

```text
equip A -- equip B si comparteixen competicio
equip A -- equip B si comparteixen recurs
```

Pero els nodes tipats tenen avantatges importants:

```text
1. Permeten explicar per que dos equips estan connectats.
2. Permeten llistar quines pistes fan de pont.
3. Permeten comptar competicions i recursos per component.
4. Eviten crear arestes quadratiques entre tots els equips d'una mateixa pista.
5. Fan mes facil generar plots interpretables.
```

## 4. Relacio amb el model actual

El context actual es construeix a:

```text
calendaritzacions/engine/variants/resource_solver/input_adapter.py
```

Ara mateix:

```text
1. Es construeixen TeamRecord.
2. S'aplica linkage segons config.
3. Es construeixen recursos base.
4. Es calcula capacitat i pressio.
5. Es creen grups i candidats per competicio.
6. Es passa tot el SolverContext al model CP-SAT.
```

La grafitzacio ha d'entrar despres de construir `SolverContext`.

Flux d'observabilitat:

```text
input_df
  -> build_context_from_dataframe(...)
  -> build_dependency_graph(context)
  -> build_component_summary(...)
  -> write_decomposition_audits(...)
  -> solver global actual
```

Flux futur de particio:

```text
input_df
  -> build_context_from_dataframe(...)
  -> split_context_by_safe_components(context)
  -> solve each subcontext
  -> merge raw results
  -> build_solution on global context
```

## 5. Claus de dependencia

### 5.1. Competition key

La clau de competicio ha de coincidir exactament amb la logica actual de
`input_adapter._competition_key`.

Regla:

```text
si Modalitat, Categoria i Subcategoria existeixen:
    fields|modalitat|categoria|subcategoria
si no:
    league|Nom Lliga o Sense lliga
```

Treball recomanat:

```text
extreure `_competition_key` a funcio publica
evitar duplicar la logica al modul de grafitzacio
```

Nom proposat:

```python
competition_key_for_team(team: TeamRecord) -> tuple[str, ...]
competition_node_key(team: TeamRecord) -> str
```

### 5.2. Resource key

La clau de recurs segura ha de ser el recurs base:

```text
Pista joc + Dia partit + Horari partit
```

No s'ha d'afegir `round_index` al node de graf inicial.

Motiu:

```text
el consum per ronda depen del numero final assignat
tots els equips poden ser candidats a tots els numeros 1..8
dos equips que comparteixen recurs base poden coincidir en consum en alguna ronda
```

Funcions existents a reutilitzar:

```text
base_resource_id_for_team(team)
build_base_resource_id(venue, day, hour_slot)
```

### 5.3. Linkage key

El constraint actual agrupa linkage per:

```text
venue + linkage_group
```

Per tant, el graf ha d'usar la mateixa clau.

No incloure dia/hora en linkage tret que el constraint canviï.

### 5.4. Entity key

No cal node d'entitat en la primera versio.

Motiu:

```text
entity_separation nomes actua dins els grups d'una competicio
com que team -- competition connecta tota la competicio, l'entitat ja queda dins el component
```

Es pot afegir mes endavant com a node auditable si ajuda a explicar conflictes,
pero no ha de canviar components.

## 6. Arquitectura proposada

Fitxers nous:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/reporting/resource_solver_decomposition_plots.py
calendaritzacions/tests/test_resource_solver_decomposition.py
calendaritzacions/tests/test_resource_solver_decomposition_plots.py
```

Fitxers a tocar amb molta cura:

```text
calendaritzacions/engine/variants/resource_solver/input_adapter.py
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/engine/variants/resource_solver/audit.py
calendaritzacions/engine/variants/resource_solver/types.py
```

Possible extensio futura:

```text
calendaritzacions/engine/variants/resource_solver/component_solver.py
calendaritzacions/tests/test_resource_solver_component_solver.py
```

## 7. Contractes de dades

### 7.1. DependencyEdge

```python
@dataclass(frozen=True)
class DependencyEdge:
    left_kind: str
    left_key: str
    right_kind: str
    right_key: str
    reason: str
```

`reason` ha de ser un d'aquests valors inicials:

```text
competition_membership
resource_capacity
linkage_group
```

### 7.2. DependencyComponent

```python
@dataclass(frozen=True)
class DependencyComponent:
    component_id: str
    nodes: tuple[DependencyNode, ...]
    edges: tuple[DependencyEdge, ...]
    team_ids: tuple[str, ...]
    competition_keys: tuple[str, ...]
    resource_ids: tuple[str, ...]
    linkage_keys: tuple[str, ...]
```

Per simplicitat es pot construir sense guardar totes les arestes en memoria si
el volum es gran, pero l'auditoria ha de poder explicar counts per reason.

### 7.3. DecompositionSummary

```python
@dataclass(frozen=True)
class DecompositionSummary:
    components: tuple[DependencyComponent, ...]
    total_teams: int
    total_competitions: int
    total_resources: int
    total_linkages: int
    total_edges: int
    component_count: int
    largest_component_team_count: int
    safe_to_split: bool
```

La primera versio pot ser JSON-ready amb dicts si no es vol tocar `types.py`.

## 8. Algorisme

### 8.1. Union-Find

Usar Union-Find / Disjoint Set.

No cal `networkx` per detectar components.

Pseudoimplementacio:

```python
class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, node):
        self.parent.setdefault(node, node)
        if self.parent[node] != node:
            self.parent[node] = self.find(self.parent[node])
        return self.parent[node]

    def union(self, left, right):
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left
```

### 8.2. Construccio del graf

```python
def build_dependency_graph(context: SolverContext) -> DependencyGraph:
    dsu = UnionFind()
    edges = []

    for team in context.teams:
        team_node = ("team", team.team_id)

        competition_node = ("competition", competition_node_key(team))
        dsu.union(team_node, competition_node)
        edges.append(edge(team_node, competition_node, "competition_membership"))

        resource_node = ("resource", base_resource_id_for_team(team))
        dsu.union(team_node, resource_node)
        edges.append(edge(team_node, resource_node, "resource_capacity"))

        linkage_group = normalized_linkage_group(team.linkage_group)
        if linkage_group:
            linkage_node = ("linkage", linkage_node_key(team.venue, linkage_group))
            dsu.union(team_node, linkage_node)
            edges.append(edge(team_node, linkage_node, "linkage_group"))

    return materialize_components(dsu, edges)
```

### 8.3. Materialitzacio de components

Per cada root:

```text
llistar nodes
llistar team_ids
llistar competition_keys
llistar resource_ids
llistar linkage_keys
comptar arestes per reason
calcular candidats dins component
calcular grups dins component
calcular pressio maxima dins component
```

### 8.4. Split segur de SolverContext

No activar per defecte en la primera fase.

Quan s'activi:

```python
def split_context_by_components(context, components):
    for component in components:
        yield filter_context(context, component.team_ids)
```

`filter_context` ha de conservar:

```text
teams del component
candidates dels teams del component
groups referenciats pels candidates
base_resources usats pels teams del component
capacities dels recursos del component
pressure dels recursos del component
phase i phase_name globals
config
```

Validacio obligatoria:

```text
cap candidate apunta a un team fora del component
cap group seleccionat queda compartit entre components
cap resource del component conte teams de fora
cap linkage del component conte teams de fora
```

Si alguna validacio falla, la particio ha de quedar desactivada i el run ha de
seguir amb el solver global.

## 9. Auditoria JSON

### 9.1. Fitxers nous d'auditoria

Generar:

```text
dependency_components.json
dependency_component_edges.json
dependency_component_summary.json
```

Opcionalment, si els fitxers serien massa grans:

```text
dependency_component_edges_sample.json
```

### 9.2. dependency_component_summary.json

Contingut:

```json
{
  "component_count": 12,
  "total_teams": 1800,
  "total_competitions": 130,
  "total_resources": 240,
  "total_linkages": 80,
  "largest_component": {
    "component_id": "C001",
    "teams": 620,
    "competitions": 42,
    "resources": 75,
    "linkages": 21,
    "candidates": 39760
  },
  "components_by_size": [
    {
      "component_id": "C001",
      "teams": 620,
      "competitions": 42,
      "resources": 75,
      "linkages": 21,
      "candidate_count": 39760,
      "group_count": 78,
      "max_resource_pressure": 3.4,
      "edge_counts": {
        "competition_membership": 620,
        "resource_capacity": 620,
        "linkage_group": 84
      }
    }
  ]
}
```

### 9.3. dependency_components.json

Per component:

```text
component_id
team_count
competition_count
resource_count
linkage_count
group_count
candidate_count
estimated_x_variables
estimated_real_home_variables
estimated_soft_resource_terms
max_resource_pressure
top_competitions
top_resources
top_linkages
```

No cal incloure tots els equips si el component es molt gran. Es pot incloure:

```text
team_ids_sample
team_ids_count
```

### 9.4. dependency_component_edges.json

Per auditoria detallada:

```text
left_kind
left_key
right_kind
right_key
reason
component_id
```

Si el fitxer es massa gran, limitar o comprimir:

```text
guardar counts globals
guardar mostra determinista de N arestes per component
```

## 10. Plots requerits

Els plots han de respondre preguntes operatives, no nomes visuals.

### 10.1. Histograma de mida de components

Fitxer:

```text
plots_decomposition/component_team_count_histogram.png
```

Mostra:

```text
x = rangs de nombre d'equips
y = nombre de components
```

Objectiu:

```text
veure si hi ha moltes illes petites o un component gegant
```

### 10.2. Barres dels components mes grans

Fitxer:

```text
plots_decomposition/top_components_by_teams.png
```

Mostra per cada component gran:

```text
equips
competicions
recursos
linkages
candidats estimats
```

Objectiu:

```text
identificar on es concentra el problema
```

### 10.3. Scatter recursos vs competicions

Fitxer:

```text
plots_decomposition/components_resources_vs_competitions.png
```

Eixos:

```text
x = resource_count
y = competition_count
size = team_count
color = candidate_count o max_resource_pressure
```

Objectiu:

```text
veure si els components grossos venen per moltes pistes, moltes competicions o totes dues
```

### 10.4. Pareto de candidats per component

Fitxer:

```text
plots_decomposition/candidate_pareto_by_component.png
```

Mostra:

```text
barres ordenades per candidate_count
linia acumulada percentual
```

Objectiu:

```text
veure si el 80% del model esta concentrat en pocs components
```

### 10.5. Xarxa reduida dels components principals

Fitxer:

```text
plots_decomposition/top_component_network_C001.png
```

Per components grans, generar una xarxa simplificada:

```text
nodes competition
nodes resource
aresta competition-resource si hi ha equips que connecten aquella competicio amb aquell recurs
gruix = nombre d'equips
```

No representar cada equip si el component es gran.

Objectiu:

```text
entendre quines pistes fan de pont entre competicions
```

### 10.6. Heatmap competicio-recurs per component

Fitxer:

```text
plots_decomposition/top_component_competition_resource_heatmap_C001.png
```

Files:

```text
top competicions del component
```

Columnes:

```text
top recursos del component
```

Valor:

```text
nombre d'equips d'aquella competicio que demanen aquell recurs
```

Objectiu:

```text
veure visualment els ponts reals
```

## 11. Reporting dins logs

Afegir linies de log curtes:

```text
decomposition: components=12 teams=1800 competitions=130 resources=240
decomposition: largest=C001 teams=620 competitions=42 resources=75 candidates=39760
decomposition: split_potential global_candidates=120000 largest_component_candidates=39760
decomposition: plots generated=6
```

Si en el futur s'activa particio:

```text
decomposition: safe split enabled components=12
decomposition: solving component C001 teams=620 candidates=39760
decomposition: solving component C002 teams=310 candidates=12400
decomposition: merged assignments=1800
```

## 12. Integracio amb service.py

### 12.1. Fase observabilitat

Al servei:

```python
context = build_context_from_dataframe(input_df, config=config)
decomposition = build_decomposition_summary(context)
audit_payloads["dependency_components"] = ...
audit_payloads["dependency_component_summary"] = ...
write_decomposition_plots(...)
built_model = build_solver_model(context)
raw_result = solve_model(built_model, config)
```

La solucio continua global.

### 12.2. Fase split experimental

Afegir config explicit:

```python
decomposition_mode: str = "audit_only"
```

Valors:

```text
off
audit_only
solve_components
```

Per defecte:

```text
audit_only
```

`solve_components` nomes s'ha d'activar quan els tests i l'auditoria estiguin
validats.

## 13. Validacions de seguretat

Abans de resoldre components per separat:

```text
1. Tots els teams del context apareixen en exactament un component.
2. Tots els candidates tenen team_id dins un component.
3. Cap group_id apareix en dos components.
4. Cap resource_id apareix en dos components.
5. Cap linkage_key apareix en dos components.
6. La suma de target_size dels grups dels subcontexts coincideix amb el nombre d'equips.
7. La suma de candidates dels subcontexts coincideix amb candidates globals.
8. El solver global i el solver per components tenen el mateix conjunt de teams assignats en fixtures petites.
```

Si qualsevol validacio falla:

```text
desactivar split
log warning
executar solver global
guardar auditoria de per que no s'ha separat
```

## 14. Estrategia de tests

### 14.1. Tests purs de graf

Fixtures petites:

```text
dues competicions sense recursos compartits -> 2 components
dues competicions amb una pista/franja compartida -> 1 component
una competicio amb moltes pistes -> 1 component
linkage entre equips de competicions diferents i mateixa venue -> 1 component
linkage buit -> no crea aresta
```

### 14.2. Tests de claus

Verificar:

```text
competition_key coincideix amb input_adapter
resource_key usa base_resource_id_for_team
linkage_key usa venue + normalized linkage_group
```

### 14.3. Tests de subcontext

Verificar:

```text
filter_context conserva teams correctes
filter_context conserva groups correctes
filter_context conserva capacities correctes
filter_context no deixa candidates orfes
```

### 14.4. Tests de plots

No cal comparar imatges pixel a pixel.

Verificar:

```text
els fitxers existeixen
tenen mida > 0
el manifest JSON referencia els plots generats
funciona amb 1 component
funciona amb molts components
funciona amb component gegant sense dibuixar tots els equips
```

### 14.5. Tests d'integracio

Amb `ResourceSolverEngine`:

```text
run genera dependency_component_summary
run genera dependency_components
run no canvia output_path ni status esperat
logs inclouen linies decomposition
```

## 15. Pla per subagents

### Agent G-01: contractes i Union-Find

Objectiu:

```text
crear el modul base de decomposition i detectar components connexos
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/tests/test_resource_solver_decomposition.py
```

Tasques:

```text
implementar UnionFind
implementar node helpers
implementar build_dependency_graph(context)
implementar build_dependency_components(context)
tests de components simples
```

Criteris d'acceptacio:

```text
no importa matplotlib
no toca service.py
no executa CP-SAT
tests purs passen sense OR-Tools
```

### Agent G-02: claus publiques i compatibilitat amb input_adapter

Objectiu:

```text
evitar duplicacio de competition_key i assegurar coherencia amb el context actual
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/input_adapter.py
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/tests/test_resource_solver_decomposition.py
```

Tasques:

```text
extreure helper public per competition_key
actualitzar decomposition per usar-lo
tests amb Modalitat/Categoria/Subcategoria
tests fallback Nom Lliga
```

Criteris d'acceptacio:

```text
la logica existent de build_context_from_dataframe no canvia
els group_prefix continuen igual
cap canvi funcional al solver
```

### Agent G-03: auditoria JSON

Objectiu:

```text
convertir components a payloads JSON-ready
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/engine/variants/resource_solver/audit.py
calendaritzacions/tests/test_resource_solver_decomposition.py
calendaritzacions/tests/test_resource_solver_audit.py
```

Tasques:

```text
build_dependency_component_summary_payload
build_dependency_components_payload
build_dependency_edges_payload o sample
calcular counts per component
calcular candidate_count i group_count per component
```

Criteris d'acceptacio:

```text
payload JSON serialitzable
no inclou objectes CP-SAT
no fa plots
```

### Agent G-04: plots de magnitud

Objectiu:

```text
generar plots explicatius dels components
```

Write-set:

```text
calendaritzacions/reporting/resource_solver_decomposition_plots.py
calendaritzacions/tests/test_resource_solver_decomposition_plots.py
```

Tasques:

```text
histograma de teams per component
top components per teams/candidates
scatter resources vs competitions
pareto de candidates
manifest JSON de plots
```

Criteris d'acceptacio:

```text
plots es generen en directori temporal
funciona sense networkx
si matplotlib no esta disponible, error controlat o skip explicit en tests
```

### Agent G-05: xarxa reduida i heatmaps

Objectiu:

```text
generar visualitzacions interpretables dels components grans
```

Write-set:

```text
calendaritzacions/reporting/resource_solver_decomposition_plots.py
calendaritzacions/tests/test_resource_solver_decomposition_plots.py
```

Tasques:

```text
construir matriu competition-resource
plot heatmap per top components
plot network reduit competition-resource
limitar top N per no fer imatges illegibles
```

Criteris d'acceptacio:

```text
no dibuixa nodes team en components grans
plots tenen titols i etiquetes llegibles
no peta amb noms llargs
```

### Agent G-06: integracio audit_only al service

Objectiu:

```text
connectar grafitzacio al run sense canviar el solver
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/engine/variants/resource_solver/audit.py
calendaritzacions/tests/test_resource_solver_service.py
```

Tasques:

```text
executar decomposition despres de build_context_from_dataframe
afegir payloads a audit_payloads
cridar write_resource_solver_decomposition_plots
afegir logs de resum
guardar manifest de plots a audit_paths
```

Criteris d'acceptacio:

```text
run existent continua generant Excel
status solver no canvia
audit_paths inclouen decomposition
si plots fallen, el run continua i queda log warning
```

### Agent G-07: split experimental de contextos

Objectiu:

```text
preparar el cami per resoldre components, sense activar-lo per defecte
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/decomposition.py
calendaritzacions/tests/test_resource_solver_decomposition.py
```

Tasques:

```text
implementar filter_context_by_team_ids
implementar split_context_by_components
implementar validate_component_split
tests de subcontexts
```

Criteris d'acceptacio:

```text
no toca model.py
no toca service.py tret que G-06 ja hagi acabat i hi hagi acord
split no s'activa per defecte
```

### Agent G-08: component solving i merge, fase posterior

Objectiu:

```text
executar solver per components i fusionar resultats
```

Write-set:

```text
calendaritzacions/engine/variants/resource_solver/component_solver.py
calendaritzacions/engine/variants/resource_solver/service.py
calendaritzacions/tests/test_resource_solver_component_solver.py
```

Tasques:

```text
solve_context_components
merge RawSolverResult
preservar status global
sumar objective_value si tots els components tenen objectiu
conservar variable_values per candidate_id
```

Criteris d'acceptacio:

```text
mode per defecte continua audit_only
fixtures petites donen mateix conjunt d'assignments que solver global quan no hi ha empats rellevants
si un component INFEASIBLE, status global INFEASIBLE
si algun component UNKNOWN, status global UNKNOWN excepte si hi ha INFEASIBLE
```

## 16. Ordre recomanat

Ordre amb paralelisme:

```text
G-01 primer
G-02 en paralel amb G-03 quan G-01 tingui esquelet
G-04 i G-05 en paralel un cop G-03 defineixi payloads
G-06 despres de G-03 i G-04
G-07 pot anar en paralel amb G-04/G-05
G-08 nomes despres de validar audit_only amb dades reals
```

Ordre lineal si una sola persona ho fa:

```text
1. decomposition.py amb Union-Find
2. competition_key public
3. payloads JSON
4. plots basics
5. integracio audit_only
6. plots avancats
7. split_context experimental
8. solver per components
```

## 17. Riscos i mitigacions

### 17.1. Component gegant unic

Risc:

```text
totes les competicions queden connectades per recursos compartits
```

Mitigacio:

```text
els plots identificaran quins recursos fan de pont
no forcar split heuristics en aquesta fase
usar l'auditoria per decidir una segona estrategia
```

### 17.2. Graf massa gran per plot

Risc:

```text
representar tots els equips fa imatges inutilitzables
```

Mitigacio:

```text
plots agregats per competition-resource
top N components
top N resources/competitions dins component
samples deterministes
```

### 17.3. Claus divergents del solver

Risc:

```text
el graf diu que dos dominis estan separats pero el solver els acobla per una clau diferent
```

Mitigacio:

```text
reutilitzar helpers existents
tests de coherencia
validacions abans de split
mode audit_only per defecte
```

### 17.4. Merge de resultats incorrecte

Risc:

```text
resoldre components genera RawSolverResult dificil de combinar
```

Mitigacio:

```text
posposar component_solver
primer implementar split_context i validacions
despres fer merge en fixtures petites
```

## 18. Definicio de fet de la fase audit_only

Es considera completada la fase inicial quan:

```text
1. Cada run resource_solver genera dependency_component_summary.json.
2. Cada run genera dependency_components.json.
3. Els logs informen component_count i largest component.
4. Es generen plots basics de magnitud.
5. El solver continua executant-se globalment.
6. Els tests purs de decomposition passen.
7. Els tests de service verifiquen que l'auditoria existeix.
8. Si els plots fallen, el run no falla.
9. No hi ha canvis al legacy.
10. No hi ha canvis funcionals en assignacions CP-SAT.
```

## 19. Definicio de fet de la fase solve_components

Es considera completada la particio segura quan:

```text
1. split_context_by_components passa totes les validacions.
2. El mode solve_components es explicit i no default.
3. Fixtures petites tenen el mateix nombre d'assignacions que el global.
4. Cap group/resource/linkage queda repartit entre components.
5. Status global es combina correctament.
6. Audit indica quins components s'han resolt i quant han trigat.
7. Si hi ha qualsevol dubte de seguretat, es torna al solver global.
```


"""Constraint builders for the resource solver."""

from calendaritzacions.engine.variants.resource_solver.constraints.assignment import (
    AssignmentConstraints,
    add_assignment_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ConstraintBuilder,
    ModelVariables,
    ObjectiveTerm,
)
from calendaritzacions.engine.variants.resource_solver.constraints.empty_numbers import (
    EmptyNumberConstraints,
    add_empty_number_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.entity_separation import (
    EntitySeparationConstraints,
    add_entity_separation_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.group_size import (
    GroupSizeConstraints,
    add_group_size_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.linkage import (
    LinkageConstraints,
    add_linkage_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.level_band import (
    LevelBandConstraints,
    add_level_band_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.resource_capacity import (
    ResourceCapacityConstraints,
    add_resource_capacity_constraints,
    candidate_resource_by_round,
)

DEFAULT_CONSTRAINT_BUILDERS = (
    AssignmentConstraints(),
    GroupSizeConstraints(),
    EmptyNumberConstraints(),
    EntitySeparationConstraints(),
    ResourceCapacityConstraints(),
    LinkageConstraints(),
    LevelBandConstraints(),
)

__all__ = [
    "AssignmentConstraints",
    "ConstraintAudit",
    "ConstraintBuilder",
    "DEFAULT_CONSTRAINT_BUILDERS",
    "EmptyNumberConstraints",
    "EntitySeparationConstraints",
    "GroupSizeConstraints",
    "LevelBandConstraints",
    "LinkageConstraints",
    "ModelVariables",
    "ObjectiveTerm",
    "ResourceCapacityConstraints",
    "add_assignment_constraints",
    "add_empty_number_constraints",
    "add_entity_separation_constraints",
    "add_group_size_constraints",
    "add_level_band_constraints",
    "add_linkage_constraints",
    "add_resource_capacity_constraints",
    "candidate_resource_by_round",
]

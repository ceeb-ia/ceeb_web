from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from unittest import TestCase

from designacions.optimization.route_points import (
    AtomicRoutePoint,
    required_gap,
    route_points_from_segments,
    same_location,
    transition_requires_vehicle,
    validate_atomic_gaps,
)


@dataclass(frozen=True)
class Segment:
    id: str
    match_ids: list[str]
    rows: list[object]
    venues: list[str]
    cluster_ids: list[str | None]
    cluster_statuses: list[str | None]
    start_dt: datetime
    end_dt: datetime


class GettableRow:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class RoutePointsTests(TestCase):
    def test_route_points_expand_rows_in_chronological_order(self):
        segment = Segment(
            id="seg-a",
            match_ids=["m1", "m2"],
            rows=[
                {"Pista joc": "SAFA", "__match_datetime": datetime(2026, 5, 2, 20, 0), "cluster": None, "cluster_status": "outlier"},
                {"Pista joc": "Maristes", "__match_datetime": datetime(2026, 5, 2, 18, 0), "cluster": "43", "cluster_status": "ok"},
            ],
            venues=["Maristes", "SAFA"],
            cluster_ids=["43", None],
            cluster_statuses=["ok", "outlier"],
            start_dt=datetime(2026, 5, 2, 18, 0),
            end_dt=datetime(2026, 5, 2, 20, 0),
        )

        points = route_points_from_segments([segment])

        self.assertEqual([point.venue for point in points], ["Maristes", "SAFA"])
        self.assertEqual([point.match_id for point in points], ["m2", "m1"])
        self.assertTrue(all(not point.source_is_aggregate for point in points))

    def test_aggregate_maristes_safa_then_maristes_uses_real_last_atomic_transition(self):
        first = {
            "id": "first",
            "match_ids": ["m1", "m2"],
            "rows": [
                {"match_id": "m1", "Pista joc": "Maristes", "__match_datetime": datetime(2026, 5, 2, 18, 0), "cluster": "43"},
                {"match_id": "m2", "Pista joc": "SAFA", "__match_datetime": datetime(2026, 5, 2, 20, 0), "cluster": None, "cluster_status": "outlier"},
            ],
            "venues": ["Maristes", "SAFA"],
            "cluster_ids": ["43", None],
            "cluster_statuses": ["ok", "outlier"],
        }
        second = {
            "id": "second",
            "match_ids": ["m3"],
            "rows": [
                GettableRow(match_id="m3", **{"Pista joc": "Maristes", "__match_datetime": datetime(2026, 5, 2, 21, 0), "cluster": "43"})
            ],
            "venues": ["Maristes"],
            "cluster_ids": ["43"],
            "cluster_statuses": ["ok"],
        }

        points = route_points_from_segments([first, second])
        self.assertEqual([point.match_id for point in points], ["m1", "m2", "m3"])
        self.assertFalse(same_location(points[1], points[2]))
        self.assertTrue(transition_requires_vehicle(points[1], points[2]))
        self.assertEqual(required_gap(points[1], points[2], {"gap_diff_cluster_min": 100}), 100)

        warnings, blocked = validate_atomic_gaps(
            [first, second],
            {"gap_same_pitch_min": 60, "gap_diff_pitch_min": 75, "gap_diff_cluster_min": 100, "has_vehicle": True},
        )

        self.assertTrue(blocked)
        self.assertIn("gap_too_short", warnings)
        self.assertIn("cross_cluster_with_vehicle_warning", warnings)

    def test_uncertain_same_location_uses_same_pitch_gap_with_warning(self):
        points = [
            AtomicRoutePoint("m1", datetime(2026, 5, 2, 18, 0), datetime(2026, 5, 2, 18, 0), "SAFA", cluster_status="outlier"),
            AtomicRoutePoint("m2", datetime(2026, 5, 2, 19, 0), datetime(2026, 5, 2, 19, 0), "SAFA", cluster_status="outlier"),
        ]

        warnings, blocked = validate_atomic_gaps(
            points,
            {"gap_same_pitch_min": 60, "gap_diff_cluster_min": 100, "has_vehicle": False},
        )

        self.assertFalse(blocked)
        self.assertIn("outlier_mobility_warning", warnings)
        self.assertNotIn("vehicle_required", warnings)

    def test_uncertain_different_location_blocks_without_vehicle_even_when_gap_is_enough(self):
        points = [
            AtomicRoutePoint("m1", datetime(2026, 5, 2, 18, 0), datetime(2026, 5, 2, 18, 0), "SAFA", cluster_status="outlier"),
            AtomicRoutePoint("m2", datetime(2026, 5, 2, 20, 0), datetime(2026, 5, 2, 20, 0), "Maristes", cluster_id="43"),
        ]

        warnings, blocked = validate_atomic_gaps(
            points,
            {"gap_diff_cluster_min": 100, "transport": "Transport public"},
        )

        self.assertTrue(blocked)
        self.assertIn("vehicle_required", warnings)

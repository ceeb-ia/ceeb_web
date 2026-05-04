from __future__ import annotations

from unittest import TestCase

from designacions.services.assignment_feasibility import (
    build_match_descriptor,
    inspect_mobility_transitions,
    mobility_reason_codes,
)


class AssignmentFeasibilityAtomicMobilityTests(TestCase):
    def test_outlier_between_same_venue_validates_real_last_atomic_transition(self):
        descriptors = [
            build_match_descriptor(
                identifier="A1",
                date_value="2026-05-02",
                time_value="18:00",
                venue="Maristes Sant Joan",
                modality="F5",
                cluster_id="43",
                address_id=43,
                cluster_status="clustered",
            ),
            build_match_descriptor(
                identifier="B1",
                date_value="2026-05-02",
                time_value="20:00",
                venue="SAFA Sant Andreu",
                modality="F5",
                cluster_id=None,
                address_id=99,
                cluster_status="outlier",
            ),
            build_match_descriptor(
                identifier="A2",
                date_value="2026-05-02",
                time_value="21:00",
                venue="Maristes Sant Joan",
                modality="F5",
                cluster_id="43",
                address_id=43,
                cluster_status="clustered",
            ),
        ]

        issues = inspect_mobility_transitions(
            descriptors,
            transport="Moto",
            gap_same_pitch_min=60,
            gap_diff_pitch_min=75,
            gap_diff_cluster_min=100,
        )

        self.assertEqual([issue.left_identifier for issue in issues], ["A1", "B1"])
        self.assertEqual([issue.right_identifier for issue in issues], ["B1", "A2"])
        self.assertEqual(issues[1].reason_code, "outlier_cluster_for_mobility_validation")
        self.assertEqual(issues[1].required_gap_min, 100)
        self.assertEqual(issues[1].actual_gap_min, 60)
        self.assertFalse(issues[1].same_pitch)

        self.assertEqual(
            mobility_reason_codes(
                descriptors,
                transport="Moto",
                gap_same_pitch_min=60,
                gap_diff_pitch_min=75,
                gap_diff_cluster_min=100,
            ),
            ["outlier_cluster_for_mobility_validation"],
        )

    def test_outlier_different_location_with_vehicle_and_enough_gap_warns(self):
        descriptors = [
            build_match_descriptor(
                identifier="B1",
                date_value="2026-05-02",
                time_value="20:00",
                venue="SAFA Sant Andreu",
                modality="F5",
                cluster_id=None,
                address_id=99,
                cluster_status="outlier",
            ),
            build_match_descriptor(
                identifier="A2",
                date_value="2026-05-02",
                time_value="21:45",
                venue="Maristes Sant Joan",
                modality="F5",
                cluster_id="43",
                address_id=43,
                cluster_status="clustered",
            ),
        ]

        issues = inspect_mobility_transitions(
            descriptors,
            transport="Moto",
            gap_same_pitch_min=60,
            gap_diff_pitch_min=75,
            gap_diff_cluster_min=100,
        )

        self.assertEqual([issue.reason_code for issue in issues], ["outlier_mobility_warning"])
        self.assertTrue(issues[0].is_advisory)

    def test_uncertain_different_location_without_vehicle_blocks_even_with_enough_gap(self):
        descriptors = [
            build_match_descriptor(
                identifier="B1",
                date_value="2026-05-02",
                time_value="20:00",
                venue="SAFA Sant Andreu",
                modality="F5",
                cluster_id=None,
                address_id=99,
                cluster_status="missing_geocode",
            ),
            build_match_descriptor(
                identifier="A2",
                date_value="2026-05-02",
                time_value="22:00",
                venue="Maristes Sant Joan",
                modality="F5",
                cluster_id="43",
                address_id=43,
                cluster_status="clustered",
            ),
        ]

        issues = inspect_mobility_transitions(
            descriptors,
            transport="Bus",
            gap_same_pitch_min=60,
            gap_diff_pitch_min=75,
            gap_diff_cluster_min=100,
        )

        self.assertEqual([issue.reason_code for issue in issues], ["missing_cluster_for_mobility_validation"])
        self.assertTrue(issues[0].is_blocking)

    def test_outlier_same_location_uses_same_pitch_gap_with_warning(self):
        descriptors = [
            build_match_descriptor(
                identifier="B1",
                date_value="2026-05-02",
                time_value="20:00",
                venue="SAFA Sant Andreu",
                modality="F5",
                cluster_id=None,
                address_id=99,
                cluster_status="outlier",
            ),
            build_match_descriptor(
                identifier="B2",
                date_value="2026-05-02",
                time_value="21:00",
                venue="SAFA Sant Andreu",
                modality="F5",
                cluster_id=None,
                address_id=99,
                cluster_status="outlier",
            ),
        ]

        issues = inspect_mobility_transitions(
            descriptors,
            transport="Bus",
            gap_same_pitch_min=60,
            gap_diff_pitch_min=75,
            gap_diff_cluster_min=100,
        )

        self.assertEqual([issue.reason_code for issue in issues], ["outlier_mobility_warning"])
        self.assertEqual(issues[0].required_gap_min, 60)
        self.assertTrue(issues[0].same_pitch)
        self.assertTrue(issues[0].is_advisory)

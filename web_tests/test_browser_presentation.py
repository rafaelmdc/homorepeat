from unittest import TestCase

from apps.browser.presentation import (
    format_protein_position,
    format_repeat_pattern,
    summarize_target_codon_usage,
)


class BrowserPresentationTests(TestCase):
    def test_format_repeat_pattern_compacts_pure_repeat(self):
        self.assertEqual(format_repeat_pattern("Q" * 42), "42Q")

    def test_format_repeat_pattern_compacts_interrupted_repeats(self):
        self.assertEqual(format_repeat_pattern("Q" * 18 + "A" + "Q" * 12), "18Q1A12Q")
        self.assertEqual(format_repeat_pattern("A" * 10 + "G" + "A" * 9), "10A1G9A")
        self.assertEqual(
            format_repeat_pattern("P" * 7 + "A" + "P" * 8 + "S" + "P" * 5),
            "7P1A8P1S5P",
        )

    def test_format_repeat_pattern_handles_empty_sequence(self):
        self.assertEqual(format_repeat_pattern(""), "")
        self.assertEqual(format_repeat_pattern(None), "")

    def test_format_protein_position_includes_midpoint_percent(self):
        self.assertEqual(format_protein_position(10, 20, 300), "10-20 (5%)")

    def test_format_protein_position_falls_back_to_coordinates_without_length(self):
        self.assertEqual(format_protein_position(10, 20, 0), "10-20")
        self.assertEqual(format_protein_position(10, 20, None), "10-20")

    def test_format_protein_position_handles_missing_coordinates(self):
        self.assertEqual(format_protein_position(None, 20, 300), "")
        self.assertEqual(format_protein_position(10, None, 300), "")

    def test_summarize_target_codon_usage_uses_target_residue_counts(self):
        summary = summarize_target_codon_usage(
            [
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 20},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 10},
                {"amino_acid": "A", "codon": "GCT", "codon_count": 1},
            ],
            "Q",
            30,
        )

        self.assertEqual(summary["coverage"], "30/30")
        self.assertEqual(summary["profile"], "CAG 67%, CAA 33%")
        self.assertEqual(summary["counts"], "CAG 20 / CAA 10")
        self.assertEqual(summary["dominant_codon"], "CAG")
        self.assertEqual(summary["parseable_counts"], "CAG=20;CAA=10")
        self.assertEqual(summary["parseable_fractions"], "CAG=0.667;CAA=0.333")

    def test_summarize_target_codon_usage_breaks_ties_by_codon(self):
        summary = summarize_target_codon_usage(
            [
                {"amino_acid": "Q", "codon": "CAG", "codon_count": 5},
                {"amino_acid": "Q", "codon": "CAA", "codon_count": 5},
            ],
            "Q",
            10,
        )

        self.assertEqual(summary["dominant_codon"], "CAA")
        self.assertEqual(summary["profile"], "CAA 50%, CAG 50%")

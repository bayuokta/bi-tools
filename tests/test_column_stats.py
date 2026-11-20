"""Uji ukuran kolom dari DMV VertiPaq (tanpa koneksi .NET)."""

from __future__ import annotations

import unittest

from core.column_stats import (
    aggregate_segments,
    attribute_id,
    column_cardinality,
    is_artifact,
    storage_key,
    table_rows,
)


class StorageKeyTests(unittest.TestCase):
    def test_name_with_id(self) -> None:
        self.assertEqual(storage_key("Dealer Code New (16930)"), ("Dealer Code New", 16930))

    def test_plain_integer(self) -> None:
        self.assertEqual(storage_key(16930), ("", 16930))

    def test_artifact_and_empty(self) -> None:
        self.assertEqual(storage_key("POS_TO_ID"), ("POS_TO_ID", None))
        self.assertEqual(storage_key(None), ("", None))
        self.assertEqual(storage_key(""), ("", None))

    def test_is_artifact(self) -> None:
        self.assertTrue(is_artifact("POS_TO_ID"))
        self.assertTrue(is_artifact("id_to_pos"))
        self.assertFalse(is_artifact("Dealer Code New (16930)"))

    def test_attribute_id_from_hierarchy_table(self) -> None:
        self.assertEqual(
            attribute_id("H$Master Dealer (19)$Dealer Name (16923)"), 16923
        )
        self.assertEqual(attribute_id("Master Dealer (22)"), 22)
        self.assertIsNone(attribute_id(""))
        self.assertIsNone(attribute_id("tanpa-id"))


class AggregateSegmentsTests(unittest.TestCase):
    def segments(self) -> list[dict]:
        return [
            # data kolom 10 (dua segmen)
            {"COLUMN_ID": "Umur (10)", "USED_SIZE": 1000, "RECORDS_COUNT": 120},
            {"COLUMN_ID": "Umur (10)", "USED_SIZE": 500, "RECORDS_COUNT": 80},
            # data kolom 11 (angka langsung, engine lama)
            {"COLUMN_ID": 11, "USED_SIZE": 300, "RECORDS_COUNT": 200},
            # hierarki atribut kolom 10
            {
                "TABLE_ID": "H$Tabel (2)$Umur (10)",
                "COLUMN_ID": "POS_TO_ID",
                "USED_SIZE": 400,
            },
            {
                "TABLE_ID": "H$Tabel (2)$Umur (10)",
                "COLUMN_ID": "ID_TO_POS",
                "USED_SIZE": 100,
            },
            # row number internal (tidak tampil, tetap dihitung di total segmen)
            {"COLUMN_ID": "RowNumber XYZ (12)", "USED_SIZE": 50, "RECORDS_COUNT": 200},
            # objek tanpa ID -> artifact
            {"COLUMN_ID": "?", "USED_SIZE": 7},
            {"TABLE_ID": "tanpa-id", "COLUMN_ID": "POS_TO_ID", "USED_SIZE": 3},
        ]

    def test_data_hierarchy_and_rows(self) -> None:
        sizes = aggregate_segments(self.segments())

        self.assertEqual(sizes.data(10), 1500)
        self.assertEqual(sizes.data(11), 300)
        self.assertEqual(sizes.hierarchy(10), 500)
        self.assertEqual(sizes.total(10), 2000)
        self.assertEqual(sizes.row_count(10), 120)
        self.assertEqual(sizes.row_count(11), 200)
        self.assertEqual(sizes.segment_bytes, 2360)
        self.assertEqual(sizes.artifact_bytes, 10)
        self.assertEqual(sizes.unmatched_segments, 1)

    def test_dictionary_size_per_attribute(self) -> None:
        storage_columns = [
            {
                "COLUMN_ID": "Umur (10)",
                "COLUMN_TYPE": "BASIC_DATA",
                "DICTIONARY_SIZE": 800,
            },
            {
                "COLUMN_ID": "Umur (10)",
                "COLUMN_TYPE": "HIERARCHY_POSITION_TO_DATAID",
                "DICTIONARY_SIZE": 0,
            },
            {
                "COLUMN_ID": "POS_TO_ID",
                "COLUMN_TYPE": "BASIC_DATA",
                "DICTIONARY_SIZE": 999,
            },
        ]

        sizes = aggregate_segments(self.segments(), storage_columns)

        self.assertEqual(sizes.dictionary(10), 800)
        self.assertEqual(sizes.dictionary(11), 0)
        self.assertEqual(sizes.total(10), 1500 + 500 + 800)

    def test_table_rows_uses_largest_column(self) -> None:
        sizes = aggregate_segments(self.segments())
        self.assertEqual(table_rows(sizes, [10, 11]), 200)
        self.assertEqual(table_rows(sizes, []), 0)

    def test_dictionary_fallback_when_no_segments(self) -> None:
        storage_columns = [
            {
                "COLUMN_ID": "Kolom (5)",
                "COLUMN_TYPE": "BASIC_DATA",
                "DICTIONARY_SIZE": 2048,
                "STRING_INDEX_SIZE": 0,
            }
        ]
        sizes = aggregate_segments([], storage_columns)

        self.assertEqual(sizes.data(5), 2048)
        self.assertEqual(sizes.segment_bytes, 0)


class ColumnCardinalityTests(unittest.TestCase):
    def test_reads_distinct_states_with_both_id_keys(self) -> None:
        rows = [
            {"ColumnID": 10, "Statistics_DistinctStates": 1234},
            {"ColumnID": "Kolom (11)", "Statistics_DistinctStates": "56"},
            {"ColumnID": 10, "Statistics_DistinctStates": 1230},
            {"ColumnID": None, "Statistics_DistinctStates": 9},
            {"ColumnID": "POS_TO_ID", "Statistics_DistinctStates": 9},
        ]
        self.assertEqual(column_cardinality(rows), {10: 1234, 11: 56})

    def test_missing_rows_give_empty_map(self) -> None:
        self.assertEqual(column_cardinality(None), {})
        self.assertEqual(column_cardinality([]), {})


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime

from build_work_json import (
    award_fy,
    choose_payment_metadata,
    contractor_display_name,
    contractor_key,
    is_placeholder,
    iso_date,
    money_to_int,
    parse_documents,
)


class BuildWorkJsonTests(unittest.TestCase):
    def test_money_rounds_half_up_to_integer_rupees(self) -> None:
        self.assertEqual(money_to_int(100.49), 100)
        self.assertEqual(money_to_int("100.50"), 101)

    def test_award_financial_year_comes_from_job_number(self) -> None:
        self.assertEqual(award_fy("087-21-000011"), "2021-22")
        self.assertEqual(award_fy("BlockCAO310-20-000203"), "2020-21")

    def test_contractor_key_removes_vendor_code_and_ms(self) -> None:
        self.assertEqual(
            contractor_key("023275 M/s. Sukesh Rai & Co."),
            "sukesh rai co",
        )

    def test_contractor_display_name_removes_vendor_code(self) -> None:
        self.assertEqual(
            contractor_display_name("023275 SUKESH RAI"),
            "SUKESH RAI",
        )

    def test_source_sentinel_date_becomes_null(self) -> None:
        self.assertIsNone(iso_date(datetime(1900, 1, 1)))
        self.assertEqual(iso_date(datetime(2025, 2, 3)), "2025-02-03")

    def test_placeholder_names_cover_known_source_variants(self) -> None:
        self.assertTrue(is_placeholder("WO-13--27051821-BLANK.pdf"))
        self.assertTrue(is_placeholder("NOT APPLICALE FOR PMC.pdf"))
        self.assertFalse(is_placeholder("Licence Copy ANIL.jpeg"))

    def test_document_parser_preserves_type_and_filename(self) -> None:
        self.assertEqual(
            list(parse_documents("AS: sanction.pdf | Agreement: signed contract.pdf")),
            [("AS", "sanction.pdf"), ("Agreement", "signed contract.pdf")],
        )

    def test_payment_metadata_prefers_matching_description(self) -> None:
        candidates = [
            {"work_description": "Drain work in ward 11", "ward_name": "Ward A"},
            {"work_description": "Road work in ward 11", "ward_name": "Ward B"},
        ]
        selected = choose_payment_metadata("Road work in ward 11", candidates)
        self.assertEqual(selected["ward_name"], "Ward B")


if __name__ == "__main__":
    unittest.main()

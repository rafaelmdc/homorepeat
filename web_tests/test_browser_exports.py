from django.test import RequestFactory, SimpleTestCase

from apps.browser.exports import (
    BrowserTSVExportMixin,
    TSV_CONTENT_TYPE,
    clean_tsv_value,
    iter_tsv_rows,
    stream_tsv_response,
)


class TSVExportTests(SimpleTestCase):
    def test_clean_tsv_value_formats_scalar_values(self):
        self.assertEqual(clean_tsv_value(None), "")
        self.assertEqual(clean_tsv_value(True), "true")
        self.assertEqual(clean_tsv_value(False), "false")
        self.assertEqual(clean_tsv_value(42), "42")
        self.assertEqual(clean_tsv_value(3.5), "3.5")

    def test_clean_tsv_value_normalizes_embedded_separators(self):
        self.assertEqual(
            clean_tsv_value("alpha\tbeta\r\ngamma"),
            "alpha beta  gamma",
        )

    def test_iter_tsv_rows_emits_header_only_for_empty_rows(self):
        self.assertEqual(
            list(iter_tsv_rows(["Run", "Status"], [])),
            ["Run\tStatus\n"],
        )

    def test_iter_tsv_rows_emits_clean_tab_separated_rows(self):
        rows = [
            ("run-alpha", "complete", True),
            ("run-beta", None, False),
        ]

        self.assertEqual(
            list(iter_tsv_rows(["Run", "Status", "Imported"], rows)),
            [
                "Run\tStatus\tImported\n",
                "run-alpha\tcomplete\ttrue\n",
                "run-beta\t\tfalse\n",
            ],
        )

    def test_iter_tsv_rows_rejects_wrong_width_rows(self):
        with self.assertRaisesMessage(ValueError, "expected 2"):
            list(iter_tsv_rows(["Run", "Status"], [("run-alpha",)]))

    def test_stream_tsv_response_sets_download_headers_and_body(self):
        response = stream_tsv_response(
            "homorepeat_runs.tsv",
            ["Run", "Status"],
            [("run-alpha", "complete")],
        )

        self.assertEqual(response["Content-Type"], TSV_CONTENT_TYPE)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="homorepeat_runs.tsv"',
        )
        self.assertEqual(
            b"".join(response.streaming_content).decode("utf-8"),
            "Run\tStatus\nrun-alpha\tcomplete\n",
        )


class BrowserTSVExportMixinTests(SimpleTestCase):
    def test_download_url_preserves_filters_and_strips_display_params(self):
        request = RequestFactory().get(
            "/browser/runs/",
            {
                "q": "run",
                "status": "success",
                "order_by": "run_id",
                "page": "2",
                "after": "cursor-after",
                "before": "cursor-before",
                "fragment": "virtual-scroll",
            },
        )
        view = BrowserTSVExportMixin()
        view.request = request

        self.assertEqual(
            view.get_tsv_download_url(),
            "/browser/runs/?q=run&status=success&order_by=run_id&download=tsv",
        )

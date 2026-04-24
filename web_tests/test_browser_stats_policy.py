from __future__ import annotations

import ast
from pathlib import Path

from django.test import RequestFactory, TestCase

from apps.browser.stats import build_stats_filter_state
from apps.browser.stats.policy import (
    StatsPayloadClassification,
    StatsPayloadType,
    classify_stats_payload,
)


class BrowserStatsPolicyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.filter_state = build_stats_filter_state(self.factory.get("/browser/lengths/"))

    def test_all_current_stats_payloads_classify_as_sync_cache(self):
        for payload_type in StatsPayloadType:
            self.assertEqual(
                classify_stats_payload(self.filter_state, payload_type),
                StatsPayloadClassification.SYNC_CACHE,
                payload_type.value,
            )


class BrowserStatsServiceBoundaryTests(TestCase):
    def test_queries_and_payloads_modules_do_not_import_view_layer(self):
        repo_root = Path(__file__).resolve().parents[1]
        module_paths = [
            repo_root / "apps/browser/stats/queries.py",
            repo_root / "apps/browser/stats/payloads.py",
        ]

        forbidden_prefixes = ("apps.browser.views", "django.views")
        discovered_imports: list[str] = []

        for module_path in module_paths:
            module_ast = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
            for node in ast.walk(module_ast):
                if isinstance(node, ast.Import):
                    discovered_imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    discovered_imports.append(node.module)

        forbidden_imports = [
            module_name
            for module_name in discovered_imports
            if module_name.startswith(forbidden_prefixes)
        ]
        self.assertEqual(forbidden_imports, [])

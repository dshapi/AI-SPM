"""Tests for threathunting_ai/scan_registry.py"""
from threathunting_ai.scan_registry import SCAN_REGISTRY, ScanDefinition, SCAN_NAMES


class TestScanRegistry:
    def test_all_expected_scans_present(self):
        assert "exposed_credentials" in SCAN_REGISTRY
        assert "unused_open_ports" in SCAN_REGISTRY
        assert "overprivileged_tools" in SCAN_REGISTRY
        assert "sensitive_data_exposure" in SCAN_REGISTRY
        assert "runtime_anomaly_detection" in SCAN_REGISTRY
        # New collectors (Plan A Tasks 3-5)
        assert "prompt_secret_exfiltration" in SCAN_REGISTRY
        assert "data_leakage_detection" in SCAN_REGISTRY
        assert "tool_misuse_detection" in SCAN_REGISTRY
        assert "unexpected_listen_ports" in SCAN_REGISTRY

    def test_scan_count(self):
        assert len(SCAN_REGISTRY) == 9

    def test_each_entry_is_scan_definition(self):
        for name, defn in SCAN_REGISTRY.items():
            assert isinstance(defn, ScanDefinition), f"{name} not a ScanDefinition"

    def test_scan_definition_has_callable_collector(self):
        for name, defn in SCAN_REGISTRY.items():
            assert callable(defn.collector), f"{name}.collector not callable"

    def test_scan_definition_has_description(self):
        for name, defn in SCAN_REGISTRY.items():
            assert defn.description, f"{name}.description is empty"

    def test_scan_names_matches_registry(self):
        assert set(SCAN_NAMES) == set(SCAN_REGISTRY.keys())

    def test_scan_names_count(self):
        assert len(SCAN_NAMES) == 9

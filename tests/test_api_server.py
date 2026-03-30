"""Tests for the REST API server."""

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestAPIServer:
    def _write_cache(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def _sample_cache(self):
        return {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "readings": [
                {
                    "patient_id": "uuid-1",
                    "patient_name": "Juan García",
                    "value": 125,
                    "timestamp": "2026-03-30T10:00:00+00:00",
                    "trend_name": "STABLE",
                    "trend_arrow": "→",
                    "is_high": False,
                    "is_low": False,
                },
                {
                    "patient_id": "uuid-2",
                    "patient_name": "María López",
                    "value": 65,
                    "timestamp": "2026-03-30T10:00:00+00:00",
                    "trend_name": "DOWN_SLOW",
                    "trend_arrow": "↘",
                    "is_high": False,
                    "is_low": True,
                },
            ],
        }

    def test_get_all_readings(self, tmp_path):
        cache_path = tmp_path / "readings_cache.json"
        self._write_cache(str(cache_path), self._sample_cache())

        with patch("src.api_server.CACHE_FILE", cache_path):
            from src.api_server import app
            client = TestClient(app)
            resp = client.get("/api/readings")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["readings"]) == 2

    def test_get_patient_reading(self, tmp_path):
        cache_path = tmp_path / "readings_cache.json"
        self._write_cache(str(cache_path), self._sample_cache())

        with patch("src.api_server.CACHE_FILE", cache_path):
            from src.api_server import app
            client = TestClient(app)
            resp = client.get("/api/readings/uuid-1")
            assert resp.status_code == 200
            assert resp.json()["patient_name"] == "Juan García"

    def test_get_patient_not_found(self, tmp_path):
        cache_path = tmp_path / "readings_cache.json"
        self._write_cache(str(cache_path), self._sample_cache())

        with patch("src.api_server.CACHE_FILE", cache_path):
            from src.api_server import app
            client = TestClient(app)
            resp = client.get("/api/readings/nonexistent")
            assert resp.status_code == 404

    def test_no_cache_file(self, tmp_path):
        cache_path = tmp_path / "nonexistent.json"

        with patch("src.api_server.CACHE_FILE", cache_path):
            from src.api_server import app
            client = TestClient(app)
            resp = client.get("/api/readings")
            assert resp.status_code == 404

    def test_health_check(self, tmp_path):
        cache_path = tmp_path / "readings_cache.json"
        self._write_cache(str(cache_path), self._sample_cache())

        with patch("src.api_server.CACHE_FILE", cache_path):
            from src.api_server import app
            client = TestClient(app)
            resp = client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["patient_count"] == 2

    def test_health_check_no_cache(self, tmp_path):
        cache_path = tmp_path / "nonexistent.json"

        with patch("src.api_server.CACHE_FILE", cache_path):
            from src.api_server import app
            client = TestClient(app)
            resp = client.get("/api/health")
            assert resp.status_code == 200
            assert resp.json()["patient_count"] == 0

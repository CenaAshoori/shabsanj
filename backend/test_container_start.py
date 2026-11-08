"""Check fresh volume startup and the public configuration boundary."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from .app import app
from .config import openrouter_key
from .container_start import seed_data


class ContainerStartupTests(unittest.TestCase):
    def test_fresh_volume_is_seeded_and_refreshes_survive_restart(self):
        with TemporaryDirectory() as directory:
            seed = Path(directory) / "seed"
            data = Path(directory) / "data"
            seed.mkdir()
            for name in ("catalog.json", "tours.json", "tickets.json"):
                (seed / name).write_text(json.dumps({"source": name}))
            seed_data(seed, data)
            self.assertEqual(len(list(data.glob("*.json"))), 3)
            (data / "tickets.json").write_text('{"refreshed":true}')
            (data / "tours.json").unlink()
            seed_data(seed, data)
            self.assertEqual(json.loads((data / "tickets.json").read_text()), {"refreshed": True})
            self.assertEqual((data / "tours.json").read_text(), (seed / "tours.json").read_text())

    def test_public_config_exposes_only_configuration_status(self):
        with TestClient(app) as client, patch.dict("os.environ", {}, clear=True):
            response = client.get("/api/config")
            self.assertEqual(response.json(), {"openrouter_configured": False})
            self.assertEqual(response.headers["cache-control"], "no-store")
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-placeholder"}):
                self.assertEqual(client.get("/api/config").json(), {"openrouter_configured": True})

    def test_mounted_key_file_is_optional_and_read_on_server(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            path = Path(directory) / "credential"
            with patch.dict("os.environ", {"OPENROUTER_API_KEY_FILE": str(path)}):
                self.assertEqual(openrouter_key(), "")
                path.write_text("test-placeholder\n")
                self.assertEqual(openrouter_key(), "test-placeholder")

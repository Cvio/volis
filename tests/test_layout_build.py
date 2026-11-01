"""What makes a copy a customer's."""

import importlib.util
from pathlib import Path

from volis.config import PythonConfig

spec = importlib.util.spec_from_file_location("layout_build", Path(__file__).parent.parent / "scripts" / "layout_build.py")
layout_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout_build)


def test_a_customers_settings_turn_developer_mode_off(tmp_path):
    for settings in ("", "[translate]\nmodel = \"x\"\n", "[setup]\nways = [\"together\"]\n"):
        path = tmp_path / "volis-python.toml"
        path.write_text(layout_build.for_a_customer(settings), encoding="utf-8")
        loaded, _ = PythonConfig.load(path)
        assert loaded.setup.developer is False
    assert loaded.setup.ways == ["together"]

"""Compatibility entry point for the current Morphset UI scenario."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name("run_model_morphset_scenarios.py")))

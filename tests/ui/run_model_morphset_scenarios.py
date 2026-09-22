"""Run the current Morphset workflow through fresh Blender UI dialogs."""
import runpy
import sys
from pathlib import Path

repo = sys.argv[sys.argv.index('--') + 1]
g = runpy.run_path(str(Path(repo) / 'tests/ui/run_ui_scenarios.py'))
from ui.model_morphset_steps import build_steps
g['steps'][:] = [('workspace', g['setup_morphset_workspace']), ('settle', lambda: None)] + build_steps(g)

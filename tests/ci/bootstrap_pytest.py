"""Install test-only packages into Blender's isolated Python environment."""

import sys

try:
    import pip  # noqa: F401
except ImportError:
    import ensurepip
    ensurepip.bootstrap()

from pip._internal.cli.main import main as pip_main

packages = [
    "pytest>=8,<10", "syrupy>=4,<6",
    "numpy>=1.24", "scipy>=1.13", "biotite>=1.1,<1.7",
    "databpy>=0.0.18", "MDAnalysis>=2.7", "mrcfile", "starfile",
    "PyYAML", "msgpack>=0.5.6",
]
code = pip_main(["install", "--disable-pip-version-check", *packages])
if code:
    raise SystemExit(code)
print(f"test packages installed for Blender Python {sys.version}")

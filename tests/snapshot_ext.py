"""Deterministic numpy-array snapshot extension for syrupy.

Lifted (near-verbatim) from MolecularNodes' ``tests/utils.py``. Serializes
numpy arrays with pinned precision so tiny floating-point noise in geometry
output doesn't cause spurious snapshot failures, and truncates large arrays so
the ``.ambr`` baselines stay reviewable in git.

Usage: request the ``geo_snapshot`` fixture and ``assert geo_snapshot == arr``.
Regenerate baselines after an intentional geometry change with
``--snapshot-update`` and code-review the diff.
"""

from __future__ import annotations

import numpy as np
from syrupy.extensions.amber import AmberSnapshotExtension


class NumpySnapshotExtension(AmberSnapshotExtension):
    def serialize(self, data, *, cutoff: int = 1000, **kwargs):
        if isinstance(data, np.ndarray):
            if data.ndim == 1 and len(data) > cutoff:
                data = data[:cutoff]
            return np.array2string(
                data,
                precision=1,
                threshold=2000,
                floatmode="maxprec_equal",
            )
        return super().serialize(data, **kwargs)

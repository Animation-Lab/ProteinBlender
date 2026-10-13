"""Named filaments - a shipped subunit and the lattice that repeats it.

The helical builder can make any filament from a rise and a twist, which is
the right tool when you have a structure and know its numbers. It is the wrong
tool for "I need a microtubule": that takes a tubulin dimer positioned on the
tube's axis, thirteen strands, and four more numbers nobody remembers.

A preset carries all of it. The subunit is one repeat unit cut from a
deposited filament and moved rigidly so the filament's axis is +Z through the
origin (``scripts/make_filament_subunits.py``), which is the frame
``core.symmetry_builder`` turns copies about - so the radius comes out right
without anyone placing an axis. The lattice is the deposit's own.

Both halves are checked against the deposit they came from: building a
preset's lattice from its subunit has to land copies on the neighbouring
subunits in the PDB entry (``tests/integration/test_filament_presets.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "filaments"


@dataclass(frozen=True)
class FilamentPreset:
    """One buildable filament."""

    id: str
    label: str
    description: str
    #: File under ``data/filaments`` holding one repeat unit in the filament's
    #: own frame.
    structure: str
    #: Where the unit and the lattice came from, for the UI and the docs.
    source: str
    #: Angstrom along the axis, and degrees about it, per unit along a strand.
    rise: float
    twist: float
    #: How many strands, how far round the axis each is from the last
    #: (degrees) and how far along it (Angstrom). See
    #: ``symmetry_builder.lattice_sites``.
    strands: int = 1
    stagger: float = 0.0
    strand_twist: Optional[float] = None
    #: Units along each strand when the user has not asked for a length.
    default_count: int = 10

    def settings(self, count: Optional[int] = None) -> dict:
        """Build settings, in the shape the symmetry builder takes them."""
        return {
            "kind": "H",
            "count": int(count if count is not None else self.default_count),
            "rise": self.rise,
            "twist": self.twist,
            "strands": self.strands,
            "stagger": self.stagger,
            "strand_twist": self.strand_twist,
            "axis": (0.0, 0.0, 1.0),
        }

    def count_for_length(self, angstrom: float) -> int:
        """Units along each strand for a filament about ``angstrom`` long.

        Along *each* strand: a micron of microtubule is a micron of every one
        of its thirteen protofilaments, not a micron shared between them.
        """
        if not self.rise:
            return 1
        return max(1, round(float(angstrom) / abs(self.rise)))

    def length(self, count: int) -> float:
        """How long a filament of ``count`` units a strand is, in Angstrom."""
        return max(int(count), 1) * abs(self.rise)

    def subunit_total(self, count: int) -> int:
        """How many copies of the unit a build of ``count`` a strand draws."""
        return max(int(count), 1) * max(int(self.strands), 1)


#: A tubulin dimer along a protofilament, in Angstrom. From the helical
#: symmetry PDB 7SJ7 was reconstructed with.
_TUBULIN_DIMER = 81.5

PRESETS: Tuple[FilamentPreset, ...] = (
    FilamentPreset(
        id="ACTIN",
        label="Actin filament",
        description=("F-actin: one helix of actin subunits, 27.5 A apart, "
                     "which reads as two strands winding round each other"),
        structure="actin_8a2t.pdb",
        source="PDB 8A2T (Oosterheert et al., Nature 2022), chain C",
        rise=27.5,
        twist=-166.7,
        default_count=26,
    ),
    FilamentPreset(
        id="MICROTUBULE",
        label="Microtubule",
        description=("Thirteen straight protofilaments of tubulin dimers "
                     "round a tube about 25 nm across, with its seam"),
        structure="tubulin_7sj7.pdb",
        source=("PDB 7SJ7 (LaFrance et al., PNAS 2022), chains A and B: "
                "human alpha-1B and beta-3 tubulin"),
        rise=_TUBULIN_DIMER,
        twist=0.0,
        strands=13,
        # Once round the tube climbs three monomers - a dimer and a half -
        # and it does so winding left-handed.
        stagger=1.5 * _TUBULIN_DIMER / 13,
        strand_twist=-360.0 / 13,
        default_count=12,
    ),
)


def get(preset_id: str) -> Optional[FilamentPreset]:
    """The preset with this id, or ``None``."""
    wanted = (preset_id or "").upper()
    return next((preset for preset in PRESETS if preset.id == wanted), None)


def structure_path(preset: FilamentPreset) -> str:
    """Absolute path of the preset's shipped subunit."""
    return str(_DATA_DIR / preset.structure)

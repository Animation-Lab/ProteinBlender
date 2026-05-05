"""DNA/RNA sequence builder for ProteinBlender.

Generates biotite AtomArray structures from nucleotide sequences using
template coordinates extracted from the 1BNA B-DNA crystal structure
(Dickerson dodecamer, 1.9 A resolution).
"""

import math
import numpy as np
from scipy.spatial.transform import Rotation
from pathlib import Path

import biotite.structure as struc
import biotite.structure.io.pdb as pdb_io


# ---------------------------------------------------------------------------
# Helix parameters
# ---------------------------------------------------------------------------

B_DNA_PARAMS = {"rise": 3.38, "twist": 36.0}   # Angstroms, degrees
A_FORM_PARAMS = {"rise": 2.6, "twist": 32.7}   # Used for RNA

COMPLEMENTS = {
    "DNA": {"A": "T", "T": "A", "G": "C", "C": "G"},
    "RNA": {"A": "U", "U": "A", "G": "C", "C": "G"},
}

RES_NAMES = {
    "DNA": {"A": "DA", "T": "DT", "G": "DG", "C": "DC"},
    "RNA": {"A": "A", "U": "U", "G": "G", "C": "C"},
}

# Which residue in 1BNA to use as sense / antisense template for each base.
# 1BNA is the palindromic Dickerson dodecamer; both chains read CGCGAATTCGCG 5'->3'.
# 1BNA chain-A (sense): DC1  DG2  DC3  DG4  DA5  DA6  DT7  DT8  DC9  DG10 DC11 DG12
# 1BNA chain-B (anti):  DC13 DG14 DC15 DG16 DA17 DA18 DT19 DT20 DC21 DG22 DC23 DG24
# Pairing: A:i pairs with B:(25-i). Antisense picks below mirror the sense picks
# spatially: each antisense pick is the chain-B residue paired with the same-base
# chain-A residue used by the sense picks (e.g. sense DC=A:3 pairs with B:22=DG, so
# antisense DG=B:22; sense DG=A:4 pairs with B:21=DC, so antisense DC=B:21; etc.).
_SENSE_PICKS = {"DC": 3, "DG": 4, "DA": 5, "DT": 7}
_ANTI_PICKS = {"DC": 21, "DG": 22, "DA": 18, "DT": 20}

# Map single-letter base to DNA template key
_BASE_TO_TEMPLATE = {"A": "DA", "T": "DT", "G": "DG", "C": "DC", "U": "DT"}


# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------

_cache: dict = {}


class _HelixTemplates:
    """Extracted and axis-aligned nucleotide templates from 1BNA."""

    def __init__(self):
        ref = self._load_and_align()
        self.sense, self.anti = self._extract_all(ref)
        self.sense_radius, self.anti_radius = self._compute_radii(ref)
        self.phi_sense, self.phi_anti = self._compute_phases(ref)
        self.z_offset = self._compute_z_offset(ref)

    # -- loading / alignment ------------------------------------------------

    def _load_and_align(self):
        data_dir = Path(__file__).parent / "data"
        pdb_file = pdb_io.PDBFile.read(str(data_dir / "1BNA.pdb"))
        ref = pdb_file.get_structure(model=1)

        # C1' atoms on chain A define the helix axis
        c1_mask = (ref.atom_name == "C1'") & (ref.chain_id == "A")
        c1 = ref.coord[c1_mask]
        centre = c1.mean(axis=0)

        # PCA -> helix axis = first principal component
        cov = np.cov((c1 - centre).T)
        evals, evecs = np.linalg.eigh(cov)
        axis = evecs[:, np.argmax(evals)]
        if np.dot(axis, c1[-1] - c1[0]) < 0:
            axis = -axis

        ref = ref.copy()
        ref.coord -= centre

        # rotate axis -> Z
        z = np.array([0.0, 0.0, 1.0])
        cross = np.cross(axis, z)
        cn = np.linalg.norm(cross)
        if cn > 1e-8:
            cross /= cn
            angle = np.arccos(np.clip(np.dot(axis, z), -1.0, 1.0))
            ref.coord = Rotation.from_rotvec(cross * angle).apply(ref.coord)

        return ref

    # -- template extraction ------------------------------------------------

    def _extract_one(self, ref, chain, res_pos):
        mask = (ref.chain_id == chain) & (ref.res_id == res_pos)
        t = ref[mask].copy()
        c1_idx = np.where(t.atom_name == "C1'")[0]
        if len(c1_idx) == 0:
            return None
        c1_pos = t.coord[c1_idx[0]].copy()
        c1_angle = math.atan2(c1_pos[1], c1_pos[0])
        t.coord -= c1_pos
        t.coord = Rotation.from_euler("z", -c1_angle).apply(t.coord)
        return t

    def _extract_all(self, ref):
        sense, anti = {}, {}
        for rn, pos in _SENSE_PICKS.items():
            t = self._extract_one(ref, "A", pos)
            if t is not None:
                sense[rn] = t
        for rn, pos in _ANTI_PICKS.items():
            t = self._extract_one(ref, "B", pos)
            if t is not None:
                anti[rn] = t
        return sense, anti

    # -- geometry measurements from aligned reference -----------------------

    def _compute_radii(self, ref):
        def _mean_radius(chain):
            c = ref.coord[(ref.atom_name == "C1'") & (ref.chain_id == chain)]
            return np.sqrt(c[:, 0] ** 2 + c[:, 1] ** 2).mean()

        return _mean_radius("A"), _mean_radius("B")

    def _compute_phases(self, ref):
        c1_a1 = ref.coord[
            (ref.atom_name == "C1'") & (ref.chain_id == "A") & (ref.res_id == 1)
        ][0]
        c1_b24 = ref.coord[
            (ref.atom_name == "C1'") & (ref.chain_id == "B") & (ref.res_id == 24)
        ][0]
        return math.atan2(c1_a1[1], c1_a1[0]), math.atan2(c1_b24[1], c1_b24[0])

    def _compute_z_offset(self, ref):
        c1_a1 = ref.coord[
            (ref.atom_name == "C1'") & (ref.chain_id == "A") & (ref.res_id == 1)
        ][0]
        return float(c1_a1[2])


def _get_templates() -> _HelixTemplates:
    if "t" not in _cache:
        _cache["t"] = _HelixTemplates()
    return _cache["t"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_nucleic_acid(
    sequence: str,
    nucleic_type: str = "DNA",
    double_stranded: bool = True,
    form: str = "B",
) -> struc.AtomArray:
    """Build a nucleic-acid AtomArray from a sequence string.

    Parameters
    ----------
    sequence : str
        Nucleotide sequence 5'->3'.  Valid chars: ATGC (DNA) or AUGC (RNA).
    nucleic_type : str
        ``'DNA'`` or ``'RNA'``.
    double_stranded : bool
        Build complementary antisense strand.
    form : str
        ``'B'`` (B-DNA) or ``'A'`` (A-form, used automatically for RNA).

    Returns
    -------
    biotite.structure.AtomArray
        Complete structure with bonds, ready for MolecularNodes pipeline.
    """
    sequence = sequence.upper()
    tmpl = _get_templates()
    params = A_FORM_PARAMS if (nucleic_type == "RNA" or form == "A") else B_DNA_PARAMS
    res_map = RES_NAMES[nucleic_type]

    arrays: list[struc.AtomArray] = []
    atom_counter = 1

    # ---- sense strand (5'->3') -------------------------------------------
    for i, base in enumerate(sequence):
        nuc, atom_counter = _place_nucleotide(
            tmpl.sense[_BASE_TO_TEMPLATE[base]],
            angle_rad=math.radians(params["twist"] * i) + tmpl.phi_sense,
            radius=tmpl.sense_radius,
            z=params["rise"] * i + tmpl.z_offset,
            chain="A",
            res_id=i + 1,
            res_name=res_map[base],
            atom_counter=atom_counter,
            is_rna_u=(nucleic_type == "RNA" and base == "U"),
        )
        arrays.append(nuc)

    # ---- antisense strand ------------------------------------------------
    # The antisense runs antiparallel to the sense: its 5' end is at the
    # TOP of the helix (high z), its 3' end at the BOTTOM. We index the
    # strand 5'->3' (i = 0 .. N-1) but place residue i at spatial index
    # j = N-1-i so chain-B's natural backbone geometry (P on +Z side,
    # O3' on -Z side) lines up with neighbours going downward.
    if double_stranded:
        comp = "".join(COMPLEMENTS[nucleic_type][b] for b in reversed(sequence))
        n = len(comp)
        for i, base in enumerate(comp):
            j = n - 1 - i  # spatial z-index along the helix
            nuc, atom_counter = _place_nucleotide(
                tmpl.anti[_BASE_TO_TEMPLATE[base]],
                angle_rad=math.radians(params["twist"] * j) + tmpl.phi_anti,
                radius=tmpl.anti_radius,
                z=params["rise"] * j + tmpl.z_offset,
                chain="B",
                res_id=i + 1,
                res_name=res_map[base],
                atom_counter=atom_counter,
                is_rna_u=(nucleic_type == "RNA" and base == "U"),
            )
            arrays.append(nuc)

    # ---- concatenate -----------------------------------------------------
    full = arrays[0]
    for a in arrays[1:]:
        full += a

    # ensure standard annotations exist (some may be absent on constructed arrays)
    _ensure_annotations(full)

    # bonds
    full.bonds = _build_bonds(full)

    # Set DNA_BUILDER_DEBUG=1 in the environment to print a structure overview
    # (chain layout, cross-chain bonds, abnormally long bonds) to the console.
    import os
    if os.environ.get("DNA_BUILDER_DEBUG"):
        try:
            _debug_dump(full)
        except Exception as _e:
            print(f"[dna_builder debug] dump failed: {_e}")

    return full


def _debug_dump(array: struc.AtomArray):
    """Print a compact overview of the built array to help debug visual issues."""
    print("=" * 72)
    print(f"[dna_builder] AtomArray: {len(array)} atoms")
    chains = np.unique(array.chain_id)
    print(f"[dna_builder] chains found: {list(chains)}")
    for ch in chains:
        cm = array.chain_id == ch
        rids = np.unique(array.res_id[cm])
        zs = []
        for rid in rids:
            mask = cm & (array.res_id == rid) & (array.atom_name == "C1'")
            idx = np.where(mask)[0]
            if len(idx):
                zs.append((int(rid), float(array.coord[idx[0], 2])))
        print(f"[dna_builder] chain {ch!r}: {len(rids)} residues "
              f"(res_id range {rids[0]}..{rids[-1]})")
        head = ", ".join(f"r{rid}@z={z:.2f}" for rid, z in zs[:3])
        tail = ", ".join(f"r{rid}@z={z:.2f}" for rid, z in zs[-3:])
        print(f"[dna_builder]   first 3 C1' z: {head}")
        print(f"[dna_builder]   last  3 C1' z: {tail}")

    if array.bonds is None:
        print("[dna_builder] WARNING: array.bonds is None")
        return

    bonds_arr = array.bonds.as_array()
    print(f"[dna_builder] total bonds: {len(bonds_arr)}")

    # Look for any cross-chain bonds (atom i and atom j on different chains)
    chain_ids = array.chain_id
    cross = []
    for row in bonds_arr:
        i, j = int(row[0]), int(row[1])
        if chain_ids[i] != chain_ids[j]:
            cross.append((i, j, str(chain_ids[i]), str(chain_ids[j])))
    if cross:
        print(f"[dna_builder] !!! {len(cross)} CROSS-CHAIN bonds detected:")
        for i, j, ci, cj in cross[:10]:
            ai = f"{ci}/{array.res_id[i]}/{array.atom_name[i]}"
            aj = f"{cj}/{array.res_id[j]}/{array.atom_name[j]}"
            d = float(np.linalg.norm(array.coord[i] - array.coord[j]))
            print(f"[dna_builder]   {ai} <-> {aj}  d={d:.2f} A")
    else:
        print("[dna_builder] no cross-chain bonds (good).")

    # Look for unusually long bonds (> 2.5 A) — indicates geometry mismatch.
    long_bonds = []
    for row in bonds_arr:
        i, j = int(row[0]), int(row[1])
        d = float(np.linalg.norm(array.coord[i] - array.coord[j]))
        if d > 2.5:
            long_bonds.append((i, j, d))
    if long_bonds:
        print(f"[dna_builder] !!! {len(long_bonds)} bonds with length > 2.5 A:")
        for i, j, d in long_bonds[:10]:
            ci, cj = str(chain_ids[i]), str(chain_ids[j])
            ai = f"{ci}/{array.res_id[i]}/{array.atom_name[i]}"
            aj = f"{cj}/{array.res_id[j]}/{array.atom_name[j]}"
            print(f"[dna_builder]   {ai} <-> {aj}  d={d:.2f} A")
    else:
        print("[dna_builder] all bonds <= 2.5 A (good).")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _place_nucleotide(template, angle_rad, radius, z, chain, res_id, res_name,
                      atom_counter, is_rna_u=False):
    """Copy *template*, apply helical transform, set annotations."""
    nuc = template.copy()

    # Rotate to helical position
    nuc.coord = Rotation.from_euler("z", angle_rad).apply(nuc.coord)
    # Translate C1' to helical position
    nuc.coord += np.array([
        radius * math.cos(angle_rad),
        radius * math.sin(angle_rad),
        z,
    ])

    nuc.chain_id[:] = chain
    nuc.res_id[:] = res_id
    nuc.res_name[:] = res_name

    # Uracil: drop C7 (methyl group unique to thymine)
    if is_rna_u:
        keep = nuc.atom_name != "C7"
        nuc = nuc[keep]

    n = len(nuc)
    nuc.atom_id = np.arange(atom_counter, atom_counter + n)
    return nuc, atom_counter + n


def _ensure_annotations(array: struc.AtomArray):
    """Ensure all annotations required by the MN _create_object pipeline exist."""
    n = len(array)
    cats = array.get_annotation_categories()
    if "b_factor" not in cats:
        array.set_annotation("b_factor", np.zeros(n, dtype=np.float32))
    if "occupancy" not in cats:
        array.set_annotation("occupancy", np.ones(n, dtype=np.float32))
    if "hetero" not in cats:
        array.set_annotation("hetero", np.zeros(n, dtype=bool))
    if "sec_struct" not in cats:
        array.set_annotation("sec_struct", np.zeros(n, dtype=np.int32))
    if "entity_id" not in cats:
        array.set_annotation("entity_id", np.zeros(n, dtype=np.int32))
    if "atom_id" not in cats:
        array.set_annotation("atom_id", np.arange(1, n + 1, dtype=np.int32))


# ---------------------------------------------------------------------------
# Bond construction
# ---------------------------------------------------------------------------

# Backbone bonds shared by all nucleotides
_BACKBONE_BONDS = [
    ("P", "OP1"), ("P", "OP2"), ("P", "O5'"),
    ("O5'", "C5'"), ("C5'", "C4'"), ("C4'", "O4'"),
    ("C4'", "C3'"), ("C3'", "O3'"), ("C3'", "C2'"),
    ("C2'", "C1'"), ("C1'", "O4'"),
]

# Glycosidic bond: C1' -> N9 (purines) or C1' -> N1 (pyrimidines)
_PURINES = {"DA", "DG", "A", "G"}

# Base-specific bond tables
_PURINE_BASE = [
    ("N9", "C8"), ("C8", "N7"), ("N7", "C5"), ("C5", "C4"),
    ("C4", "N9"), ("C4", "N3"), ("N3", "C2"), ("C2", "N1"),
    ("N1", "C6"), ("C6", "C5"),
]
_ADENINE_EXTRA = [("C6", "N6")]
_GUANINE_EXTRA = [("C6", "O6"), ("C2", "N2")]

_PYRIMIDINE_BASE = [
    ("N1", "C2"), ("C2", "N3"), ("N3", "C4"), ("C4", "C5"),
    ("C5", "C6"), ("C6", "N1"),
]
_CYTOSINE_EXTRA = [("C2", "O2"), ("C4", "N4")]
_THYMINE_EXTRA = [("C2", "O2"), ("C4", "O4"), ("C5", "C7")]
_URACIL_EXTRA = [("C2", "O2"), ("C4", "O4")]

_BASE_BONDS: dict[str, list] = {
    "DA": _PURINE_BASE + _ADENINE_EXTRA,
    "DG": _PURINE_BASE + _GUANINE_EXTRA,
    "DC": _PYRIMIDINE_BASE + _CYTOSINE_EXTRA,
    "DT": _PYRIMIDINE_BASE + _THYMINE_EXTRA,
    "A":  _PURINE_BASE + _ADENINE_EXTRA,
    "G":  _PURINE_BASE + _GUANINE_EXTRA,
    "C":  _PYRIMIDINE_BASE + _CYTOSINE_EXTRA,
    "U":  _PYRIMIDINE_BASE + _URACIL_EXTRA,
}


def _build_bonds(array: struc.AtomArray) -> struc.BondList:
    bonds = struc.BondList(len(array))

    for chain in np.unique(array.chain_id):
        cm = array.chain_id == chain
        chain_res_ids = np.unique(array.res_id[cm])

        for res_id in chain_res_ids:
            rm = cm & (array.res_id == res_id)
            indices = np.where(rm)[0]
            names = array.atom_name[rm]
            rn = array.res_name[rm][0]

            name_to_idx = {n: int(idx) for n, idx in zip(names, indices)}

            # Backbone
            for a1, a2 in _BACKBONE_BONDS:
                if a1 in name_to_idx and a2 in name_to_idx:
                    bonds.add_bond(name_to_idx[a1], name_to_idx[a2],
                                   struc.BondType.SINGLE)

            # Glycosidic bond
            if rn in _PURINES:
                if "C1'" in name_to_idx and "N9" in name_to_idx:
                    bonds.add_bond(name_to_idx["C1'"], name_to_idx["N9"],
                                   struc.BondType.SINGLE)
            else:
                if "C1'" in name_to_idx and "N1" in name_to_idx:
                    bonds.add_bond(name_to_idx["C1'"], name_to_idx["N1"],
                                   struc.BondType.SINGLE)

            # Base bonds
            for a1, a2 in _BASE_BONDS.get(rn, []):
                if a1 in name_to_idx and a2 in name_to_idx:
                    bonds.add_bond(name_to_idx[a1], name_to_idx[a2],
                                   struc.BondType.SINGLE)

        # Inter-residue backbone: O3'(i) -> P(i+1)
        for j in range(len(chain_res_ids) - 1):
            o3 = np.where(cm & (array.res_id == chain_res_ids[j])
                          & (array.atom_name == "O3'"))[0]
            p = np.where(cm & (array.res_id == chain_res_ids[j + 1])
                         & (array.atom_name == "P"))[0]
            if len(o3) and len(p):
                bonds.add_bond(int(o3[0]), int(p[0]), struc.BondType.SINGLE)

    return bonds


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def get_complement(sequence: str, nucleic_type: str = "DNA") -> str:
    return "".join(COMPLEMENTS[nucleic_type][b] for b in sequence.upper())


def validate_sequence(sequence: str, nucleic_type: str = "DNA") -> str:
    """Strip invalid chars, return uppercased cleaned sequence."""
    valid = set("ATGC") if nucleic_type == "DNA" else set("AUGC")
    return "".join(c for c in sequence.upper() if c in valid)


def calculate_helix_info(length: int, nucleic_type: str = "DNA") -> dict:
    """Return dict with helix_length_angstrom, turns, base_pairs."""
    p = A_FORM_PARAMS if nucleic_type == "RNA" else B_DNA_PARAMS
    return {
        "helix_length_angstrom": length * p["rise"],
        "turns": length * p["twist"] / 360.0,
        "base_pairs": length,
    }

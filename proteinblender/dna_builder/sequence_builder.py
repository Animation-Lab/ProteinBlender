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
# Pairing: A:i pairs with B:(25-i).
#
# The antisense templates are NOT rebuilt as an independent strand. Each
# antisense residue below is the chain-B residue Watson-Crick paired with a
# chain-A sense pick, and it is extracted in that sense partner's frame (see
# ``_extract_pair_anti``) so the base pair keeps its true crystal geometry
# when stamped onto the idealized helix. Keyed by the ANTISENSE base's name:
#   anti DT = B:20 (partner of sense DA = A:5)
#   anti DA = B:18 (partner of sense DT = A:7)
#   anti DG = B:22 (partner of sense DC = A:3)
#   anti DC = B:21 (partner of sense DG = A:4)
_SENSE_PICKS = {"DC": 3, "DG": 4, "DA": 5, "DT": 7}
_ANTI_PICKS = {"DC": 21, "DG": 22, "DA": 18, "DT": 20}

# Watson-Crick complement of each DNA template res_name (used to find the
# sense partner of an antisense pick).
_TEMPLATE_COMPLEMENT = {"DA": "DT", "DT": "DA", "DC": "DG", "DG": "DC"}

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
        sense = {}
        for rn, pos in _SENSE_PICKS.items():
            t = self._extract_one(ref, "A", pos)
            if t is not None:
                sense[rn] = t
        anti = self._extract_pair_anti(ref)
        return sense, anti

    def _extract_pair_anti(self, ref):
        """Antisense templates in their Watson-Crick sense partner's frame.

        Each 1BNA antisense residue is transformed by the *same* operation
        ``_extract_one`` applies to its sense partner — translate the sense
        C1' to the origin, then de-rotate by the sense C1' angle — instead of
        being re-centred on its own C1'. The antisense residue therefore keeps
        its true crystal offset from the sense C1'.

        When the sense partner is later stamped onto the idealized helix, the
        antisense loop applies that same helical placement to this template
        (see ``build_nucleic_acid``), so every base pair reproduces 1BNA's real
        relative geometry: partners sit ~10.4 A apart with their bases meeting,
        and each base's nearest cross-strand neighbour is its true complement.

        The previous approach rebuilt the antisense as an independent strand
        from its own mean radius and phase angle; combined with the sense
        strand's mean radius that placed Watson-Crick partners ~11 A apart —
        farther than the diagonal (wrong-identity) neighbours — so bases
        appeared to pair with a same-identity base (Alpha 1.0.6 critical bug).
        """
        anti = {}
        for anti_rn, anti_pos in _ANTI_PICKS.items():
            sense_pos = _SENSE_PICKS[_TEMPLATE_COMPLEMENT[anti_rn]]
            sc1_mask = (
                (ref.chain_id == "A")
                & (ref.res_id == sense_pos)
                & (ref.atom_name == "C1'")
            )
            sc1_hits = ref.coord[sc1_mask]
            if len(sc1_hits) == 0:
                continue
            sc1 = sc1_hits[0]
            phi_sense = math.atan2(sc1[1], sc1[0])
            a = ref[(ref.chain_id == "B") & (ref.res_id == anti_pos)].copy()
            a.coord = a.coord - sc1
            a.coord = Rotation.from_euler("z", -phi_sense).apply(a.coord)
            anti[anti_rn] = a
        return anti

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
# Fiber-model helix generator (HELIX mode)
# ---------------------------------------------------------------------------

# Base-letter key used to look up a fiber repeat unit for each residue.
_TABLE_BASE = {
    "DNA": {"A": "A", "T": "T", "G": "G", "C": "C"},
    "RNA": {"A": "A", "U": "U", "G": "G", "C": "C"},
}


def _fiber_form_key(nucleic_type: str, form: str) -> str:
    """Map (nucleic_type, form) to a key in fiber_data.FIBER_UNITS."""
    if nucleic_type == "RNA":
        return "A-RNA"
    return "A" if form == "A" else "B"


def _build_fiber_helix(sequence, nucleic_type, double_stranded, form):
    """Build a canonical double/single helix from fiber-diffraction units.

    Faithful port of AmberTools NAB ``fd_helix`` (see fiber_data.py). Each
    residue is one repeat unit whose atoms are stored in helix-frame
    cylindrical coordinates (r, phi, z); successive residues are generated by a
    rigid screw transform (rotate by ``twist``, translate by ``rise``). The
    antisense strand mirrors phi and z (``hxmul = +1`` vs ``-1``) and walks back
    down the axis, so it runs antiparallel with its bases Watson-Crick paired to
    the sense strand. Because the units are fiber-refined, O3'(i)->P(i+1) closes
    to ~1.6 Å with no fitting step. The helix axis is +Z (bend rig depends on
    this). The 5'-terminal phosphate of each strand is omitted.
    """
    from .fiber_data import FIBER_UNITS, FIBER_PARAMS

    key = _fiber_form_key(nucleic_type, form)
    units = FIBER_UNITS[key]
    rise, twist = FIBER_PARAMS[key]
    res_map = RES_NAMES[nucleic_type]
    comp = COMPLEMENTS[nucleic_type]
    tbase = _TABLE_BASE[nucleic_type]

    n = len(sequence)
    strand1 = list(sequence)
    strand2 = [comp[b] for b in reversed(sequence)]  # 5'->3' of the complement
    strands = [strand1] if not double_stranded else [strand1, strand2]

    names, elems, coords = [], [], []
    chain_ids, res_ids, res_names = [], [], []

    current_height = 0.0
    current_rotation = 0.0
    inc_h, inc_r = rise, twist

    for si, strand in enumerate(strands):
        hxmul = -1 if si == 0 else 1
        chain = "A" if si == 0 else "B"
        for k, base in enumerate(strand):
            unit = units[tbase[base]]
            rname = res_map[base]
            drop_p = k == 0  # 5'-terminal phosphate omitted
            for atom, r, phi, z in unit:
                if drop_p and atom in ("P", "OP1", "OP2"):
                    continue
                yyr = math.radians(hxmul * phi + current_rotation)
                names.append(atom)
                elems.append(atom[0])
                coords.append((r * math.cos(yyr),
                               r * math.sin(yyr),
                               hxmul * z + current_height))
                chain_ids.append(chain)
                res_ids.append(k + 1)
                res_names.append(rname)
            current_height += inc_h
            current_rotation += inc_r
        # Reverse walk direction so the next strand runs antiparallel.
        inc_h, inc_r = -inc_h, -inc_r
        current_rotation += inc_r
        current_height += inc_h

    m = len(names)
    full = struc.AtomArray(m)
    full.coord = np.array(coords, dtype=np.float32)
    full.atom_name = np.array(names, dtype="<U6")
    full.element = np.array(elems, dtype="<U2")
    full.chain_id = np.array(chain_ids, dtype="<U4")
    full.res_id = np.array(res_ids, dtype=np.int32)
    full.res_name = np.array(res_names, dtype="<U5")
    full.hetero = np.zeros(m, dtype=bool)
    full.set_annotation("atom_id", np.arange(1, m + 1, dtype=np.int32))

    _ensure_annotations(full)
    full.bonds = _build_bonds(full, skip_inter_residue=False)

    import os
    if os.environ.get("DNA_BUILDER_DEBUG"):
        try:
            _debug_dump(full)
        except Exception as _e:
            print(f"[dna_builder debug] dump failed: {_e}")

    return full


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_nucleic_acid(
    sequence: str,
    nucleic_type: str = "DNA",
    double_stranded: bool = True,
    form: str = "B",
    wound_mask=None,
    schematic: bool = False,
    realistic_atoms: bool = False,
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
    wound_mask : sequence of bool, optional
        Per-base-pair wound state (length must match ``sequence``).
        ``True`` = wound (helical twist), ``False`` = unwound (ladder rung).
        If ``None`` (default), all bases are wound.  Used by LADDER mode.
    realistic_atoms : bool
        LADDER mode only. ``False`` (stylised, default) collapses every
        residue to a flat 2D sheet (all atoms at z=0). ``True`` keeps a
        natural 3D backbone extent so ball-and-stick reads as a real
        nucleotide. Bases are always perfectly flat so MN's Cartoon
        node renders rungs as flat blocks either way. Ignored in HELIX
        mode (which always uses real 1BNA crystal templates).

    Returns
    -------
    biotite.structure.AtomArray
        Complete structure with bonds, ready for MolecularNodes pipeline.
    """
    sequence = sequence.upper()
    n = len(sequence)

    # HELIX mode (default): canonical fiber-diffraction model. Each residue is
    # one fiber repeat unit (fiber_data.py) replicated by a rigid screw
    # transform — rotate by twist, translate by rise — so the sugar-phosphate
    # backbone is continuous (O3'(i)->P(i+1) ~= 1.6 Å) and Watson-Crick pairing
    # is correct by construction. LADDER mode is the only non-helix path.
    ladder_mode = wound_mask is not None and not any(wound_mask)
    if not ladder_mode:
        return _build_fiber_helix(sequence, nucleic_type, double_stranded, form)

    # ------------------------------------------------------------------
    # LADDER mode: stylised flat ladder — bases stacked in a plane, backbone
    # deliberately NOT atomically valid. Every bp held at constant angle, the
    # two strands placed exactly 180° apart at a common radius. Templates come
    # from canonical_geometry.py — procedural idealised geometries with base
    # ring atoms placed exactly in the z=0 plane (so MN's Style Cartoon has no
    # residual crystal-buckle to tilt the rungs). The anti template is sense's
    # X-axis-flipped twin, putting paired bases in a Watson-Crick dyad and
    # restoring antiparallel backbone direction.
    # ------------------------------------------------------------------
    tmpl = _get_templates()
    params = A_FORM_PARAMS if (nucleic_type == "RNA" or form == "A") else B_DNA_PARAMS
    res_map = RES_NAMES[nucleic_type]
    cum_angle = _cumulative_twist(n, params["twist"], wound_mask)

    from .canonical_geometry import get_canonical_templates, LADDER_RADIUS
    sense_phi = math.pi
    anti_phi = 0.0
    sense_radius = anti_radius = LADDER_RADIUS
    sense_tmpls = get_canonical_templates(
        realistic=realistic_atoms, schematic=schematic
    )
    # Anti's template is sense's, X-axis-flipped (y → -y, z → -z): aligns the
    # in-plane base frame of paired rungs and gives the anti strand inverted
    # P/O3' so the antiparallel placement (j=N-1-i) keeps O3'(i) next to P(i+1).
    anti_tmpls = {k: _flip_template_about_x(v) for k, v in sense_tmpls.items()}

    arrays: list[struc.AtomArray] = []
    atom_counter = 1

    # ---- sense strand (5'->3') -------------------------------------------
    for i, base in enumerate(sequence):
        nuc, atom_counter = _place_nucleotide(
            sense_tmpls[_BASE_TO_TEMPLATE[base]],
            angle_rad=cum_angle[i] + sense_phi,
            radius=sense_radius,
            z=params["rise"] * i + tmpl.z_offset,
            chain="A",
            res_id=i + 1,
            res_name=res_map[base],
            atom_counter=atom_counter,
            is_rna_u=(nucleic_type == "RNA" and base == "U"),
        )
        arrays.append(nuc)

    # ---- antisense strand ------------------------------------------------
    # The antisense runs antiparallel: its 5' end is at the TOP of the
    # helix (high z), its 3' end at the BOTTOM. We index the strand
    # 5'->3' (i = 0 .. N-1) but place residue i at spatial index
    # j = N-1-i so the backbone direction lines up with neighbours
    # going downward.
    #
    # This applies in both wound (helix) and ladder modes. In ladder
    # mode the anti template has been pre-flipped about its X axis (see
    # the LADDER setup above), which gives each anti residue an inverted
    # P/O3' arrangement; combined with the spatial reverse here, that
    # puts O3'(i) right next to P(i+1) for a clean antiparallel
    # backbone path even though we skip the explicit inter-residue
    # bonds in ladder mode.
    if double_stranded:
        comp = "".join(COMPLEMENTS[nucleic_type][b] for b in reversed(sequence))
        for i, base in enumerate(comp):
            j = n - 1 - i  # spatial z-index along the helix
            nuc, atom_counter = _place_nucleotide(
                anti_tmpls[_BASE_TO_TEMPLATE[base]],
                angle_rad=cum_angle[j] + anti_phi,
                radius=anti_radius,
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

    # bonds — skip the inter-residue O3'->P bonds in LADDER mode because
    # the templates were extracted from a wound helix where consecutive
    # residues are rotated 36° apart; without that rotation those bonds
    # stretch to ~6 Å and look like long crossing sticks.
    full.bonds = _build_bonds(full, skip_inter_residue=ladder_mode)

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


def _cumulative_twist(n: int, twist_deg: float, wound_mask) -> list[float]:
    """Per-position cumulative angle (radians) along the helix axis.

    The transition between two consecutive base pairs contributes ``twist``
    only when both endpoints are wound; if either is unwound, the angle
    holds steady (giving a flat ladder there).
    """
    if wound_mask is None:
        wound = [True] * n
    else:
        wound = [bool(w) for w in wound_mask]
        if len(wound) != n:
            raise ValueError(
                f"wound_mask length {len(wound)} does not match sequence length {n}"
            )

    twist_rad = math.radians(twist_deg)
    cum = [0.0] * n
    for k in range(1, n):
        if wound[k - 1] and wound[k]:
            cum[k] = cum[k - 1] + twist_rad
        else:
            cum[k] = cum[k - 1]
    return cum


def make_wound_mask(length: int, mode: str) -> list[bool] | None:
    """Build a wound mask from a high-level UI mode.

    Returns ``None`` for HELIX (all wound, default), or an all-False
    list for LADDER (all unwound, every bp held at constant angle).
    """
    if mode == "HELIX":
        return None
    if mode == "LADDER":
        return [False] * length
    raise ValueError(f"unknown winding mode: {mode!r}")


def _flip_template_about_x(template):
    """Rotate template 180° around X axis through C1' (y → -y, z → -z).

    Applied to anti templates in LADDER mode so paired sense/anti
    residues form a Watson-Crick dyad — a 180° rotation around the helix-
    radial axis at the pair's Z. This aligns the in-plane base frame of
    the two bases so MN's Cartoon renders each pair as one flat rung
    instead of a twisted X, and as a side effect restores biological
    antiparallel backbone direction inside each anti residue (P above
    C1', O3' below — opposite of sense).
    """
    out = template.copy()
    coord = out.coord.copy()
    coord[:, 1] = -coord[:, 1]
    coord[:, 2] = -coord[:, 2]
    out.coord = coord
    return out


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


def _build_bonds(array: struc.AtomArray, skip_inter_residue: bool = False) -> struc.BondList:
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

            # Glycosidic bond. Real purines bond C1'->N9; real
            # pyrimidines C1'->N1. In schematic ladder mode purines have
            # been stripped of N7/C8/N9, so we fall back to C1'->N1
            # (the same atom that anchors pyrimidines).
            if "C1'" in name_to_idx:
                if rn in _PURINES and "N9" in name_to_idx:
                    bonds.add_bond(name_to_idx["C1'"], name_to_idx["N9"],
                                   struc.BondType.SINGLE)
                elif "N1" in name_to_idx:
                    bonds.add_bond(name_to_idx["C1'"], name_to_idx["N1"],
                                   struc.BondType.SINGLE)

            # Base bonds
            for a1, a2 in _BASE_BONDS.get(rn, []):
                if a1 in name_to_idx and a2 in name_to_idx:
                    bonds.add_bond(name_to_idx[a1], name_to_idx[a2],
                                   struc.BondType.SINGLE)

        # Inter-residue backbone: O3'(i) -> P(i+1)
        if not skip_inter_residue:
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


def calculate_helix_info(length: int, nucleic_type: str = "DNA",
                         wound_mask=None) -> dict:
    """Return dict with helix_length_angstrom, turns, base_pairs.

    If ``wound_mask`` is given, the turn count reflects only the wound
    transitions (z-extent is unchanged by unwinding).
    """
    p = A_FORM_PARAMS if nucleic_type == "RNA" else B_DNA_PARAMS
    if wound_mask is None:
        wound_transitions = max(0, length - 1)
    else:
        wound = [bool(w) for w in wound_mask]
        wound_transitions = sum(
            1 for k in range(1, length) if wound[k - 1] and wound[k]
        )
    return {
        "helix_length_angstrom": length * p["rise"],
        "turns": wound_transitions * p["twist"] / 360.0,
        "base_pairs": length,
    }

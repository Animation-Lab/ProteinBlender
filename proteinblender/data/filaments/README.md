# Filament subunits

One repeat unit of each filament the presets in `core/filament_presets.py` can build.

Each file is cut from a deposited structure and moved rigidly so that the filament's axis is +Z through the origin, the unit sits out along +X, and its centre is at z = 0.
That is the frame the helical builder turns copies about, so a preset comes out with the right radius without anyone positioning an axis.
No atom has moved relative to any other: nothing is refined, idealised or rebuilt.
Waters are dropped; bound nucleotides and ions are kept.

| File | Source | What it is |
| --- | --- | --- |
| `actin_8a2t.pdb` | PDB 8A2T, chain C | One actin subunit of an Mg-ADP actin filament, with its ADP and magnesium. Oosterheert et al., "Structural basis of actin filament assembly and aging", Nature 2022, doi:10.1038/s41586-022-05241-8. |
| `tubulin_7sj7.pdb` | PDB 7SJ7, chains A and B | One tubulin dimer (human alpha-1B and beta-3) of an undecorated 13-protofilament microtubule, with its GTP, GDP and magnesium. LaFrance et al., "Structural transitions in the GTP cap visualized by cryo-electron microscopy of catalytically inactive microtubules", PNAS 2022, doi:10.1073/pnas.2114994119. |

PDB entries are in the public domain (CC0 1.0).

Do not edit these by hand.
Regenerate them with `python scripts/make_filament_subunits.py`, which also rewrites the ground truth in `tests/data/filaments` that the presets are tested against.

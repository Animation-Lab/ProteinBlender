# Deposited assembly fixture

`1stm.cif.gz` contains the unmodified RCSB mmCIF for satellite tobacco mosaic
virus, downloaded from `https://files.rcsb.org/download/1STM.cif` on 2026-09-25
and compressed with gzip. It exercises the six deposited assembly definitions,
including identity-only chain subsets and transformations scoped to different
chain lists. Labels come from `_pdbx_struct_assembly.details`.

Expected protein chain placements (A, B, C, D, E):

| Assembly | Deposited description | Placements |
| --- | --- | --- |
| 1 | complete icosahedral assembly | 12, 12, 12, 12, 12 |
| 2 | icosahedral asymmetric unit | 1, 0, 0, 0, 0 |
| 3 | icosahedral pentamer | 1, 1, 1, 1, 1 |
| 4 | icosahedral 23 hexamer | 3, 1, 1, 1, 1 |
| 5 | icosahedral asymmetric unit, std point frame | 1, 0, 0, 0, 0 |
| 6 | crystal asymmetric unit, crystal frame | 1, 1, 1, 1, 1 |

Assembly 4's deposited description says “hexamer” even though its operator and
chain lists produce seven protein placements; the UI preserves that description.
Water label chains F–J map to author chains A–E and are not separate protein
objects. The tests validate the displayed protein chains.

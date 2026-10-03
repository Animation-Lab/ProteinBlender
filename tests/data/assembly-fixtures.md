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

## Composite operator fixture

`1m4x.cif.gz` contains the unmodified RCSB mmCIF for the PBCV-1 virus capsid
(quasi-atomic model), downloaded from `https://files.rcsb.org/download/1M4X.cif`
on 2026-10-03 and compressed with gzip.
It is the bundled structure whose deposited assemblies are *products* of two
operator groups, so it guards the operator-expression parser.
All assemblies list chains A, B and C.

| Assembly | `oper_expression` | Placements |
| --- | --- | --- |
| 1 | `(1-60)(61-88)` | 60 x 28 = 1680 |
| 2 | `(61-88)` | 28 |
| 3 | `(1-5)(61-88)` | 5 x 28 = 140 |
| 4 | `(1,2,6,10,23,24)(61-88)` | 6 x 28 = 168 |
| 5 | `(1-5)(63-68)` | 5 x 6 = 30 |
| 6 | `(1,10,23)(61,62,69-88)` | 3 x 22 = 66 |
| 7 | `(P)(61-88)` | 28 |

The right-hand group is applied first, so each placement is `M_left @ M_right`.
Assembly 6 also has a mixed group (`61,62,69-88`) that must expand to one union of 22 operators.

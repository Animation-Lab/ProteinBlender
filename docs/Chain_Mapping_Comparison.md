# Chain Mapping Approaches Comparison

## Implementation A (molecule_manager.py) - Simple Approach

### Initialization:
```python
# Simple chain mapping from string parsing
self.chain_mapping = {}
if hasattr(molecule.array, 'chain_mapping_str'):
    self.chain_mapping = self._parse_chain_mapping(molecule.array.chain_mapping_str)
```

### Key Methods:
```python
def _parse_chain_mapping(self, mapping_str: str) -> dict:
    """Parse chain mapping string into a dictionary"""
    mapping = {}
    if mapping_str:
        for pair in mapping_str.split(","):
            if ":" in pair:
                k, v = pair.split(":")
                mapping[int(k)] = v
    return mapping

def get_author_chain_id(self, numeric_chain_id: int) -> str:
    """Convert numeric chain ID to author chain ID"""
    if self.chain_mapping:
        return self.chain_mapping.get(numeric_chain_id, str(numeric_chain_id))
    return str(numeric_chain_id)
```

### Pros:
- Simple and straightforward
- Direct string parsing
- Easy to understand

### Cons:
- No biotite integration validation
- No fallback mechanisms
- Doesn't ensure chain_id_int annotation exists
- Single mapping only (no dual system)
- No robust type checking

---

## Implementation B (molecule_wrapper.py) - Robust Approach

### Initialization:
```python
# Ensure chain_id_int annotation exists
if not self.molecule.array.has_annotation("chain_id_int"):
    self.molecule.array.add_annotation("chain_id_int", dtype=int)
    unique_chain_ids, int_indices = np.unique(self.molecule.array.chain_id, return_inverse=True)
    self.molecule.array.set_annotation("chain_id_int", int_indices)

# 1. Author chain ID mapping (auth_asym_id)
raw_auth_map = molecule.array.chain_mapping_str() if hasattr(molecule.array, 'chain_mapping_str') else {}
self.auth_chain_id_map: Dict[int, str] = {}
if isinstance(raw_auth_map, dict):
    self.auth_chain_id_map = {k: v for k, v in raw_auth_map.items() if isinstance(k, int) and isinstance(v, str)}

# 2. Label asym ID mapping
self.idx_to_label_asym_id_map: Dict[int, str] = {}
if hasattr(molecule.array, 'chain_id'):
    unique_label_asym_ids = sorted(list(np.unique(molecule.array.chain_id)))
    for i, label_id_str in enumerate(unique_label_asym_ids):
        self.idx_to_label_asym_id_map[i] = str(label_id_str)
```

### Key Methods:
```python
def get_int_chain_index(self, label_asym_id: str) -> Optional[int]:
    """Return the internal integer chain index for a given label_asym_id"""
    # Direct mapping
    for idx, lab in self.idx_to_label_asym_id_map.items():
        if lab == label_asym_id:
            return idx
    # Fallback mapping
    for idx, auth_lab in self.auth_chain_id_map.items():
        if auth_lab == label_asym_id:
            return idx
    return None

def _get_chain_residue_ranges(self) -> Dict[str, Tuple[int, int]]:
    """Robust chain residue range calculation with fallbacks"""
    # Uses chain_id_int for reliable grouping
    # Multiple fallback mechanisms
    # Defensive programming with extensive error checking
```

### Pros:
- Ensures required annotations exist
- Dual mapping system (auth + label)
- Robust type checking and validation
- Multiple fallback mechanisms
- Better biotite integration
- Handles both mmCIF and PDB formats properly
- Extensive error logging and debugging
- Defensive programming patterns

### Cons:
- More complex initialization
- Requires understanding of biotite annotation system

---

## Decision: Use Implementation B's Approach

**Reasons:**
1. **Biotite Integration**: Properly integrates with biotite's annotation system
2. **Robustness**: Multiple fallback mechanisms prevent failures
3. **Type Safety**: Proper type checking and validation
4. **Dual Mapping**: Handles both author and label chain IDs
5. **Future-Proof**: Better handles different molecular file formats

---

## Implementation Plan

### Step 1: Replace chain mapping initialization in molecule_manager.py
- Replace simple `chain_mapping` with dual system
- Add `chain_id_int` annotation creation
- Add robust type checking

### Step 2: Update chain mapping methods
- Replace `_parse_chain_mapping()` with robust approach
- Update `get_author_chain_id()` to use new system
- Add `get_int_chain_index()` method

### Step 3: Update `_get_chain_residue_ranges()`
- Use `chain_id_int` for grouping
- Add fallback mechanisms
- Improve error handling

### Step 4: Update all chain ID usage throughout the class
- Update domain creation methods
- Update geometry node setup
- Update any hardcoded chain ID logic 
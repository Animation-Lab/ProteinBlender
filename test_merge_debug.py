"""Debug script to check why merge is disabled"""

import bpy

scene = bpy.context.scene

print("\n" + "="*60)
print("MERGE BUTTON DEBUG")
print("="*60)

# Find selected domains
selected_domains = []
for item in scene.outliner_items:
    if item.is_selected and item.item_type == 'DOMAIN':
        selected_domains.append(item)
        print(f"\nSelected domain: {item.name}")
        print(f"  ID: {item.item_id}")
        print(f"  Parent: {item.parent_id}")
        print(f"  Range: {item.domain_start}-{item.domain_end}")

print(f"\nTotal selected domains: {len(selected_domains)}")

if len(selected_domains) >= 2:
    # Check parent chains
    parent_chains = set()
    for domain in selected_domains:
        parent_chains.add(domain.parent_id)
    
    print(f"\nParent chains: {parent_chains}")
    print(f"Same parent chain: {len(parent_chains) == 1}")
    
    # Sort and check adjacency
    sorted_domains = sorted(selected_domains, key=lambda d: d.domain_start)
    print("\nSorted domains:")
    for d in sorted_domains:
        print(f"  {d.name}: {d.domain_start}-{d.domain_end}")
    
    # Check adjacency
    adjacent = True
    for i in range(len(sorted_domains) - 1):
        current_end = sorted_domains[i].domain_end
        next_start = sorted_domains[i+1].domain_start
        is_adjacent = (current_end + 1 == next_start)
        print(f"\nChecking adjacency between domains {i} and {i+1}:")
        print(f"  Domain {i} ends at: {current_end}")
        print(f"  Domain {i+1} starts at: {next_start}")
        print(f"  Adjacent (end+1 == start): {is_adjacent}")
        if not is_adjacent:
            adjacent = False
    
    print(f"\nAll domains adjacent: {adjacent}")
    print(f"Can merge: {len(parent_chains) == 1 and adjacent}")
else:
    print("\nNeed at least 2 domains selected to merge")

print("\n" + "="*60)
#!/usr/bin/env python3
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.getcwd())

try:
    from proteinblender.utils.scene_manager import sync_molecule_list_after_undo, sync_molecule_list_before_undo
    print("✅ SUCCESS: Both undo handler functions imported successfully!")
    print(f"   sync_molecule_list_before_undo: {sync_molecule_list_before_undo}")
    print(f"   sync_molecule_list_after_undo: {sync_molecule_list_after_undo}")
except ImportError as e:
    print(f"❌ IMPORT ERROR: {e}")
except Exception as e:
    print(f"❌ OTHER ERROR: {e}") 
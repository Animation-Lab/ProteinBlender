# protein_workspace/utils/file_io.py
import os
import tempfile
import requests

def fetch_pdb_from_rcsb(pdb_id):
    """Fetch a PDB file from the RCSB PDB database and store it locally."""
    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    try:
        r = requests.get(url)
        r.raise_for_status()
    except Exception as e:
        print(f"Error fetching PDB {pdb_id}: {e}")
        return False, None

    # Store in a temporary directory
    tmp_dir = tempfile.gettempdir()
    filepath = os.path.join(tmp_dir, f"{pdb_id}.pdb")
    with open(filepath, 'wb') as f:
        f.write(r.content)

    return True, filepath

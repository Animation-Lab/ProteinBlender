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

def get_protein_file(identifier, method='PDB'):
    """Get the protein file, either from cache or by downloading."""
    # Define file paths
    tmp_dir = tempfile.gettempdir()
    cache_path = os.path.join(tmp_dir, f"{identifier}.pdb")
    
    # Check if file exists in cache
    if os.path.exists(cache_path):
        return True, cache_path
        
    # If not in cache, download based on method
    if method == 'PDB':
        return fetch_pdb_from_rcsb(identifier)
    elif method == 'ALPHAFOLD':
        return fetch_from_alphafold(identifier)
    
    return False, None

def fetch_from_alphafold(uniprot_id):
    """Fetch a structure from AlphaFold database."""
    url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v4.pdb"
    try:
        r = requests.get(url)
        r.raise_for_status()
    except Exception as e:
        print(f"Error fetching AlphaFold structure {uniprot_id}: {e}")
        return False, None

    tmp_dir = tempfile.gettempdir()
    filepath = os.path.join(tmp_dir, f"{uniprot_id}.pdb")
    with open(filepath, 'wb') as f:
        f.write(r.content)

    return True, filepath

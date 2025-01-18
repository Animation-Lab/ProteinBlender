# protein_workspace/utils/file_io.py
import os
import tempfile
import requests

def fetch_pdb_from_rcsb(pdb_id):
    """Fetch a PDB file from the RCSB PDB database and store it locally."""
    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    print(f"fetching PDB file from {url}")
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
    """Get the protein file contents, either from cache or by downloading."""
    print(f"getting protein file for {identifier} with method {method}")
    # Define file paths
    tmp_dir = tempfile.gettempdir()
    cache_path = os.path.join(tmp_dir, f"{identifier}.pdb")
    
    try:
        # Check if file exists in cache
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                return f.read()
            
        # If not in cache, download based on method
        success, filepath = None, None
        if method == 'PDB':
            success, filepath = fetch_pdb_from_rcsb(identifier)
        elif method == 'ALPHAFOLD':
            success, filepath = fetch_from_alphafold(identifier)
        
        if success and filepath:
            with open(filepath, 'r') as f:
                return f.read()
                
        return None
        
    except Exception as e:
        print(f"Error reading protein file for {identifier}: {e}")
        return None

def fetch_from_alphafold(uniprot_id):
    """Fetch a structure from AlphaFold database."""
    url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v4.pdb"
    print(f"fetching AlphaFold structure from {url}")
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

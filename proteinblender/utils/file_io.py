# protein_workspace/utils/file_io.py
import os
import tempfile
import requests
import time

def download_file(url, max_retries=3, retry_delay=1):
    """
    Download a file with retry logic and better error handling.
    
    Args:
        url (str): The URL to download
        max_retries (int): Maximum number of retry attempts
        retry_delay (float): Delay between retries in seconds
        
    Returns:
        tuple: (success, response or error message)
    """
    headers = {
        'User-Agent': 'ProteinBlender/1.0 (Blender Addon; Python Requests)',
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return True, response
            elif response.status_code == 404:
                return False, f"File not found (404): {url}"
            else:
                print(f"Attempt {attempt+1}/{max_retries}: HTTP error {response.status_code} from {url}")
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt+1}/{max_retries}: Error: {e}")
        
        # Only sleep if we're going to retry
        if attempt < max_retries - 1:
            time.sleep(retry_delay)
    
    return False, f"Failed to download after {max_retries} attempts: {url}"

def fetch_pdb_from_rcsb(pdb_id):
    """Fetch a PDB file from the RCSB PDB database and store it locally."""
    # Format PDB ID to lowercase for case-insensitivity
    pdb_id = pdb_id.lower()
    
    # List of URLs to try (in order)
    urls = [
        f"https://files.rcsb.org/download/{pdb_id}.pdb",                 # Primary RCSB URL
        f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb",         # Try uppercase
        f"https://www.ebi.ac.uk/pdbe/entry-files/download/{pdb_id}.pdb", # Try PDBe (Europe)
        f"https://data.pdbj.org/pub/pdb/data/structures/divided/pdb/{pdb_id[1:3]}/pdb{pdb_id}.ent.gz" # Try PDBj (Japan)
    ]
    
    errors = []
    
    for url in urls:
        print(f"Attempting to fetch PDB file from {url}")
        success, result = download_file(url)
        
        if success:
            # Store in a temporary directory
            tmp_dir = tempfile.gettempdir()
            filepath = os.path.join(tmp_dir, f"{pdb_id}.pdb")
            with open(filepath, 'wb') as f:
                f.write(result.content)
            print(f"Successfully downloaded PDB {pdb_id} from {url}")
            return True, filepath
        else:
            errors.append(result)
    
    # If we get here, all attempts failed
    error_msg = f"Failed to download PDB {pdb_id} from any source. Errors: {'; '.join(errors)}"
    print(error_msg)
    return False, None

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
    # Try multiple URL patterns
    urls = [
        f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v4.pdb",
        f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v3.pdb",
        f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v2.pdb"
    ]
    
    errors = []
    
    for url in urls:
        print(f"Attempting to fetch AlphaFold structure from {url}")
        success, result = download_file(url)
        
        if success:
            tmp_dir = tempfile.gettempdir()
            filepath = os.path.join(tmp_dir, f"{uniprot_id}.pdb")
            with open(filepath, 'wb') as f:
                f.write(result.content)
            print(f"Successfully downloaded AlphaFold model for {uniprot_id} from {url}")
            return True, filepath
        else:
            errors.append(result)
    
    # If we get here, all attempts failed
    error_msg = f"Failed to download AlphaFold model for {uniprot_id}. Errors: {'; '.join(errors)}"
    print(error_msg)
    return False, None

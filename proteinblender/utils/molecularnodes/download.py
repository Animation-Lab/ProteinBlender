import io
import os
import time
from pathlib import Path
import requests

CACHE_OLD = str(Path("~", ".MolecularNodes").expanduser())
CACHE_DIR = str(Path("~", "MolecularNodesCache").expanduser())

# rename old cache directories if users have them so we aren't leaving cached files in
# hidden folders on disk somewhere, I don't like the idea of silently renaming folders
# on a user's disk on load, so for now this will be disabled.
# TODO: make a decision on this (maybe a conformation popup on download)
# if os.path.exists(CACHE_OLD):
#     os.rename(CACHE_OLD, CACHE_DIR)


class FileDownloadPDBError(Exception):
    """
    Exception raised for errors in the file download process.

    Attributes:
        message -- explanation of the error
    """

    def __init__(
        self,
        message="There was an error downloading the file from the Protein Data Bank. PDB or format for PDB code may not be available.",
    ):
        self.message = message
        super().__init__(self.message)


def _download_with_retry(url, max_retries=3, retry_delay=1):
    """
    Download from URL with retry logic and better error handling.
    
    Args:
        url (str): The URL to download
        max_retries (int): Maximum number of retry attempts
        retry_delay (float): Delay between retries in seconds
        
    Returns:
        tuple: (success, response object or error message)
    """
    headers = {
        'User-Agent': 'ProteinBlender/1.0 (MolecularNodes; Python Requests)',
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


def download(code, format="cif", cache=CACHE_DIR, database="rcsb"):
    """
    Downloads a structure from the specified protein data bank in the given format.

    Parameters
    ----------
    code : str
        The code of the file to fetch.
    format : str, optional
        The format of the file. Defaults to "cif". Possible values are ['cif', 'pdb',
        'mmcif', 'pdbx', 'bcif'].
    cache : str, optional
        The cache directory to store the fetched file. Defaults to `~/MolecularNodesCache`.
    database : str, optional
        The database to fetch the file from. Defaults to 'rcsb'.

    Returns
    -------
    file
        The fetched file as a file-like object.

    Raises
    ------
    ValueError
        If the specified format is not supported.
    FileDownloadPDBError
        If the file couldn't be downloaded.
    """
    supported_formats = ["cif", "pdb", "bcif"]
    if format not in supported_formats:
        raise ValueError(f"File format '{format}' not in: {supported_formats=}")

    _is_binary = format in ["bcif"]
    filename = f"{code}.{format}"
    # create the cache location
    if cache:
        if not os.path.isdir(cache):
            os.makedirs(cache)

        file = os.path.join(cache, filename)
    else:
        file = None

    if file:
        if os.path.exists(file):
            return file

    # List of URLs to try in order
    urls = []
    
    # Primary URL based on selected database
    if database == "alphafold":
        urls = [
            get_alphafold_url(code, format),
            # No fallbacks for AlphaFold URLs
        ]
    else:
        # Main RCSB URL
        if database in ["rcsb", "pdb", "wwpdb"]:
            primary_url = _url(code, format, database)
            urls.append(primary_url)
            
            # Add alternative URLs
            if format == "pdb":
                # Try uppercase PDB ID
                urls.append(f"https://files.rcsb.org/download/{code.upper()}.{format}")
                
                # Try PDBe (Europe)
                urls.append(f"https://www.ebi.ac.uk/pdbe/entry-files/download/{code.lower()}.{format}")
                
                # Try PDBj (Japan)
                if len(code) == 4:  # Standard PDB IDs are 4 characters
                    urls.append(f"https://data.pdbj.org/pub/pdb/data/structures/divided/pdb/{code.lower()[1:3]}/pdb{code.lower()}.ent.gz")
    
    # Try each URL in succession
    errors = []
    for url in urls:
        print(f"Attempting to download {code}.{format} from {url}")
        success, result = _download_with_retry(url)
        
        if success:
            if _is_binary:
                content = result.content
            else:
                content = result.text
                
            if file:
                mode = "wb+" if _is_binary else "w+"
                with open(file, mode) as f:
                    f.write(content)
                print(f"Successfully downloaded {code}.{format} to {file}")
                return file
            else:
                if _is_binary:
                    return_file = io.BytesIO(content)
                else:
                    return_file = io.StringIO(content)
                return return_file
        else:
            errors.append(result)
    
    # If we get here, all download attempts failed
    error_msg = f"Failed to download {code}.{format}. Errors: {'; '.join(errors)}"
    print(error_msg)
    raise FileDownloadPDBError(error_msg)


def _url(code, format, database="rcsb"):
    "Get the URL for downloading the given file form a particular database."

    if database in ["rcsb", "pdb", "wwpdb"]:
        if format == "bcif":
            return f"https://models.rcsb.org/{code}.bcif"

        else:
            return f"https://files.rcsb.org/download/{code}.{format}"
    # if database == "pdbe":
    #     return f"https://www.ebi.ac.uk/pdbe/entry-files/download/{filename}"
    elif database == "alphafold":
        return get_alphafold_url(code, format)
    # if database == "pdbe":
    #     return f"https://www.ebi.ac.uk/pdbe/entry-files/download/{filename}"
    else:
        ValueError(f"Database {database} not currently supported.")


def get_alphafold_url(code, format):
    if format not in ["pdb", "cif", "bcif"]:
        ValueError(f"Format {format} not currently supported from AlphaFold databse.")

    # Try different ways to get the AlphaFold URL
    try:
        # First try the API approach
        url = f"https://alphafold.ebi.ac.uk/api/prediction/{code}"
        print(f"Querying AlphaFold API at {url}")
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                return data[0][f"{format}Url"]
    except Exception as e:
        print(f"Failed to get AlphaFold URL via API: {e}")
    
    # Fallback to direct URL pattern
    if format == "pdb":
        return f"https://alphafold.ebi.ac.uk/files/AF-{code}-F1-model_v4.pdb"
    elif format == "cif":
        return f"https://alphafold.ebi.ac.uk/files/AF-{code}-F1-model_v4.cif" 
    elif format == "bcif":
        return f"https://alphafold.ebi.ac.uk/files/AF-{code}-F1-model_v4.bcif"
    else:
        raise ValueError(f"Unsupported format {format} for AlphaFold database")

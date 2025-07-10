"""
 utils
 file operations, CSV handling, config management
"""

import os
import re
import csv
import json
import tempfile
import ctypes
import sys
import multiprocessing
from eP_C import OUTPUT_FILE_MAP, CSV_HEADERS


def parse_output_controls(idf_file):
    """
    Parse the OutputControl:Files object from an IDF file if it exists
    
    Args:
        idf_file (str): Path to the IDF file
    
    Returns:
        tuple: (output_controls dict, output_file_map dict)
    """
    try:
        with open(idf_file, 'r') as f:
            content = f.read()
        
        # Find the OutputControl:Files object
        pattern = r'OutputControl:Files,\s*([^;]*);'
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return None, OUTPUT_FILE_MAP
        
        # Extract parameters
        params_text = match.group(1).strip()
        params = [p.strip() for p in params_text.split(',')]
        
        # Define the parameter names in order
        param_names = list(OUTPUT_FILE_MAP.keys())
        
        # Create dictionary of parameters
        output_controls = {}
        for i, name in enumerate(param_names):
            if i < len(params):
                # Clean up comments from values
                value = params[i].split('!')[0].strip()
                output_controls[name] = value.lower() == 'yes'
            else:
                output_controls[name] = False

        return output_controls, OUTPUT_FILE_MAP
    
    except Exception as e:
        print(f"Error parsing OutputControl:Files from {idf_file}: {str(e)}")
        return None, OUTPUT_FILE_MAP


def resolve_csv_path(csv_output, idf_files):
    """
    Resolve the CSV output path based on whether it's a filename or full path.
    If it's just a filename, create it in the same folder as the IDF files.
    
    Args:
        csv_output (str): CSV output filename or path
        idf_files (list): List of IDF file paths
    
    Returns:
        str: Full path to the CSV file
    """
    if not csv_output:
        csv_output = "simulation_results.csv"
    
    # Check if csv_output is just a filename (no path separators)
    if os.path.dirname(csv_output) == "":
        # It's just a filename, so create it in the IDF folder
        if idf_files:
            # Get the directory of the first IDF file
            idf_folder = os.path.dirname(os.path.abspath(idf_files[0]))
            csv_path = os.path.join(idf_folder, csv_output)
        else:
            # Fallback to current directory if no IDF files
            csv_path = csv_output
    else:
        # It's a full path, use as-is
        csv_path = os.path.abspath(csv_output)
    
    return csv_path


def save_config_to_temp(config):
    """Save configuration to a temporary file"""
    temp_file = tempfile.mktemp(suffix='.json', prefix='epp_config_')
    with open(temp_file, 'w') as f:
        json.dump(config, f)
    return temp_file


def load_config_from_temp(config_file):
    """Load configuration from temporary file"""
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        os.unlink(config_file)  # Delete temp file
        return config
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def add_simulation_to_csv(idf_file, weather_file, info, row_number, csv_file):
    """
    Add a single simulation result to the CSV file.
    
    Args:
        idf_file (str): Path to the IDF file
        weather_file (str): Path to the weather file
        info (dict): Simulation status information
        row_number (int): Row number for this simulation
        csv_file (str): Path to the CSV file
    """
    # Check if CSV file exists, create with header if not
    file_exists = os.path.isfile(csv_file)
    
    # Get the base names
    idf_basename = os.path.basename(idf_file)
    idf_name = os.path.splitext(idf_basename)[0]
    weather_base = os.path.basename(weather_file)
    
    # Determine completion status - any non-completed status is considered failed (0)
    progress = 1 if info['status'] == 'Completed' else 0
    
    # Get completion message
    message = "EnergyPlus Completed Successfully" if progress == 1 else info['status']
    
    # Calculate runtime
    if info['start_time'] and info['end_time']:
        runtime = info['end_time'] - info['start_time']
    else:
        runtime = 0
    hours = int(runtime // 3600)
    minutes = int((runtime % 3600) // 60)
    seconds = int(runtime % 60)
    
    # Format data for CSV
    row = [
        row_number,              # Row number / sequential ID
        idf_name,                # Job_ID
        weather_base,            # WeatherFile
        idf_basename,            # ModelFile
        progress,                # Progress (1-Completed/0-Failed)
        message,                 # Message
        info['warnings'],        # Warnings
        info['errors'],          # Errors
        f"{hours:02d}",          # Hours
        f"{minutes:02d}",        # Minutes
        f"{seconds:02d}"         # Seconds
    ]
    
    with open(csv_file, 'a', newline='') as f:
        writer = csv.writer(f)
        
        # Write header if file doesn't exist
        if not file_exists:
            writer.writerow(CSV_HEADERS)

        writer.writerow(row)
        
    print(f"Added to CSV: {idf_name} - Status: {info['status']} - Progress: {progress}")


def allocate_console():
    """Allocate a console window for the current process (Windows only)"""
    try:
        # Allocate console
        kernel32 = ctypes.windll.kernel32
        kernel32.AllocConsole()
        
        # Redirect stdout, stderr to console
        sys.stdout = open('CONOUT$', 'w')
        sys.stderr = open('CONOUT$', 'w')
        sys.stdin = open('CONIN$', 'r')
        
        # Set console title
        from eP_C import APP_NAME, VERSION
        kernel32.SetConsoleTitleW(f"{APP_NAME} - by Misha Brovin v{VERSION}")
        
        return True
    except Exception as e:
        print(f"Failed to allocate console: {e}")
        return False


def cleanup_and_exit():
    """Cleanup function to ensure process termination"""
    try:
        # Terminate any remaining multiprocessing processes
        for process in multiprocessing.active_children():
            process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
    except:
        pass
    
    os._exit(0)


def signal_handler(signum, frame):
    """Handle system signals"""
    cleanup_and_exit()
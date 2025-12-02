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


def parse_err_file(idf_file):
    """
    Parse the EnergyPlus .err file to extract warning and error counts.

    Args:
        idf_file (str): Path to the IDF file

    Returns:
        tuple: (warnings_count, errors_count) or (0, 0) if file not found
    """
    # Construct the expected .err file path
    idf_dir = os.path.dirname(idf_file)
    idf_basename = os.path.basename(idf_file)
    idf_name = os.path.splitext(idf_basename)[0]
    err_file = os.path.join(idf_dir, f"{idf_name}out.err")

    warnings_count = 0
    errors_count = 0

    if not os.path.exists(err_file):
        return warnings_count, errors_count

    try:
        with open(err_file, 'r', encoding='utf-8', errors='ignore') as f:
            # Read the entire file to find the summary line at the end
            content = f.read()

            # Look for the EnergyPlus completion summary line
            # Pattern examples:
            # "************* EnergyPlus Completed Successfully-- 19520 Warning; 1 Severe Errors; Elapsed Time=00hr 20min  1.99sec"
            # "************* EnergyPlus Completed Successfully-- 0 Warning; 0 Severe Errors; Elapsed Time=00hr 01min 30.00sec"
            # Also handle warmup summary:
            # "************* EnergyPlus Warmup Error Summary. During Warmup: 1 Warning; 0 Severe Errors."

            # Pattern 1: Main completion summary
            pattern1 = r'EnergyPlus\s+Completed\s+Successfully--\s*(\d+)\s+Warning.*?(\d+)\s+Severe\s+Errors'
            match1 = re.search(pattern1, content, re.IGNORECASE)

            if match1:
                warnings_count = int(match1.group(1))
                errors_count = int(match1.group(2))
            else:
                # Pattern 2: Warmup summary (may appear in addition to main summary)
                # We'll still look for this but prefer the main summary
                pattern2 = r'During\s+Warmup:\s*(\d+)\s+Warning.*?(\d+)\s+Severe\s+Errors'
                match2 = re.search(pattern2, content, re.IGNORECASE)

                if match2:
                    warnings_count = int(match2.group(1))
                    errors_count = int(match2.group(2))

    except Exception as e:
        print(f"Error parsing .err file for {idf_name}: {str(e)}")

    return warnings_count, errors_count


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

    # Parse the .err file to get actual warning and error counts
    warnings_count, errors_count = parse_err_file(idf_file)

    # If the .err file parsing returned non-zero values, use those instead of the tracked counts
    if warnings_count > 0 or errors_count > 0:
        warnings = warnings_count
        errors = errors_count
    else:
        # Fallback to the tracked counts (from real-time parsing)
        warnings = info['warnings']
        errors = info['errors']

    # Format data for CSV
    row = [
        row_number,              # Row number / sequential ID
        idf_name,                # Job_ID
        weather_base,            # WeatherFile
        idf_basename,            # ModelFile
        progress,                # Progress (1-Completed/0-Failed)
        message,                 # Message
        warnings,                # Warnings (from .err file)
        errors,                  # Errors (from .err file)
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

    print(f"Added to CSV: {idf_name} - Status: {info['status']} - Progress: {progress} - Warnings: {warnings}, Errors: {errors}")


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
    """
    Cleanup function to ensure process termination.
    Only terminates child processes of this application, not other EnergyPlus instances.
    """
    print("Initiating cleanup...")

    # Restore all modified IDF files before exiting
    try:
        restored_count = restore_all_idf_files()
        if restored_count > 0:
            print(f"Restored {restored_count} IDF file(s) to original state")
    except Exception as e:
        print(f"Error restoring IDF files during cleanup: {e}")

    # Strategy 1: Terminate tracked multiprocessing children
    try:
        children = multiprocessing.active_children()
        print(f"Found {len(children)} active multiprocessing children")

        for child in children:
            try:
                if child.is_alive():
                    print(f"Terminating child process: {child.name} (PID: {child.pid})")
                    child.terminate()
                    child.join(timeout=2)

                    if child.is_alive():
                        print(f"Force killing child process: {child.name}")
                        child.kill()
                        child.join(timeout=1)
            except Exception as e:
                print(f"Error terminating child {child.name}: {e}")
    except Exception as e:
        print(f"Error accessing active_children: {e}")

    # Strategy 2: Kill all child processes using psutil (only OUR children)
    try:
        import psutil
        current_process = psutil.Process(os.getpid())
        children = current_process.children(recursive=True)

        print(f"Found {len(children)} child processes via psutil")

        for child in children:
            try:
                print(f"Terminating child PID {child.pid}: {child.name()}")
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Wait for termination
        gone, alive = psutil.wait_procs(children, timeout=3)

        # Force kill remaining processes
        for child in alive:
            try:
                print(f"Force killing PID {child.pid}: {child.name()}")
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    except Exception as e:
        print(f"Error with psutil cleanup: {e}")

    # Small delay to ensure cleanup completes
    import time
    time.sleep(0.5)

    print("Cleanup complete. Exiting...")
    os._exit(0)


def signal_handler(signum, frame):
    """Handle system signals"""
    cleanup_and_exit()


# Global registry to track modified IDF files and their backup information
# Format: {idf_file_path: (had_controls, original_text)}
_idf_backup_registry = {}


def backup_output_controls(idf_file):
    """
    Backup the existing OutputControl:Files object from an IDF file.
    Stores backup in global registry for later restoration.

    Args:
        idf_file (str): Path to IDF file

    Returns:
        tuple: (had_controls: bool, original_text: str or None)
    """
    try:
        # Normalize path for consistent registry keys
        idf_file = os.path.abspath(idf_file)

        with open(idf_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Find the OutputControl:Files object
        # Match "OutputControl:Files," followed by all lines until we hit a parameter line with semicolon
        # The pattern looks for lines with comma, followed eventually by a line with semicolon (the last param)
        # We need to match: OutputControl:Files, \n <params with comma> \n <last param with semicolon>
        # Strategy: Match all lines that start with whitespace and have comma OR semicolon, until we hit one with semicolon

        # More robust: Match OutputControl:Files, then keep matching lines until we find one that has
        # a semicolon followed by a comment (the last parameter)
        pattern = r'OutputControl:Files\s*,(?:\s*\n\s*[^,\n]*,\s*!-[^\n]*)*\s*\n\s*[^,\n]*;\s*!-[^\n]*'
        match = re.search(pattern, content, re.IGNORECASE)

        if match:
            # Extract the full OutputControl:Files block including the header
            full_text = match.group(0)
            backup_info = (True, full_text)
        else:
            backup_info = (False, None)

        # Register this backup in the global registry
        _idf_backup_registry[idf_file] = backup_info

        return backup_info

    except Exception as e:
        print(f"Error backing up OutputControl:Files from {idf_file}: {e}")
        return (False, None)


def inject_output_controls(idf_file, output_mode, output_files=None):
    """
    Inject or replace OutputControl:Files object in IDF file (in-place modification).

    Args:
        idf_file (str): Path to IDF file to modify
        output_mode (str): "Default", "Pristine", or "Custom"
        output_files (list): List of output file keys (e.g., ['Output CSV', 'Output JSON'])

    Returns:
        None (modifies file in-place)
    """
    # If Pristine mode, do nothing
    if output_mode == "Pristine":
        return

    if output_files is None:
        output_files = []

    try:
        # Read the IDF file
        with open(idf_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Build the OutputControl:Files object
        params = []
        for i, key in enumerate(OUTPUT_FILE_MAP.keys()):
            if output_mode == "Default":
                value = "Yes" if key in ['Output CSV', 'Output Tabular'] else "No"
            elif output_mode == "Custom":
                value = "Yes" if key in output_files else "No"
            else:
                value = "No"

            # Last parameter uses semicolon, others use comma
            separator = ";" if i == len(OUTPUT_FILE_MAP) - 1 else ","
            # Format: 4 spaces + value + separator + padding to column 30 + comment
            params.append(f"    {value}{separator:<25}!- {key}")

        output_control = "OutputControl:Files,\n" + "\n".join(params)

        # Check if OutputControl:Files already exists
        # Use the same robust pattern as backup: match lines with commas, then final line with semicolon
        pattern = r'OutputControl:Files\s*,(?:\s*\n\s*[^,\n]*,\s*!-[^\n]*)*\s*\n\s*[^,\n]*;\s*!-[^\n]*'
        match = re.search(pattern, content, re.IGNORECASE)

        if match:
            # Replace existing OutputControl:Files
            new_content = re.sub(pattern, output_control, content, flags=re.IGNORECASE)
        else:
            # Append at end of file
            # Remove trailing whitespace and add OutputControl:Files
            content = content.rstrip()
            new_content = content + "\n\n" + output_control + "\n"

        # Write modified content back
        with open(idf_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"Injected OutputControl:Files ({output_mode} mode) into {os.path.basename(idf_file)}")

    except Exception as e:
        print(f"Error injecting OutputControl:Files into {idf_file}: {e}")


def restore_output_controls(idf_file, had_controls, original_text):
    """
    Restore the original OutputControl:Files state in IDF file.
    Removes file from global registry after restoration.

    Args:
        idf_file (str): Path to IDF file
        had_controls (bool): Whether file originally had OutputControl:Files
        original_text (str): Original OutputControl:Files text (or None)

    Returns:
        None (modifies file in-place)
    """
    try:
        # Normalize path for consistent registry keys
        idf_file = os.path.abspath(idf_file)

        # Read current content
        with open(idf_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Pattern to find ANY OutputControl:Files block
        # Use the same robust pattern: match lines with commas, then final line with semicolon
        pattern = r'OutputControl:Files\s*,(?:\s*\n\s*[^,\n]*,\s*!-[^\n]*)*\s*\n\s*[^,\n]*;\s*!-[^\n]*'

        if had_controls and original_text:
            # Restore the original OutputControl:Files
            new_content = re.sub(pattern, original_text, content, count=1, flags=re.IGNORECASE | re.MULTILINE)
            print(f"Restored original OutputControl:Files in {os.path.basename(idf_file)}")
        elif not had_controls:
            # Remove the injected OutputControl:Files
            # Also remove the blank lines we added before it
            new_content = re.sub(r'\n\n' + pattern, '', content, count=1, flags=re.IGNORECASE | re.MULTILINE)
            # Fallback: remove without double newline
            new_content = re.sub(pattern, '', new_content, count=1, flags=re.IGNORECASE | re.MULTILINE)
            print(f"Removed injected OutputControl:Files from {os.path.basename(idf_file)}")
        else:
            # Nothing to do
            return

        # Write restored content back
        with open(idf_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        # Remove from registry after successful restoration
        if idf_file in _idf_backup_registry:
            del _idf_backup_registry[idf_file]

    except Exception as e:
        print(f"Error restoring OutputControl:Files in {idf_file}: {e}")


def restore_all_idf_files():
    """
    Restore all IDF files that were modified during simulation.
    Called when user stops simulations or on cleanup.

    Returns:
        int: Number of files restored
    """
    restored_count = 0

    # Make a copy of registry keys to avoid modification during iteration
    idf_files = list(_idf_backup_registry.keys())

    for idf_file in idf_files:
        try:
            had_controls, original_text = _idf_backup_registry[idf_file]
            restore_output_controls(idf_file, had_controls, original_text)
            restored_count += 1
        except Exception as e:
            print(f"Error restoring {idf_file}: {e}")

    return restored_count


def clear_idf_backup_registry():
    """Clear the IDF backup registry without restoring files."""
    _idf_backup_registry.clear()
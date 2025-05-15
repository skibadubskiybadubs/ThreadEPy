"""
Developed by: Mykhailo [Misha] Brovin

EnergyPlus Parallel Simulation Runner
This script runs multiple EnergyPlus simulations in parallel, displaying their status
It supports real-time updates, error handling, and CSV output for results.

If the .idf file contains OutputControl:Files object, the script will use them to determine the output files to generate,
otherwise it will generate the default output files (.err, .htm).

Developed for EnergyPlus version 23.2.0, but should work with other versions as well.
# Requirements:
- Python 3.7+
- Rich library for UI: `pip install rich`
- psutil for process monitoring: `pip install psutil`
- Windows OS (EnergyPlus is primarily supported on Windows)

How to use:
1. Place this script in the directory with your .IDF and .epw files.
2. Ensure EnergyPlus is installed and set the `DEFAULT_EPLUS_PATH` variable to its installation directory.
3. Run the script: `python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0"`

Alternatively, you can run it with command line arguments to limit the number of parallel simulations:
python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0" --max_workers 4
You can also specify a custom CSV output file:
python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0" --csv_output "results.csv"
You can also specify the weather file to use:
python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0" --weather_file "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
"""

import os
import re
import glob
import shutil
import tempfile
import subprocess
import time
import sys
import argparse
import threading
import queue
import multiprocessing
from multiprocessing import Manager, Process, cpu_count

# Check if dependencies are installed, if not, install them
def check_and_install_dependencies():
    try:
        import rich
        import psutil
    except ImportError:
        print("Installing required dependencies (rich, psutil)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "psutil"])
        print("Dependencies installed successfully.")
check_and_install_dependencies()

# Now import the dependencies
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich import box
import psutil

# Change this to the path of your EnergyPlus installation
DEFAULT_EPLUS_PATH = r"C:\EnergyPlusV23-2-0"

class SimulationStatus:
    """Class to track the status of simulations"""
    def __init__(self):
        self.simulations = {}
        self._lock = threading.Lock()
    
    def add_simulation(self, idf_name):
        """Add a new simulation to track"""
        with self._lock:
            self.simulations[idf_name] = {
                'status': 'Waiting',  # Start with Waiting status
                'progress': 0,
                'cpu': 0,
                'memory': 0,
                'log': [],
                'start_time': None,  # Will be set when simulation actually starts
                'end_time': None,
                'errors': 0,
                'warnings': 0,
                'process': None
            }
    
    def update_simulation(self, idf_name, **kwargs):
        """Update status of a simulation"""
        with self._lock:
            if idf_name in self.simulations:
                if 'status' in kwargs: # RESET cpu AND memory usage UPON COMPLETION
                    status = kwargs['status']
                    if status == 'Completed' or status.startswith('Failed'):
                        kwargs['cpu'] = 0.0
                        kwargs['memory'] = 0.0
                self.simulations[idf_name].update(kwargs)
                
                # If start_time is being set for the first time, set it
                if 'status' in kwargs and kwargs['status'] == 'Running' and not self.simulations[idf_name]['start_time']:
                    self.simulations[idf_name]['start_time'] = time.time()
    
    def add_log(self, idf_name, line):
        """Add a log line for a simulation"""
        with self._lock:
            if idf_name in self.simulations:
                # Keep last 10 log lines
                logs = self.simulations[idf_name]['log']
                logs.append(line.strip())
                if len(logs) > 10:
                    logs.pop(0)
                
                # Check for warnings and errors
                line_lower = line.lower()
                if '* warning *' in line_lower:
                    self.simulations[idf_name]['warnings'] += 1
                if '* severe *' in line_lower or 'fatal' in line_lower or 'error' in line_lower:
                    self.simulations[idf_name]['errors'] += 1
                
                # Try to estimate progress
                if 'begin month=' in line_lower:
                    try:
                        month = int(line.split('month=')[1].split()[0])
                        self.simulations[idf_name]['progress'] = min(100, int((month / 12) * 100))
                    except:
                        pass
                elif 'percentage through simulation:' in line_lower:
                    try:
                        progress = float(line.split('percentage through simulation:')[1].split('%')[0].strip())
                        self.simulations[idf_name]['progress'] = min(100, int(progress))
                    except:
                        pass
                elif 'energyplus starting' in line_lower or 'starting energyplus' in line_lower:
                    self.simulations[idf_name]['status'] = 'Running'
                    self.simulations[idf_name]['progress'] = max(1, self.simulations[idf_name]['progress'])
                elif 'starting simulation at' in line_lower:
                    self.simulations[idf_name]['status'] = 'Running'
                    self.simulations[idf_name]['progress'] = max(5, self.simulations[idf_name]['progress'])
                elif 'warming up {' in line_lower:
                    self.simulations[idf_name]['status'] = 'Running'
                    # Extract the warmup number and update progress
                    try:
                        warmup_num = int(line_lower.split('{')[1].split('}')[0])
                        self.simulations[idf_name]['progress'] = max(5 + warmup_num * 2, self.simulations[idf_name]['progress'])
                    except:
                        self.simulations[idf_name]['progress'] = max(10, self.simulations[idf_name]['progress'])
                
                # Check for completion or fatal errors
                if 'energyplus completed successfully' in line_lower:
                    self.simulations[idf_name]['status'] = 'Completed'
                    self.simulations[idf_name]['progress'] = 100
                    self.simulations[idf_name]['end_time'] = time.time()
                elif 'fatal' in line_lower or '**fatal:' in line_lower or 'fatal error' in line_lower:
                    self.simulations[idf_name]['status'] = 'Failed'
                    self.simulations[idf_name]['progress'] = 100  # Mark as 100% to show it's done
                    self.simulations[idf_name]['end_time'] = time.time()
                    self.simulations[idf_name]['errors'] += 1
    
    def get_table(self, completed_count=None, total=None):
        """Generate a rich Table to display simulation status"""
        title = "EnergyPlus Parallel Simulations"
        if completed_count is not None and total is not None:
            progress_pct = int((completed_count / total) * 100) if total > 0 else 0
            title = f"EnergyPlus Parallel Simulations - {completed_count}/{total} ({progress_pct}%)"
            
        table = Table(title=title, box=box.ROUNDED)
        
        # Add columns
        table.add_column("Simulation", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Progress", style="magenta")
        table.add_column("CPU %", style="yellow")
        table.add_column("Memory", style="yellow")
        table.add_column("Warnings", style="yellow")
        table.add_column("Errors", style="red")
        table.add_column("Runtime", style="blue")
        
        # Add rows for each simulation sorted by status (running first, then waiting, then completed)
        with self._lock:
            # Sort simulations by status: Running/Initializing first, then Waiting, then Completed/Failed
            sorted_sims = sorted(
                self.simulations.items(),
                key=lambda x: (
                    0 if x[1]['status'].startswith('Failed') else
                    1 if x[1]['status'] in ['Running', 'Initializing'] else
                    2 if x[1]['status'] == 'Waiting' else
                    3
                )
            )
            
            for name, info in sorted_sims:
                # Calculate runtime
                if info['end_time'] and info['start_time']:
                    runtime = info['end_time'] - info['start_time']
                elif info['start_time']:
                    runtime = time.time() - info['start_time']
                else:
                    runtime = 0
                
                runtime_str = f"{int(runtime // 60)}m {int(runtime % 60)}s"
                
                # Progress bar representation
                progress = info['progress']
                progress_bar = f"[{'#' * (progress // 5)}{' ' * (20 - progress // 5)}] {progress}%"
                
                # Status color
                status = info['status']
                if status == 'Waiting':
                    status_color = 'yellow'
                elif status == 'Initializing' or status == 'Running':
                    status_color = 'green'
                elif status == 'Completed':
                    status_color = 'blue'
                else:
                    status_color = 'red'
                
                table.add_row(
                    name,
                    f"[{status_color}]{status}[/{status_color}]",
                    progress_bar,
                    f"{info['cpu']:.1f}%",
                    f"{info['memory']:.1f} MB",
                    str(info['warnings']),
                    str(info['errors']),
                    runtime_str
                )
        
        return table
    
    def get_logs_panel(self):
        """Generate a panel with simulation logs, focusing on active simulations"""
        from rich.columns import Columns
        from rich.text import Text
        
        panels = []
        with self._lock:
            # Focus on active simulations first, then recently completed
            active_sims = [name for name, info in self.simulations.items() 
                          if info['status'] in ['Running', 'Initializing']]
            
            # Add recently completed or failed if we have space
            if len(active_sims) < 8:  # Limit to reasonable number for display
                completed_sims = [name for name, info in self.simulations.items() 
                                 if info['status'] in ['Completed', 'Failed'] and info['log']]
                # Take the most recent completions first (up to a reasonable limit)
                active_sims.extend(completed_sims[:8-len(active_sims)])
            
            for name in active_sims:
                info = self.simulations[name]
                logs = info['log']
                if not logs:  # Skip if no logs
                    continue
                    
                log_text = Text("\n".join(logs))
                
                # Apply color to warning and error messages
                for i, line in enumerate(logs):
                    line_lower = line.lower()
                    if "* warning *" in line_lower:
                        start = log_text.plain.find(line)
                        end = start + len(line)
                        log_text.stylize("yellow", start, end)
                    elif "* severe *" in line_lower or "fatal" in line_lower or "error" in line_lower:
                        start = log_text.plain.find(line)
                        end = start + len(line)
                        log_text.stylize("red", start, end)
                
                # Use different border colors based on status
                status = info['status']
                if status == 'Running':
                    border_style = "green"
                elif status == 'Completed':
                    border_style = "blue"
                elif status == 'Failed' or status.startswith('Failed ('):
                    border_style = "red"
                else:
                    border_style = "yellow"
                
                panel = Panel(log_text, title=f"[blue]{name}", border_style=border_style)
                panels.append(panel)
        
        if not panels:
            # If no active simulations, show a message
            return Panel("No active simulations", title="Logs")
                
        # Return a columns layout with all panels
        return Columns(panels)

def process_monitor(pid, idf_name, update_queue):
    """Monitor CPU and memory usage of a process and send updates to the queue"""
    try:
        process = psutil.Process(pid)
        
        while True:
            try:
                # Check if process still exists
                if not process.is_running():
                    break
                
                # Get CPU and memory usage
                cpu_percent = process.cpu_percent(interval=1)
                memory_info = process.memory_info()
                memory_mb = memory_info.rss / (1024 * 1024)
                
                # Send update to queue
                update_queue.put(("UPDATE", idf_name, {
                    'cpu': cpu_percent,
                    'memory': memory_mb
                }))
                
                # Short delay
                time.sleep(1)
            except:
                # Process likely ended
                break
    except:
        # Process not found
        pass

def parse_output_controls(idf_file):
    """
    Parse the OutputControl:Files object from an IDF file if it exists
    
    Args:
        idf_file (str): Path to the IDF file
    
    Returns:
        dict: Dictionary of output file controls, or None if not found
    """
    output_file_map = {
        'Output CSV': '.csv',
        'Output MTR': '.mtr',
        'Output ESO': '.eso',
        'Output EIO': '.eio',
        'Output Tabular': 'Table.html',
        'Output SQLite': '.sqlite',
        'Output JSON': '.json',
        'Output AUDIT': '.audit',
        'Output Zone Sizing': 'Zsz.csv',
        'Output System Sizing': 'Ssz.csv',
        'Output DXF': '.dxf',
        'Output BND': '.bnd',
        'Output RDD': '.rdd',
        'Output MDD': '.mdd',
        'Output MTD': '.mtd',
        'Output END': '.end',
        'Output SHD': '.shd',
        'Output DFS': '.dfs',
        'Output GLHE': '.glhe',
        'Output DelightIn': '.delightin',
        'Output DelightELdmp': '.delighteldmp',
        'Output DelightDFdmp': '.delightdfdmp',
        'Output EDD': '.edd',
        'Output DBG': '.dbg',
        'Output PerfLog': '.perflog',
        'Output SLN': '.sln',
        'Output SCI': '.sci',
        'Output WRL': '.wrl',
        'Output Screen': '.screen',
        'Output ExtShd': '.extshd',
        'Output Tarcog': '.tarcog'
    }

    try:
        with open(idf_file, 'r') as f:
            content = f.read()
        
        # Find the OutputControl:Files object
        pattern = r'OutputControl:Files,\s*([^;]*);'
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        
        if not match:
            return None, output_file_map
        
        # Extract parameters
        params_text = match.group(1).strip()
        params = [p.strip() for p in params_text.split(',')]
        
        # Define the parameter names in order
        param_names = list(output_file_map.keys())
        
        # Create dictionary of parameters
        output_controls = {}
        for i, name in enumerate(param_names):
            if i < len(params):
                # Clean up comments from values
                value = params[i].split('!')[0].strip()
                output_controls[name] = value.lower() == 'yes'
            else:
                output_controls[name] = False

        return output_controls, output_file_map
    
    except Exception as e:
        print(f"Error parsing OutputControl:Files from {idf_file}: {str(e)}")
        return output_controls, output_file_map

def run_energyplus_simulation(idf_file, weather_file, eplus_dir, update_queue, completed_queue=None):
    """
    Run a single EnergyPlus simulation.
    
    Args:
        idf_file (str): Path to the IDF file
        weather_file (str): Path to the EPW weather file
        eplus_dir (str): Path to the EnergyPlus installation directory
        update_queue (Queue): Queue for status updates
        completed_queue (Queue, optional): Queue for completion signals
    
    Returns:
        None
    """
    # Make sure we have absolute paths
    idf_file = os.path.abspath(idf_file)
    weather_file = os.path.abspath(weather_file)
    eplus_dir = os.path.abspath(eplus_dir)
    
    # Get the output directory (current working directory)
    output_dir = os.getcwd()
    
    # Get file names
    idf_basename = os.path.basename(idf_file)
    idf_name = os.path.splitext(idf_basename)[0]
    weather_basename = os.path.basename(weather_file)
    
    # Signal that we're starting
    update_queue.put(("INFO", f"Starting simulation for {idf_basename}"))
    update_queue.put(("UPDATE", idf_name, {'status': 'Initializing'}))
    
    try:
        # Create a unique temporary directory for the simulation
        temp_dir = tempfile.mkdtemp(prefix=f"EP_{idf_name}_")
        update_queue.put(("INFO", f"Created temporary directory: {temp_dir}"))
        
        # Copy the IDF file to the temp directory
        temp_idf = os.path.join(temp_dir, idf_basename)
        shutil.copy2(idf_file, temp_idf)
        
        # Copy the weather file to the temp directory
        temp_weather = os.path.join(temp_dir, weather_basename)
        shutil.copy2(weather_file, temp_weather)
        
        # Copy required EnergyPlus files to the temp directory
        energyplus_exe = os.path.join(eplus_dir, 'energyplus.exe')
        if not os.path.exists(energyplus_exe):
            update_queue.put(("INFO", f"Error: EnergyPlus executable not found at {energyplus_exe}"))
            update_queue.put(("UPDATE", idf_name, {
                'status': 'Failed (Missing EnergyPlus)',
                'progress': 100,
                'end_time': time.time()
            }))
            update_queue.put(("COMPLETED", idf_name))  # Signal completion even on error
            if completed_queue:
                completed_queue.put(idf_name)
            return
        
        for file in ['Energy+.idd', 'DElight2.dll', 'libexpat.dll', 'bcvtb.dll']:
            src_path = os.path.join(eplus_dir, file)
            if os.path.exists(src_path):
                dst_path = os.path.join(temp_dir, file)
                shutil.copy2(src_path, dst_path)
        
        # Create empty Energy+.ini file
        with open(os.path.join(temp_dir, 'Energy+.ini'), 'w') as f:
            pass
        
        # Change to the temporary directory
        original_dir = os.getcwd()
        os.chdir(temp_dir)
        
        # Parse OutputControl:Files from the IDF
        # output_controls, output_file_map = parse_output_controls(temp_idf)
        # update_queue.put(("INFO", f"Parsed OutputControl:Files from {idf_basename}"))
        # if output_controls:
        #     # Map OutputControl:Files options to EnergyPlus CLI flags
        #     # See: https://github.com/NREL/EnergyPlus/blob/develop/doc/running-energyplus-from-command-line.md
        #     # Only add flags if the output is disabled (set to False)
        #     if not output_controls.get('Output END', False): cmd.append('-a')
        #     if not output_controls.get('Output CSV', False): cmd.append('--no-csv')
        #     if not output_controls.get('Output MTR', False): cmd.append('--no-mtr')
        #     if not output_controls.get('Output ESO', False): cmd.append('--no-eso')
        #     if not output_controls.get('Output EIO', False): cmd.append('--no-eio')
        #     if not output_controls.get('Output Tabular', False): cmd.append('--no-tabular')
        #     if not output_controls.get('Output SQLite', False): cmd.append('--no-sqlite')
        #     if not output_controls.get('Output JSON', False): cmd.append('--no-json')
        #     if not output_controls.get('Output AUDIT', False): cmd.append('--no-audit')
        #     if not output_controls.get('Output Zone Sizing', False): cmd.append('--no-zsz')
        #     if not output_controls.get('Output System Sizing', False): cmd.append('--no-ssz')
        #     if not output_controls.get('Output DXF', False): cmd.append('--no-dxf')
        #     if not output_controls.get('Output BND', False): cmd.append('--no-bnd')
        #     if not output_controls.get('Output RDD', False): cmd.append('--no-rdd')
        #     if not output_controls.get('Output MDD', False): cmd.append('--no-mdd')
        #     if not output_controls.get('Output MTD', False): cmd.append('--no-mtd')
        #     if not output_controls.get('Output SHD', False): cmd.append('--no-shd')
        #     if not output_controls.get('Output DFS', False): cmd.append('--no-dfs')
        #     if not output_controls.get('Output GLHE', False): cmd.append('--no-glhe')
        #     if not output_controls.get('Output DelightIn', False): cmd.append('--no-delightin')
        #     if not output_controls.get('Output DelightELdmp', False): cmd.append('--no-delighteldmp')
        #     if not output_controls.get('Output DelightDFdmp', False): cmd.append('--no-delightdfdmp')
        #     if not output_controls.get('Output EDD', False): cmd.append('--no-edd')
        #     if not output_controls.get('Output DBG', False): cmd.append('--no-dbg')
        #     if not output_controls.get('Output PerfLog', False): cmd.append('--no-perflog')
        #     if not output_controls.get('Output SLN', False): cmd.append('--no-sln')
        #     if not output_controls.get('Output SCI', False): cmd.append('--no-sci')
        #     if not output_controls.get('Output WRL', False): cmd.append('--no-wrl')
        #     if not output_controls.get('Output Screen', False): cmd.append('--no-screen')
        #     if not output_controls.get('Output ExtShd', False): cmd.append('--no-extshd')
        #     if not output_controls.get('Output Tarcog', False): cmd.append('--no-tarcog')
            
        # Run EnergyPlus with the correct command line
        cmd = [
            energyplus_exe,
            '-w', weather_basename, # Weather file
            '-p', idf_name,         # Prefix for output files
            '-d', output_dir,       # Output directory
            '-a',                   # -a flag disables the annual simulation summary (.end file)
            idf_basename
        ]
        
        cmd_str = ' '.join(cmd)
        update_queue.put(("INFO", f"Running command: {cmd_str}"))
        update_queue.put(("UPDATE", idf_name, {'status': 'Running'}))
        
        # Start the EnergyPlus process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Start a process monitor for CPU and memory
        monitor_thread = threading.Thread(
            target=process_monitor,
            args=(process.pid, idf_name, update_queue)
        )
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Variables to track fatal errors
        fatal_error_detected = False
        
        # Read output in real-time and send to queue
        for line in iter(process.stdout.readline, ''):
            if line.strip():
                try:
                    update_queue.put(("LOG", idf_name, line.strip()))
                    
                    # Check for fatal error indicators in the output
                    line_lower = line.lower()
                    if '**fatal' in line_lower or 'fatal error' in line_lower or 'fatal:' in line_lower:
                        # Immediately mark as failed
                        update_queue.put(("UPDATE", idf_name, {
                            'status': 'Failed (Fatal Error)',
                            'progress': 100,  # Mark as 100% to show it's done
                            'end_time': time.time()
                        }))
                        fatal_error_detected = True
                        
                        # Signal completion so next simulation can start
                        update_queue.put(("COMPLETED", idf_name))
                        if completed_queue:
                            completed_queue.put(idf_name)
                        
                        # Terminate the process since we detected a fatal error
                        try:
                            process.terminate()
                        except:
                            pass
                        break
                    
                    # Also check for successful completion
                    if 'energyplus completed successfully' in line_lower:
                        update_queue.put(("UPDATE", idf_name, {
                            'status': 'Completed',
                            'progress': 100,
                            'end_time': time.time()
                        }))
                        update_queue.put(("COMPLETED", idf_name))
                        if completed_queue:
                            completed_queue.put(idf_name)
                except:
                    # If the queue is closed, stop sending updates
                    break
        
        # If no fatal error was detected in the logs, wait for the process to complete
        if not fatal_error_detected:
            try:
                process.wait(timeout=10)  # Wait up to 10 seconds for normal termination
            except subprocess.TimeoutExpired:
                # If it times out, force terminate
                process.terminate()
                try:
                    process.wait(timeout=5)
                except:
                    # If it still doesn't terminate, force kill
                    process.kill()
            
            # Update final status based on the return code (only if not already signaled as completed)
            if process.returncode == 0:
                update_queue.put(("UPDATE", idf_name, {
                    'status': 'Completed',
                    'progress': 100,
                    'end_time': time.time()
                }))
            else:
                update_queue.put(("UPDATE", idf_name, {
                    'status': 'Failed (Exit code: {})'.format(process.returncode),
                    'progress': 100,  # Mark as 100% to show it's done
                    'end_time': time.time()
                }))
            
            # Signal that this simulation is complete (for job scheduling)
            update_queue.put(("COMPLETED", idf_name))
            if completed_queue:
                completed_queue.put(idf_name)
        
        # Change back to the original directory
        os.chdir(original_dir)
        
        # Clean up the temporary directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
        
    except Exception as e:
        # Make sure we're back in the original directory
        try:
            if 'original_dir' in locals():
                os.chdir(original_dir)
        except:
            pass
        
        try:
            update_queue.put(("INFO", f"Error running simulation for {idf_basename}: {str(e)}"))
            update_queue.put(("UPDATE", idf_name, {
                'status': f'Failed: {str(e)}',
                'progress': 100,  # Mark as 100% to show it's done
                'end_time': time.time()
            }))
            
            # Signal that this simulation is complete (for job scheduling)
            update_queue.put(("COMPLETED", idf_name))
            if completed_queue:
                completed_queue.put(idf_name)
        except:
            # If the queue is closed, we can't send updates
            pass

def update_process(update_queue, status_tracker):
    """Process updates from the queue and update the status tracker"""
    while True:
        try:
            message = update_queue.get(timeout=0.5)
            if message == "DONE":
                break
            
            # Process different message types
            message_type = message[0]
            
            if message_type == "INFO":
                print(message[1])
            
            elif message_type == "UPDATE":
                # Update the status tracker
                idf_name = message[1]
                updates = message[2]
                status_tracker.update_simulation(idf_name, **updates)
            
            elif message_type == "LOG":
                idf_name = message[1]
                log_message = message[2]
                status_tracker.add_log(idf_name, log_message)
            
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error in update process: {str(e)}")

def run_simulations(eplus_path=DEFAULT_EPLUS_PATH, max_workers=None, csv_output="simulation_results.csv"):
    """
    Run all IDF files in the current directory in parallel
    with a Rich UI showing progress. Simulations are staged
    based on available CPU cores.
    
    Args:
        eplus_path (str): Path to the EnergyPlus installation directory
        max_workers (int): Maximum number of parallel simulations
        csv_output (str): Name of the CSV output file for results summary
    """
    # Define the CSV helper function locally to avoid import issues
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
        import csv
        import os
        
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
                writer.writerow([
                    "#", "Job_ID", "WeatherFile", "ModelFile", "Progress(1-Completed/0-Failed)", 
                    "Message", "Warnings", "Errors", "Hours", "Minutes", "Seconds"
                ])

            writer.writerow(row)
            
        print(f"Added to CSV: {idf_name} - Status: {info['status']} - Progress: {progress}")
    
    current_dir = os.getcwd()
    
    # Find all IDF files in the current directory
    idf_files = glob.glob(os.path.join(current_dir, "*.idf"))
    if not idf_files:
        print(f"No IDF files found in the current directory")
        return
    
    # Find weather files
    epw_files = glob.glob(os.path.join(current_dir, "*.epw"))
    if not epw_files:
        print(f"No EPW weather files found in the current directory")
        return
    # Use the first weather file
    weather_file = epw_files[0]
    
    # Initialize CSV file with headers
    if csv_output:
        import csv
        with open(csv_output, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "#", "Job_ID", "WeatherFile", "ModelFile", "Progress(1-Completed/0-Failed)", 
                "Message", "Warnings", "Errors", "Hours", "Minutes", "Seconds"
            ])
        print(f"Initialized CSV results file: {csv_output}")
    
    # Determine the number of logical processors
    available_cores = psutil.cpu_count(logical=True)
    
    # Set the maximum number of workers
    if max_workers is None:
        max_workers = max(1, available_cores - 1)  # Leave one core free
    max_workers = min(max_workers, len(idf_files))
    
    print(f"Found {len(idf_files)} IDF files:")
    for idf in idf_files:
        print(f"  - {os.path.basename(idf)}")
    
    print(f"Using weather file: {os.path.basename(weather_file)}")
    print(f"Using EnergyPlus: {eplus_path}")
    print(f"Running with {max_workers} parallel processes (out of {available_cores} logical processors)")
    
    # Create a status tracker
    status_tracker = SimulationStatus()
    
    # Create a layout for the UI
    layout = Layout()
    layout.split(
        Layout(name="stats"),  # Removed fixed size to auto-adjust
        Layout(name="logs")
    )
    
    # Register all simulations with status "Waiting"
    for idf_file in idf_files:
        idf_name = os.path.splitext(os.path.basename(idf_file))[0]
        status_tracker.add_simulation(idf_name)
    
    # Create a manager for sharing data between processes
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        # Method already set
        pass
    
    manager = Manager()
    update_queue = manager.Queue()
    completed_queue = manager.Queue()  # Separate queue for completion signals
    
    # Start update process
    update_thread = threading.Thread(target=update_process, args=(update_queue, status_tracker))
    update_thread.daemon = True
    update_thread.start()
    
    # Prepare process tracking
    active_processes = {}  # Maps idf_name to its Process object
    waiting_files = list(idf_files)  # List of files waiting to be processed
    completed_count = 0  # Count of completed simulations
    total = len(idf_files)  # Total number of simulations
    last_check_time = time.time()  # Time of last process check
    
    # For CSV row numbering
    row_counter = 0
    
    # Track which simulations have been written to CSV
    csv_written = set()
    
    # Start initial batch of simulations
    for i in range(min(max_workers, len(waiting_files))):
        idf_file = waiting_files.pop(0)
        idf_name = os.path.splitext(os.path.basename(idf_file))[0]
        
        # Create and start the process
        process = Process(
            target=run_energyplus_simulation,
            args=(idf_file, weather_file, eplus_path, update_queue, completed_queue)
        )
        process.start()
        
        # Track the process
        active_processes[idf_name] = {
            'process': process,
            'start_time': time.time(),
            'file': idf_file
        }
    
    # Display live UI updates
    try:
        with Live(layout, refresh_per_second=4) as live:
            # Continue until all simulations are done
            while active_processes or waiting_files:
                # Process messages in the update queue first to update statuses
                try:
                    while True:
                        message = update_queue.get_nowait()
                        if message == "DONE":
                            break
                        
                        # Process different message types
                        message_type = message[0]
                        
                        if message_type == "INFO":
                            # Just print the message
                            print(message[1])
                        
                        elif message_type == "UPDATE":
                            # Update the status tracker
                            idf_name = message[1]
                            updates = message[2]
                            
                            # Check if this is a status update to Failed
                            is_failure_update = False
                            if 'status' in updates and (updates['status'] == 'Failed' or 
                                                        updates['status'].startswith('Failed (')):
                                is_failure_update = True
                                print(f"⚠️ Detected failure for {idf_name}: {updates['status']}")
                            
                            # Update status tracker
                            status_tracker.update_simulation(idf_name, **updates)
                            
                            # If status was updated to Failed and has 'end_time', write to CSV immediately
                            if is_failure_update and 'end_time' in updates and idf_name not in csv_written and idf_name in active_processes:
                                info = status_tracker.simulations[idf_name]
                                if csv_output:
                                    add_simulation_to_csv(active_processes[idf_name]['file'], weather_file, info, row_counter, csv_output)
                                    csv_written.add(idf_name)
                                    row_counter += 1
                        
                        elif message_type == "LOG":
                            idf_name = message[1]
                            log_message = message[2]
                            status_tracker.add_log(idf_name, log_message)
                            
                            # Check if this log message indicates a fatal error
                            log_lower = log_message.lower()
                            if ('**fatal' in log_lower or 'fatal error' in log_lower or 'fatal:' in log_lower) and idf_name in active_processes:
                                # Force status update to Failed
                                status_tracker.update_simulation(idf_name, status='Failed (Fatal Error)', progress=100)
                                
                                # If not already written to CSV, write now
                                if idf_name not in csv_written and csv_output:
                                    info = status_tracker.simulations[idf_name]
                                    add_simulation_to_csv(active_processes[idf_name]['file'], weather_file, info, row_counter, csv_output)
                                    csv_written.add(idf_name)
                                    row_counter += 1
                        
                        # Don't handle COMPLETED messages here - let the next section do that
                        elif message_type != "COMPLETED":
                            update_queue.put(message)
                
                except queue.Empty:
                    pass
                
                # Check for completed processes from the completion queue
                completed_names = []
                try:
                    while True:
                        completed_name = completed_queue.get_nowait()
                        if completed_name:
                            completed_names.append(completed_name)
                except queue.Empty:
                    pass
                
                # Also check for COMPLETED messages in the update queue
                try:
                    while True:
                        message = update_queue.get_nowait()
                        if message[0] == "COMPLETED":
                            completed_name = message[1]
                            if completed_name not in completed_names:
                                completed_names.append(completed_name)
                        else:
                            update_queue.put(message)
                except queue.Empty:
                    pass
                
                # Process all COMPLETED signals
                for name in completed_names:
                    if name in active_processes:
                        process_info = active_processes[name]
                        process = process_info['process']
                        
                        # Try to terminate/cleanup the process
                        try:
                            if process.is_alive():
                                process.terminate()
                                process.join(timeout=0.5)
                        except:
                            pass
                        
                        # Write to CSV if the simulation has completed or failed and hasn't been written yet
                        if name in status_tracker.simulations and name not in csv_written and csv_output:
                            info = status_tracker.simulations[name]
                            # Write to CSV no matter what the status is - we're capturing completion
                            add_simulation_to_csv(process_info['file'], weather_file, info, row_counter, csv_output)
                            csv_written.add(name)
                            row_counter += 1
                        
                        # Remove from active processes
                        del active_processes[name]
                        completed_count += 1
                        
                        print(f"Completed simulation: {name}")
                        
                        # Start a new simulation if any are waiting
                        if waiting_files:
                            next_file = waiting_files.pop(0)
                            next_name = os.path.splitext(os.path.basename(next_file))[0]
                            
                            # Create and start the process
                            process = Process(
                                target=run_energyplus_simulation,
                                args=(next_file, weather_file, eplus_path, update_queue, completed_queue)
                            )
                            process.start()
                            
                            # Track the process
                            active_processes[next_name] = {
                                'process': process,
                                'start_time': time.time(),
                                'file': next_file
                            }
                            
                            print(f"Started new simulation: {next_name}")
                
                # Check for simulations that have changed status to Failed
                failed_names = []
                for name, info in status_tracker.simulations.items():
                    if name in active_processes and (info['status'] == 'Failed' or info['status'].startswith('Failed (')):
                        failed_names.append(name)
                
                # Process any newly failed simulations
                for name in failed_names:
                    if name in active_processes:
                        process_info = active_processes[name]
                        process = process_info['process']
                        
                        # Write to CSV if status has changed to Failed and hasn't been written yet
                        if name not in csv_written and csv_output:
                            info = status_tracker.simulations[name]
                            add_simulation_to_csv(process_info['file'], weather_file, info, row_counter, csv_output)
                            csv_written.add(name)
                            row_counter += 1
                        
                        print(f"Process for {name} has failed - terminating")
                        
                        # Try to terminate/cleanup the process
                        try:
                            if process.is_alive():
                                process.terminate()
                                process.join(timeout=0.5)
                        except:
                            pass
                        
                        # Remove from active processes
                        del active_processes[name]
                        completed_count += 1
                        
                        # Start a new simulation if any are waiting
                        if waiting_files:
                            next_file = waiting_files.pop(0)
                            next_name = os.path.splitext(os.path.basename(next_file))[0]
                            
                            # Create and start the process
                            process = Process(
                                target=run_energyplus_simulation,
                                args=(next_file, weather_file, eplus_path, update_queue, completed_queue)
                            )
                            process.start()
                            
                            # Track the process
                            active_processes[next_name] = {
                                'process': process,
                                'start_time': time.time(),
                                'file': next_file
                            }
                            
                            print(f"Started new simulation: {next_name}")
                
                # Periodic check for dead or completed processes (every 10 seconds)
                current_time = time.time()
                if current_time - last_check_time > 5:  # Reduced to 5 seconds for more frequent checks
                    # Check if any simulation with errors is still marked as Initializing instead of Failed
                    for name, info in status_tracker.simulations.items():
                        if name in active_processes and info['status'] == 'Initializing' and info['errors'] > 0:
                            # Force update to Failed
                            print(f"⚠️ Forcing status update for {name} from Initializing to Failed due to errors")
                            status_tracker.update_simulation(name, status='Failed', progress=100, cpu=0.0, memory=0.0)
                            
                            # Add to failed_names to be processed immediately
                            if name not in failed_names:
                                failed_names.append(name)
                    
                    # Scan active processes for any that have completed or failed
                    to_remove = []
                    for name, process_info in active_processes.items():
                        process = process_info['process']
                        
                        # Check if process is still alive
                        if not process.is_alive():
                            to_remove.append(name)
                            print(f"Process for {name} is no longer alive - marking completed")
                            
                            # Check if status is still Initializing but process is dead - mark as Failed
                            if name in status_tracker.simulations and status_tracker.simulations[name]['status'] == 'Initializing':
                                status_tracker.update_simulation(name, status='Failed (Process died)', progress=100, cpu=0.0, memory=0.0)
                            
                            # Write to CSV for dead processes if not already written
                            if name in status_tracker.simulations and name not in csv_written and csv_output:
                                info = status_tracker.simulations[name]
                                add_simulation_to_csv(process_info['file'], weather_file, info, row_counter, csv_output)
                                csv_written.add(name)
                                row_counter += 1
                        
                        # Check for excessively long-running simulations (1 hour)
                        if current_time - process_info['start_time'] > 3600:
                            if name not in to_remove:
                                to_remove.append(name)
                                print(f"Simulation {name} has been running for over 1 hour - marking as failed")
                                status_tracker.update_simulation(name, {
                                    'status': 'Failed (Timeout)',
                                    'progress': 100,
                                    'end_time': current_time,
                                    'cpu': 0.0,
                                    'memory': 0.0
                                })
                                
                                # Wait for status update to be processed
                                time.sleep(0.1)
                                
                                # Write to CSV for timed-out processes if not already written
                                if name in status_tracker.simulations and name not in csv_written and csv_output:
                                    info = status_tracker.simulations[name]
                                    add_simulation_to_csv(process_info['file'], weather_file, info, row_counter, csv_output)
                                    csv_written.add(name)
                                    row_counter += 1
                    
                    # Handle all identified processes
                    for name in to_remove:
                        if name in active_processes:
                            process_info = active_processes[name]
                            process = process_info['process']
                            
                            # Try to terminate/cleanup the process
                            try:
                                if process.is_alive():
                                    process.terminate()
                                    process.join(timeout=0.5)
                            except:
                                pass
                            
                            # Remove from active processes
                            del active_processes[name]
                            completed_count += 1
                            
                            # Start a new simulation if any are waiting
                            if waiting_files:
                                next_file = waiting_files.pop(0)
                                next_name = os.path.splitext(os.path.basename(next_file))[0]
                                
                                # Create and start the process
                                process = Process(
                                    target=run_energyplus_simulation,
                                    args=(next_file, weather_file, eplus_path, update_queue, completed_queue)
                                )
                                process.start()
                                
                                # Track the process
                                active_processes[next_name] = {
                                    'process': process,
                                    'start_time': time.time(),
                                    'file': next_file
                                }
                                
                                print(f"Started new simulation: {next_name}")
                    
                    # Update the check time
                    last_check_time = current_time
                
                # Update the UI components
                layout["stats"].update(status_tracker.get_table(completed_count, total))
                layout["logs"].update(status_tracker.get_logs_panel())
                
                # Short delay before next update
                time.sleep(0.25)
            
            # Final update
            layout["stats"].update(status_tracker.get_table(completed_count, total))
            layout["logs"].update(status_tracker.get_logs_panel())
    
    except KeyboardInterrupt:
        print("\nUser interrupted. Cleaning up...")
        # Terminate all active processes
        for process_info in active_processes.values():
            process_info['process'].terminate()
    except Exception as e:
        print(f"\nError in main loop: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up processes
        for process_info in active_processes.values():
            process = process_info['process']
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
        
        # Signal update thread to end
        try:
            update_queue.put("DONE")
        except:
            pass
        
        # Ensure all simulations are written to CSV
        if csv_output:
            for idf_file in idf_files:
                idf_name = os.path.splitext(os.path.basename(idf_file))[0]
                if idf_name not in csv_written and idf_name in status_tracker.simulations:
                    info = status_tracker.simulations[idf_name]
                    add_simulation_to_csv(idf_file, weather_file, info, len(csv_written), csv_output)
                    csv_written.add(idf_name)
    
    # Print final summary
    print("\nAll simulations completed!")
    print("Output files have been saved to the original directory.")
    
    print("\nSimulation Summary:")
    print("-" * 80)
    for idf_file in idf_files:
        idf_name = os.path.splitext(os.path.basename(idf_file))[0]
        if idf_name in status_tracker.simulations:
            info = status_tracker.simulations[idf_name]
            runtime = 0
            if info['start_time'] and info['end_time']:
                runtime = info['end_time'] - info['start_time']
            runtime_str = f"{int(runtime // 60)}m {int(runtime % 60)}s"
            print(f"{idf_name}: {info['status']} in {runtime_str} - Warnings: {info['warnings']}, Errors: {info['errors']}")
    print("-" * 80)
    
    # Check for output files
    print("\nOutput files created:")
    for idf_file in idf_files:
        idf_name = os.path.splitext(os.path.basename(idf_file))[0]
        print(f"Files for {idf_name}:")
        found_files = False
        for file in os.listdir(current_dir):
            if file.startswith(idf_name) and not file.endswith('.idf') and not file.endswith('.end'):
                print(f"  - {file}")
                found_files = True
        if not found_files:
            print("  No output files found")
            
    print(f"\nResults CSV has been saved to: {csv_output} ({len(csv_written)} simulations recorded)")

def main():
    parser = argparse.ArgumentParser(description='Run EnergyPlus simulations in parallel with Rich UI')
    parser.add_argument('--eplus', type=str, default=DEFAULT_EPLUS_PATH, help='Path to EnergyPlus installation directory')
    parser.add_argument('--max-workers', type=int, default=None, help='Maximum number of parallel simulations')
    parser.add_argument('--csv', type=str, default="simulation_results.csv", help='Output CSV file for simulation results')
    
    args = parser.parse_args()
    
    run_simulations(args.eplus, args.max_workers, args.csv)

if __name__ == "__main__":
    main()
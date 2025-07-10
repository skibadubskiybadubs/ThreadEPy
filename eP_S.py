"""
 sim
 core simulation logic and parallel execution
"""

import os
import sys
import time
import glob
import csv
import queue
import shutil
import tempfile
import subprocess
import threading
import traceback
import multiprocessing
from multiprocessing import Manager, Process

from eP_D import import_dependencies
from eP_T import SimulationStatus, process_monitor, update_process
from eP_U import add_simulation_to_csv, resolve_csv_path

# Import Rich components
rich_components = import_dependencies()
Live = rich_components['Live']
Layout = rich_components['Layout']
psutil = rich_components['psutil']


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
    # (same as IDF file directory)
    try: 
        output_dir = os.path.dirname(idf_file)
    except: 
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


def run_simulations(idf_files=None, weather_file=None, eplus_path=None, max_workers=None, csv_output="simulation_results.csv"):
    """
    Run EnergyPlus simulations in parallel with a Rich UI showing progress.
    
    Args:
        idf_files (list): List of IDF file paths
        weather_file (str): Path to the EPW weather file  
        eplus_path (str): Path to the EnergyPlus installation directory
        max_workers (int): Maximum number of parallel simulations
        csv_output (str): Name of the CSV output file for results summary
    """
    if not idf_files:
        print("No IDF files provided")
        return
        
    if not weather_file or not os.path.exists(weather_file):
        print("Invalid weather file provided")
        return
    
    # Resolve the CSV output path
    csv_output = resolve_csv_path(csv_output, idf_files)
    
    # Initialize CSV file with headers
    if csv_output:
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

    row_counter = 0 # For CSV row numbering
    
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
                        
                        message_type = message[0]
                        
                        if message_type == "INFO":
                            print(message[1])
                        
                        elif message_type == "UPDATE":
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
                
                # Periodic check for dead or completed processes (every 5 seconds)
                current_time = time.time()
                if current_time - last_check_time > 5:
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
    
    # Final summary
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
        try: 
            output_dir = os.path.dirname(idf_file)
        except: 
            output_dir = os.getcwd()
        print(f"Files for {idf_name}:")
        found_files = False
        for file in os.listdir(output_dir):
            if file.startswith(idf_name) and not file.endswith('.idf') and not file.endswith('.end'):
                print(f"  - {file}")
                found_files = True
        if not found_files:
            print("  No output files found")
            
    print(f"\nResults CSV has been saved to: {csv_output} ({len(csv_written)} simulations recorded)")
    
    # Keep console open for user to see results
    input("\nPress Enter to exit...")
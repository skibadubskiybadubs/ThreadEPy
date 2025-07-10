"""
 status_tracker
 process monitoring
"""

import time
import threading
import queue
from eP_D import import_dependencies

# Import Rich components
rich_components = import_dependencies()
Table = rich_components['Table']
Panel = rich_components['Panel']
Columns = rich_components['Columns']
Text = rich_components['Text']
box = rich_components['box']
psutil = rich_components['psutil']


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
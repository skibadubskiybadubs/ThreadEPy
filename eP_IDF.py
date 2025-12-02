"""
IDF Object Manager
Handles dynamic parsing of EnergyPlus IDD schema, IDF object injection, and restoration.
Supports any EnergyPlus version by reading the OutputControl:Files structure from the IDD file.
"""

import os
import re


class IDDSchemaParser:
    """Parser for EnergyPlus IDD (Input Data Dictionary) files."""

    def __init__(self, eplus_path):
        """
        Initialize IDD parser with path to EnergyPlus installation.

        Args:
            eplus_path (str): Path to EnergyPlus installation directory
        """
        self.eplus_path = eplus_path
        self.idd_path = os.path.join(eplus_path, "Energy+.idd")
        self.output_control_fields = None
        self.output_control_field_names = None

    def parse_output_control_files(self):
        """
        Parse the OutputControl:Files object definition from the IDD file.

        Returns:
            tuple: (field_names: list, field_count: int) or (None, None) if not found
        """
        if not os.path.exists(self.idd_path):
            print(f"Warning: IDD file not found at {self.idd_path}")
            return None, None

        try:
            with open(self.idd_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Find the OutputControl:Files object definition
            # IDD format:
            # OutputControl:Files,
            #   \memo Controls which output files are produced
            #   A1 , \field Output CSV
            #        \type choice
            #   A2 , \field Output MTR
            #        ...

            # Pattern to match the entire OutputControl:Files block
            pattern = r'OutputControl:Files,\s*(.*?)(?=\n\s*\n|\n[A-Z])'
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

            if not match:
                print("Warning: OutputControl:Files not found in IDD")
                return None, None

            block = match.group(1)

            # Extract field names from \field lines
            field_pattern = r'\\field\s+([^\n]+)'
            field_matches = re.findall(field_pattern, block)

            # Clean up field names (remove trailing whitespace/comments)
            field_names = [name.strip() for name in field_matches]

            print(f"Parsed OutputControl:Files from IDD: {len(field_names)} fields")

            self.output_control_fields = field_names
            self.output_control_field_names = len(field_names)

            return field_names, len(field_names)

        except Exception as e:
            print(f"Error parsing IDD file: {e}")
            return None, None

    def get_output_control_fields(self):
        """
        Get the OutputControl:Files field names, parsing IDD if not already done.

        Returns:
            list: Field names for OutputControl:Files
        """
        if self.output_control_fields is None:
            self.parse_output_control_files()

        return self.output_control_fields or []


class IDFObjectManager:
    """Manager for IDF object injection and restoration."""

    def __init__(self, eplus_path):
        """
        Initialize IDF object manager.

        Args:
            eplus_path (str): Path to EnergyPlus installation directory
        """
        self.idd_parser = IDDSchemaParser(eplus_path)
        self.field_names = self.idd_parser.get_output_control_fields()

        # Backup registry: {idf_file_path: (had_controls, original_text)}
        self.backup_registry = {}

    def backup_output_controls(self, idf_file):
        """
        Backup the existing OutputControl:Files object from an IDF file.

        Args:
            idf_file (str): Path to IDF file

        Returns:
            tuple: (had_controls: bool, original_text: str or None)
        """
        try:
            idf_file = os.path.abspath(idf_file)

            with open(idf_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Dynamic pattern that matches ANY OutputControl:Files regardless of parameter count
            # Strategy: Match "OutputControl:Files," followed by any content until we find
            # a line that ends with semicolon (the last parameter), including the comment after it
            # Pattern breakdown:
            #   OutputControl:Files\s*,  - Header with optional whitespace
            #   (?:.*?\n)*?              - Any number of lines (non-greedy)
            #   .*?;                     - Final line ending with semicolon (non-greedy)
            #   (?:\s*!-[^\n]*)?         - Optional comment after semicolon
            pattern = r'OutputControl:Files\s*,(?:.*?\n)*?.*?;(?:\s*!-[^\n]*)?'
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

            if match:
                full_text = match.group(0)
                backup_info = (True, full_text)
                print(f"Backed up existing OutputControl:Files from {os.path.basename(idf_file)}")
            else:
                backup_info = (False, None)

            # Register in backup registry
            self.backup_registry[idf_file] = backup_info

            return backup_info

        except Exception as e:
            print(f"Error backing up OutputControl:Files from {idf_file}: {e}")
            return (False, None)

    def inject_output_controls(self, idf_file, output_mode, output_files=None):
        """
        Inject or replace OutputControl:Files object in IDF file.

        Args:
            idf_file (str): Path to IDF file to modify
            output_mode (str): "Default", "Pristine", or "Custom"
            output_files (list): List of field names to set to "Yes" (with "Output " prefix)

        Returns:
            None (modifies file in-place)
        """
        # If Pristine mode, do nothing
        if output_mode == "Pristine":
            return

        if output_files is None:
            output_files = []

        if not self.field_names:
            print(f"Warning: No OutputControl:Files schema found, cannot inject")
            return

        try:
            with open(idf_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Build OutputControl:Files object based on parsed IDD schema
            params = []
            for i, field_name in enumerate(self.field_names):
                # Determine value based on mode
                if output_mode == "Default":
                    # Default mode: CSV and Tabular only
                    value = "Yes" if field_name in ['Output CSV', 'Output Tabular'] else "No"
                elif output_mode == "Custom":
                    # Custom mode: check if field is in selected list
                    value = "Yes" if field_name in output_files else "No"
                else:
                    value = "No"

                # Last parameter uses semicolon, others use comma
                is_last = (i == len(self.field_names) - 1)
                separator = ";" if is_last else ","

                # Format: 4 spaces + value + separator + padding + comment
                params.append(f"    {value}{separator:<25}!- {field_name}")

            output_control = "OutputControl:Files,\n" + "\n".join(params)

            # Check if OutputControl:Files already exists using dynamic pattern
            # Same pattern as backup: matches any OutputControl:Files regardless of parameter count
            pattern = r'OutputControl:Files\s*,(?:.*?\n)*?.*?;(?:\s*!-[^\n]*)?'
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

            if match:
                # Replace existing OutputControl:Files
                new_content = content[:match.start()] + output_control + content[match.end():]
            else:
                # Append at end of file
                content = content.rstrip()
                new_content = content + "\n\n" + output_control + "\n"

            # Write modified content back
            with open(idf_file, 'w', encoding='utf-8') as f:
                f.write(new_content)

            print(f"Injected OutputControl:Files ({output_mode} mode) into {os.path.basename(idf_file)}")

        except Exception as e:
            print(f"Error injecting OutputControl:Files into {idf_file}: {e}")

    def restore_output_controls(self, idf_file, had_controls, original_text):
        """
        Restore the original OutputControl:Files state in IDF file.

        Args:
            idf_file (str): Path to IDF file
            had_controls (bool): Whether file originally had OutputControl:Files
            original_text (str): Original OutputControl:Files text (or None)

        Returns:
            None (modifies file in-place)
        """
        try:
            idf_file = os.path.abspath(idf_file)

            with open(idf_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Dynamic pattern to find ANY OutputControl:Files block
            # Same pattern as backup and inject: matches any OutputControl:Files regardless of parameter count
            pattern = r'OutputControl:Files\s*,(?:.*?\n)*?.*?;(?:\s*!-[^\n]*)?'
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)

            if not match:
                print(f"Warning: No OutputControl:Files found to restore in {os.path.basename(idf_file)}")
                return

            if had_controls and original_text:
                # Restore the original OutputControl:Files
                new_content = content[:match.start()] + original_text + content[match.end():]
                print(f"Restored original OutputControl:Files in {os.path.basename(idf_file)}")
            elif not had_controls:
                # Remove the injected OutputControl:Files
                # Also remove blank lines before it if they exist
                start = match.start()
                # Check if there are blank lines before the match
                if start >= 2 and content[start-2:start] == '\n\n':
                    start -= 2
                new_content = content[:start] + content[match.end():]
                print(f"Removed injected OutputControl:Files from {os.path.basename(idf_file)}")
            else:
                # Nothing to do
                return

            # Write restored content back
            with open(idf_file, 'w', encoding='utf-8') as f:
                f.write(new_content)

            # Remove from registry after successful restoration
            if idf_file in self.backup_registry:
                del self.backup_registry[idf_file]

        except Exception as e:
            print(f"Error restoring OutputControl:Files in {idf_file}: {e}")

    def restore_all_idf_files(self):
        """
        Restore all IDF files that were modified during simulation.

        Returns:
            int: Number of files restored
        """
        restored_count = 0
        idf_files = list(self.backup_registry.keys())

        for idf_file in idf_files:
            try:
                had_controls, original_text = self.backup_registry[idf_file]
                self.restore_output_controls(idf_file, had_controls, original_text)
                restored_count += 1
            except Exception as e:
                print(f"Error restoring {idf_file}: {e}")

        return restored_count

    def clear_backup_registry(self):
        """Clear the backup registry without restoring files."""
        self.backup_registry.clear()

    def get_field_names(self):
        """
        Get the list of OutputControl:Files field names.

        Returns:
            list: Field names (e.g., ['Output CSV', 'Output MTR', ...])
        """
        return self.field_names.copy() if self.field_names else []

    def get_short_field_names(self):
        """
        Get short field names without "Output " prefix for GUI display.

        Returns:
            list: Short field names (e.g., ['CSV', 'MTR', ...])
        """
        if not self.field_names:
            return []

        short_names = []
        for name in self.field_names:
            # Remove "Output " prefix if present
            if name.startswith("Output "):
                short_names.append(name[7:])  # Remove "Output " (7 characters)
            else:
                short_names.append(name)

        return short_names


# Global IDF manager instance (will be initialized when EnergyPlus path is known)
_global_idf_manager = None


def initialize_idf_manager(eplus_path):
    """
    Initialize the global IDF manager with the specified EnergyPlus path.

    Args:
        eplus_path (str): Path to EnergyPlus installation directory

    Returns:
        IDFObjectManager: The initialized manager
    """
    global _global_idf_manager
    _global_idf_manager = IDFObjectManager(eplus_path)
    return _global_idf_manager


def get_idf_manager():
    """
    Get the global IDF manager instance.

    Returns:
        IDFObjectManager or None: The global manager, or None if not initialized
    """
    return _global_idf_manager

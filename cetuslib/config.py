"""Configuration management for Cetus."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional


__all__ = ['ConfigManager']


class ConfigManager:
    """Manage application settings using XDG Base Directory on Linux and APPDATA on Windows"""

    def __init__(self) -> None:
        if sys.platform == 'win32':
            appdata = os.environ.get('APPDATA')
            if not appdata:
                appdata = os.path.join(Path.home(), 'AppData', 'Roaming')
            self.config_dir = os.path.join(appdata, 'Cetus')
        else:
            # Get XDG config directory (defaults to ~/.config)
            xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
            if not xdg_config_home:
                xdg_config_home = os.path.join(Path.home(), '.config')
            self.config_dir = os.path.join(xdg_config_home, 'cetus')

        # Create cetus config directory
        os.makedirs(self.config_dir, exist_ok=True)

        # Config file path
        self.config_file = os.path.join(self.config_dir, 'settings.json')

        # Default settings
        self.defaults = {
            # Serial settings
            'port_type': 'USB',
            'baudrate': '9600',
            'databits': '8',
            'parity': 'None',
            'stopbits': '1',
            'flow': 'None',
            'vendor': 'Default',
            # Connection mode
            'connection_mode': 'serial',
            # SSH settings
            'ssh_host': '',
            'ssh_port': '22',
            'ssh_username': '',
            'ssh_auth_method': 'password',
            'ssh_key_path': '',
            'ssh_profiles': '[]',
            'ssh_rc_collapsed': False,
            # Serial profiles
            'serial_profiles': '[]',
            # Terminal preference for Linux/native devices
            'terminal_mode': 'auto',
            # Vuln scanner
            'vuln_community_history': '[]',
            # Theme settings
            'theme': 'light',
        }

        # Load settings
        self.settings = self.load()

    def load(self) -> dict[str, Any]:
        """Load settings from file, return defaults if file doesn't exist"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults (in case new settings were added)
                    return {**self.defaults, **loaded}
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load settings: {e}")
                return self.defaults.copy()
        return self.defaults.copy()

    def save(self) -> None:
        """Save settings to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Warning: Could not save settings: {e}")

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and save"""
        self.settings[key] = value
        self.save()

    def get(self, key: str) -> Any:
        """Get a setting value"""
        return self.settings.get(key, self.defaults.get(key))

    def get_ssh_profiles(self) -> list[dict[str, Any]]:
        """Get list of saved SSH connection profiles"""
        profiles_json = self.settings.get('ssh_profiles', '[]')
        try:
            return json.loads(profiles_json)
        except json.JSONDecodeError:
            return []

    def save_ssh_profile(self, name: str, host: str, port: str, username: str, auth_method: str, key_path: str = '', protocol: str = 'SSH', vendor: str = 'Default', group: str = 'Default', password: str = '', terminal_mode: str = 'auto') -> None:
        """Save an SSH connection profile"""
        profiles = self.get_ssh_profiles()
        entry = {
            'name': name, 'host': host, 'port': port,
            'username': username, 'auth_method': auth_method,
            'key_path': key_path, 'protocol': protocol,
            'vendor': vendor, 'group': group,
            'terminal_mode': terminal_mode,
        }
        if password:
            import base64
            entry['password'] = base64.b64encode(password.encode()).decode()
        # Update existing or add new
        for i, p in enumerate(profiles):
            if p.get('name') == name:
                profiles[i] = entry
                break
        else:
            profiles.append(entry)
        self.set('ssh_profiles', json.dumps(profiles))

    def delete_ssh_profile(self, name: str) -> None:
        """Delete an SSH connection profile"""
        profiles = [p for p in self.get_ssh_profiles() if p.get('name') != name]
        self.set('ssh_profiles', json.dumps(profiles))

    def get_vuln_community_history(self) -> list[str]:
        """Get list of previously used SNMP community strings (most recent first)."""
        try:
            return json.loads(self.settings.get('vuln_community_history', '[]'))
        except Exception:
            return []

    def add_vuln_community(self, community: str) -> None:
        """Prepend community to history, keeping at most 20 unique entries."""
        history = self.get_vuln_community_history()
        if community in history:
            history.remove(community)
        history.insert(0, community)
        self.set('vuln_community_history', json.dumps(history[:20]))

    def get_snmp_ip_community(self, ip: str) -> Optional[str]:
        """Return the last working SNMP community for a given IP, or None."""
        try:
            mapping = json.loads(self.settings.get('snmp_ip_community_map', '{}'))
            return mapping.get(ip)
        except Exception:
            return None

    def set_snmp_ip_community(self, ip: str, community: str) -> None:
        """Save the last working SNMP community for a given IP."""
        try:
            mapping = json.loads(self.settings.get('snmp_ip_community_map', '{}'))
        except Exception:
            mapping = {}
        mapping[ip] = community
        self.set('snmp_ip_community_map', json.dumps(mapping))

    def get_serial_profiles(self) -> list[dict[str, Any]]:
        """Get list of saved serial connection profiles"""
        profiles_json = self.settings.get('serial_profiles', '[]')
        try:
            return json.loads(profiles_json)
        except json.JSONDecodeError:
            return []

    def save_serial_profile(self, name: str, port: str, baudrate: str, databits: str, parity: str, stopbits: str, flow: str, vendor: str = 'Default', group: str = 'Default', terminal_mode: str = 'auto') -> None:
        """Save a serial connection profile"""
        profiles = self.get_serial_profiles()
        entry = {
            'name': name, 'port': port, 'baudrate': baudrate,
            'databits': databits, 'parity': parity,
            'stopbits': stopbits, 'flow': flow,
            'vendor': vendor, 'group': group,
            'terminal_mode': terminal_mode,
        }
        for i, p in enumerate(profiles):
            if p.get('name') == name:
                profiles[i] = entry
                break
        else:
            profiles.append(entry)
        self.set('serial_profiles', json.dumps(profiles))

    def delete_serial_profile(self, name: str) -> None:
        """Delete a serial connection profile"""
        profiles = [p for p in self.get_serial_profiles() if p.get('name') != name]
        self.set('serial_profiles', json.dumps(profiles))

    def get_quick_notes(self) -> str:
        """Return the shared quick notes text."""
        return self.get('quick_notes') or ''

    def set_quick_notes(self, text: str) -> None:
        """Persist the shared quick notes text."""
        self.set('quick_notes', text)

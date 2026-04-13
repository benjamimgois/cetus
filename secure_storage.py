"""
Secure storage module for OpenGrid credentials
Provides encryption for sensitive data like passwords
"""
import os
import json
import base64
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


class SecureStorage:
    """Handle secure storage of sensitive credentials"""
    
    def __init__(self, config_dir=None):
        if config_dir is None:
            # Use XDG config directory
            xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
            if not xdg_config_home:
                xdg_config_home = os.path.join(Path.home(), '.config')
            config_dir = os.path.join(xdg_config_home, 'opengrid')
        
        self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Key file for encryption
        self.key_file = os.path.join(self.config_dir, '.key')
        self._key = None
        
    def _get_or_create_key(self):
        """Get or create encryption key"""
        if self._key is not None:
            return self._key
            
        if os.path.exists(self.key_file):
            try:
                with open(self.key_file, 'rb') as f:
                    key_data = f.read()
                if len(key_data) == 44:  # Fernet key size
                    self._key = key_data
                    return self._key
            except Exception:
                pass  # Fall through to create new key
        
        # Generate new key
        key = Fernet.generate_key()
        try:
            with open(self.key_file, 'wb') as f:
                f.write(key)
            # Set restrictive permissions
            os.chmod(self.key_file, 0o600)
            self._key = key
            return self._key
        except Exception:
            # If we can't save key, generate ephemeral key (not persistent)
            self._key = Fernet.generate_key()
            return self._key
    
    def _get_cipher(self):
        """Get Fernet cipher instance"""
        if not CRYPTOGRAPHY_AVAILABLE:
            return None
        key = self._get_or_create_key()
        return Fernet(key)
    
    def encrypt(self, data):
        """Encrypt sensitive data"""
        if not CRYPTOGRAPHY_AVAILABLE:
            # Fallback to base64 with obfuscation (not secure but better than plain)
            return base64.b64encode(data.encode()).decode()
        
        try:
            cipher = self._get_cipher()
            encrypted = cipher.encrypt(data.encode())
            return base64.b64encode(encrypted).decode()
        except Exception:
            # Fallback if encryption fails
            return base64.b64encode(data.encode()).decode()
    
    def decrypt(self, encrypted_data):
        """Decrypt sensitive data"""
        if not encrypted_data:
            return ""
            
        if not CRYPTOGRAPHY_AVAILABLE:
            # Fallback decoding
            try:
                return base64.b64decode(encrypted_data.encode()).decode()
            except Exception:
                return encrypted_data  # Return as-is if decoding fails
        
        try:
            cipher = self._get_cipher()
            decoded = base64.b64decode(encrypted_data.encode())
            decrypted = cipher.decrypt(decoded)
            return decrypted.decode()
        except Exception:
            # If decryption fails, try fallback
            try:
                return base64.b64decode(encrypted_data.encode()).decode()
            except Exception:
                return encrypted_data  # Return as-is if all fails


# Global instance for backward compatibility
_secure_storage = None

def get_secure_storage():
    """Get global secure storage instance"""
    global _secure_storage
    if _secure_storage is None:
        _secure_storage = SecureStorage()
    return _secure_storage

def encrypt_password(password):
    """Encrypt a password for storage"""
    return get_secure_storage().encrypt(password)

def decrypt_password(encrypted_password):
    """Decrypt a password from storage"""
    return get_secure_storage().decrypt(encrypted_password)
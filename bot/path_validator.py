"""
NIJA Path Validation Utility

Security utility for validating and sanitizing file paths to prevent
path traversal attacks and other file system vulnerabilities.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import os
import re
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PathValidator:
    """
    Validates and sanitizes file paths to prevent security vulnerabilities.
    
    Prevents:
    - Path traversal attacks (../, .., etc.)
    - Absolute path injection
    - Null byte injection
    - Special character exploits
    """
    
    # Disallowed patterns in paths
    DANGEROUS_PATTERNS = [
        r'\.\.',          # Parent directory references
        r'~',             # Home directory references
        r'^\/',           # Absolute paths (Unix)
        r'^[A-Za-z]:',    # Absolute paths (Windows)
        r'\x00',          # Null bytes
        r'[<>:"|?*]',     # Windows reserved characters
    ]
    
    # Allowed characters in directory/file names
    SAFE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
    
    @classmethod
    def validate_directory_name(cls, directory: str) -> bool:
        """
        Validate that a directory name is safe.
        
        Args:
            directory: Directory name to validate
            
        Returns:
            True if safe, False otherwise
        """
        if not directory or not isinstance(directory, str):
            return False
        
        # Check for dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, directory):
                logger.warning(f"Dangerous pattern detected in directory: {directory}")
                return False
        
        # Check if name contains only safe characters
        if not cls.SAFE_NAME_PATTERN.match(directory):
            logger.warning(f"Invalid characters in directory: {directory}")
            return False
        
        return True
    
    @classmethod
    def sanitize_directory_name(cls, directory: str) -> str:
        """
        Sanitize a directory name by removing unsafe characters.
        
        Args:
            directory: Directory name to sanitize
            
        Returns:
            Sanitized directory name
        """
        if not directory or not isinstance(directory, str):
            return "reports"
        
        # Remove any path separators
        directory = directory.replace('/', '_').replace('\\', '_')
        
        # Remove parent directory references
        directory = directory.replace('..', '')
        
        # Remove special characters, keep only alphanumeric, underscore, hyphen, dot
        directory = re.sub(r'[^a-zA-Z0-9_\-\.]', '', directory)
        
        # Ensure it's not empty after sanitization
        if not directory:
            directory = "reports"
        
        return directory
    
    @classmethod
    def secure_path(cls, base_dir: str, user_path: str, allow_subdirs: bool = True) -> Path:
        """
        Create a secure path by validating it's within the base directory.
        
        Args:
            base_dir: Base directory that all paths must be within
            user_path: User-provided path component
            allow_subdirs: Whether to allow subdirectory creation
            
        Returns:
            Validated Path object
            
        Raises:
            ValueError: If the path would escape the base directory
        """
        # Sanitize the user path
        if allow_subdirs:
            # Split into components and sanitize each
            parts = user_path.split(os.sep)
            sanitized_parts = [cls.sanitize_directory_name(part) for part in parts if part]
            sanitized_path = os.path.join(*sanitized_parts) if sanitized_parts else "reports"
        else:
            sanitized_path = cls.sanitize_directory_name(user_path)
        
        # Create the full path
        base = Path(base_dir).resolve()
        target = (base / sanitized_path).resolve()
        
        # Ensure the target is within base directory
        try:
            target.relative_to(base)
        except ValueError:
            logger.error(f"Path traversal attempt: {user_path} would escape {base_dir}")
            raise ValueError(f"Invalid path: {user_path} is outside allowed directory")
        
        return target
    
    @classmethod
    def validate_filename(cls, filename: str) -> bool:
        """
        Validate that a filename is safe.
        
        Args:
            filename: Filename to validate
            
        Returns:
            True if safe, False otherwise
        """
        if not filename or not isinstance(filename, str):
            return False
        
        # Check for dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, filename):
                logger.warning(f"Dangerous pattern detected in filename: {filename}")
                return False
        
        # Check if name contains only safe characters
        # Allow dots for extensions
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
            logger.warning(f"Invalid characters in filename: {filename}")
            return False
        
        # Ensure it has an extension
        if '.' not in filename:
            logger.warning(f"Filename missing extension: {filename}")
            return False
        
        return True
    
    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """
        Sanitize a filename by removing unsafe characters.
        
        Args:
            filename: Filename to sanitize
            
        Returns:
            Sanitized filename
        """
        if not filename or not isinstance(filename, str):
            return "report.json"
        
        # Remove path components
        filename = os.path.basename(filename)
        
        # Remove dangerous characters
        filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)
        
        # Ensure it has an extension
        if '.' not in filename:
            filename = filename + '.json'
        
        return filename

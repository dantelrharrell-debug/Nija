"""
Path Validation Utility for NIJA Trading Bot

This module provides security utilities to prevent path traversal attacks
and ensure safe filesystem operations when handling user-provided paths.
NIJA Path Validation Utility

Security utility for validating and sanitizing file paths to prevent
path traversal attacks and other file system vulnerabilities.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import os
import re
from pathlib import Path
from typing import Optional, Union
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PathValidationError(Exception):
    """Raised when a path fails security validation"""
    pass


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing or replacing dangerous characters.

    Args:
        filename: The filename to sanitize

    Returns:
        Sanitized filename safe for filesystem use

    Raises:
        PathValidationError: If filename is invalid or dangerous
    """
    if not filename or not isinstance(filename, str):
        raise PathValidationError("Filename must be a non-empty string")

    # Remove any path separators to prevent directory traversal
    filename = filename.replace('/', '_').replace('\\', '_')
    
    # Remove parent directory references (../ and ..\) - SECURITY CRITICAL
    filename = filename.replace('..', '')

    # Remove null bytes
    filename = filename.replace('\0', '')

    # Remove control characters
    filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)

    # Remove or replace filesystem-unsafe characters on Windows/Unix
    unsafe_chars = ['<', '>', ':', '"', '|', '?', '*']
    for char in unsafe_chars:
        filename = filename.replace(char, '_')

    # Remove leading/trailing dots and spaces (Windows issue)
    filename = filename.strip('. ')

    # Prevent reserved Windows names
    reserved_names = [
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    ]
    name_without_ext = os.path.splitext(filename)[0].upper()
    if name_without_ext in reserved_names:
        filename = f"_{filename}"

    # Ensure we still have a valid filename
    if not filename or filename in ['.', '..']:
        raise PathValidationError(f"Invalid filename after sanitization: {filename}")

    # Limit length (most filesystems support 255, leave some margin)
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:200-len(ext)] + ext

    return filename


def validate_output_path(
    base_dir: Union[str, Path],
    user_provided_path: Union[str, Path],
    allow_create: bool = True
) -> Path:
    """
    Validate that a user-provided path is safe and within the expected base directory.

    This function prevents path traversal attacks by ensuring the resolved path
    is within the base directory.

    Args:
        base_dir: The base directory that the path must be within
        user_provided_path: The user-provided path to validate
        allow_create: Whether to create the directory if it doesn't exist

    Returns:
        Validated Path object

    Raises:
        PathValidationError: If the path is invalid or outside base_dir
    """
    # Convert to Path objects
    base_dir = Path(base_dir)
    user_provided_path = Path(user_provided_path)

    # Resolve base_dir to absolute path
    try:
        base_dir = base_dir.resolve()
    except (OSError, RuntimeError) as e:
        raise PathValidationError(f"Invalid base directory: {e}")

    # Construct the target path
    if user_provided_path.is_absolute():
        # For absolute paths, verify they're within base_dir
        try:
            target_path = user_provided_path.resolve()
        except (OSError, RuntimeError) as e:
            raise PathValidationError(f"Invalid target path: {e}")
    else:
        # For relative paths, join with base_dir
        target_path = base_dir / user_provided_path
        try:
            target_path = target_path.resolve()
        except (OSError, RuntimeError) as e:
            raise PathValidationError(f"Invalid target path: {e}")

    # Security check: Ensure resolved path is within base_dir
    try:
        target_path.relative_to(base_dir)
    except ValueError:
        logger.warning(
            f"Path traversal attempt detected: {user_provided_path} "
            f"resolves outside base directory {base_dir}"
        )
        raise PathValidationError(
            f"Path is outside allowed directory. "
            f"Provided: {user_provided_path}, Base: {base_dir}"
        )

    # Create directory if allowed and needed
    if allow_create:
        try:
            target_path.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            raise PathValidationError(f"Cannot create directory: {e}")

    return target_path


def validate_file_path(
    base_dir: Union[str, Path],
    filename: str,
    subdirectory: Optional[str] = None
) -> Path:
    """
    Validate a file path for safe export operations.

    Args:
        base_dir: The base directory for file operations
        filename: The filename (will be sanitized)
        subdirectory: Optional subdirectory within base_dir

    Returns:
        Validated Path object for the file

    Raises:
        PathValidationError: If validation fails
    """
    # Sanitize the filename
    safe_filename = sanitize_filename(filename)

    # Build the directory path
    if subdirectory:
        dir_path = validate_output_path(base_dir, subdirectory, allow_create=True)
    else:
        dir_path = validate_output_path(base_dir, ".", allow_create=True)

    # Construct final file path
    file_path = dir_path / safe_filename

    # One final check that the file path is within base_dir
    try:
        file_path.resolve().relative_to(Path(base_dir).resolve())
    except ValueError:
        raise PathValidationError(
            f"File path validation failed: {file_path} is outside {base_dir}"
        )

    return file_path
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

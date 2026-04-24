"""
Safe Path Resolver - Reusable Security Component

Centralized path security with runtime metrics and attack detection.
Provides a single point of control for all file path operations.

Features:
    - Path traversal prevention
    - Runtime security metrics tracking
    - Attack detection and logging
    - Security badge generation for CI
    - Comprehensive path validation

Author: NIJA Trading Systems
Date: January 31, 2026
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass, asdict
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class SecurityMetrics:
    """Track runtime security metrics"""
    total_validations: int = 0
    successful_validations: int = 0
    blocked_attacks: int = 0
    sanitizations_performed: int = 0
    
    # Attack type counters
    path_traversal_attempts: int = 0
    absolute_path_attempts: int = 0
    null_byte_attempts: int = 0
    special_char_attempts: int = 0
    
    # Timestamps
    first_validation: Optional[str] = None
    last_validation: Optional[str] = None
    last_attack: Optional[str] = None
    
    # Attack examples (for monitoring)
    recent_attacks: List[str] = None
    
    def __post_init__(self):
        if self.recent_attacks is None:
            self.recent_attacks = []


class SafePathResolver:
    """
    Centralized, reusable path security resolver.
    
    Provides comprehensive protection against path traversal and file system attacks.
    Tracks runtime security metrics for monitoring and CI reporting.
    
    Thread-safe singleton implementation for consistent metrics across application.
    
    Example:
        >>> resolver = SafePathResolver.get_instance()
        >>> safe_path = resolver.resolve_safe_path("data/users", user_input)
        >>> metrics = resolver.get_metrics()
        >>> print(f"Blocked attacks: {metrics['blocked_attacks']}")
    """
    
    _instance = None
    _lock = Lock()
    
    # Security patterns
    DANGEROUS_PATTERNS = [
        (r'\.\.', 'path_traversal'),          # Parent directory references
        (r'~', 'home_directory'),              # Home directory references
        (r'^[/\\]', 'absolute_path'),          # Absolute paths (Unix/Windows)
        (r'^[A-Za-z]:', 'windows_drive'),      # Windows drive letters
        (r'\x00', 'null_byte'),                # Null bytes
        (r'[<>:"|?*]', 'special_chars'),       # Unsafe characters
    ]
    
    # Safe filename pattern
    SAFE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
    
    def __init__(self):
        """Initialize resolver with empty metrics"""
        self.metrics = SecurityMetrics()
        self.metrics_lock = Lock()
    
    @classmethod
    def get_instance(cls) -> 'SafePathResolver':
        """
        Get singleton instance of SafePathResolver.
        
        Thread-safe singleton pattern ensures consistent metrics
        across the entire application.
        
        Returns:
            Singleton SafePathResolver instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def _record_validation(self, success: bool, attack_type: Optional[str] = None,
                          original_input: Optional[str] = None):
        """
        Record validation attempt in metrics.
        
        Args:
            success: Whether validation succeeded
            attack_type: Type of attack detected (if any)
            original_input: Original input that triggered validation
        """
        with self.metrics_lock:
            now = datetime.utcnow().isoformat()
            
            self.metrics.total_validations += 1
            
            if self.metrics.first_validation is None:
                self.metrics.first_validation = now
            
            self.metrics.last_validation = now
            
            if success:
                self.metrics.successful_validations += 1
            else:
                self.metrics.blocked_attacks += 1
                self.metrics.last_attack = now
            
            # Record attack type even if sanitization succeeded
            if attack_type:
                if not success:
                    self.metrics.blocked_attacks += 1
                    self.metrics.last_attack = now
                
                # Track attack type
                if attack_type == 'path_traversal':
                    self.metrics.path_traversal_attempts += 1
                elif attack_type in ['absolute_path', 'windows_drive']:
                    self.metrics.absolute_path_attempts += 1
                elif attack_type == 'null_byte':
                    self.metrics.null_byte_attempts += 1
                elif attack_type == 'special_chars':
                    self.metrics.special_char_attempts += 1
                
                # Store recent attack examples (keep last 10)
                if original_input:
                    attack_record = f"{now}: {attack_type} - {original_input[:50]}"
                    self.metrics.recent_attacks.append(attack_record)
                    if len(self.metrics.recent_attacks) > 10:
                        self.metrics.recent_attacks.pop(0)
    
    def _detect_attack_patterns(self, user_input: str) -> Optional[str]:
        """
        Detect dangerous patterns in user input.
        
        Args:
            user_input: User-provided input to check
            
        Returns:
            Attack type if detected, None otherwise
        """
        for pattern, attack_type in self.DANGEROUS_PATTERNS:
            if re.search(pattern, user_input):
                return attack_type
        return None
    
    def sanitize_filename(self, filename: str, allow_empty: bool = False) -> str:
        """
        Sanitize a filename by removing dangerous characters.
        
        Security measures:
            - Remove path separators
            - Remove parent directory references (..)
            - Remove null bytes
            - Remove control characters
            - Remove unsafe filesystem characters
            - Validate against reserved Windows names
        
        Args:
            filename: Filename to sanitize
            allow_empty: If False, raises ValueError on empty result
            
        Returns:
            Sanitized filename
            
        Raises:
            ValueError: If filename is invalid or becomes empty after sanitization
        """
        if not filename or not isinstance(filename, str):
            self._record_validation(False, 'invalid_input', str(filename))
            raise ValueError("Filename must be a non-empty string")
        
        original = filename
        
        # Detect attack patterns before sanitization
        attack_type = self._detect_attack_patterns(filename)
        
        # Remove path separators
        filename = filename.replace('/', '_').replace('\\', '_')
        
        # Remove parent directory references - CRITICAL
        filename = filename.replace('..', '')
        
        # Remove null bytes
        filename = filename.replace('\0', '')
        
        # Remove control characters
        filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)
        
        # Remove unsafe characters
        unsafe_chars = ['<', '>', ':', '"', '|', '?', '*']
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        
        # Remove leading/trailing dots and spaces
        filename = filename.strip('. ')
        
        # Reserved Windows names
        reserved_names = [
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        ]
        name_without_ext = os.path.splitext(filename)[0].upper()
        if name_without_ext in reserved_names:
            filename = f"_{filename}"
        
        # Check if sanitization occurred
        if filename != original:
            with self.metrics_lock:
                self.metrics.sanitizations_performed += 1
        
        # Validate result
        if not filename or filename in ['.', '..']:
            if not allow_empty:
                self._record_validation(False, attack_type or 'invalid_result', original)
                raise ValueError(f"Invalid filename after sanitization: {original}")
        
        # Limit length
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[:200-len(ext)] + ext
        
        # Record successful sanitization
        if attack_type:
            logger.warning(f"Sanitized potentially malicious filename: {original} -> {filename}")
            self._record_validation(True, attack_type, original)
        else:
            self._record_validation(True)
        
        return filename
    
    def resolve_safe_path(
        self,
        base_dir: str,
        user_input: str,
        create_dirs: bool = False
    ) -> Path:
        """
        Resolve a safe path within a base directory.
        
        This is the primary method for secure path resolution.
        
        Security:
            - Sanitizes user input
            - Resolves to absolute path
            - Verifies containment within base_dir
            - Optionally creates directories safely
        
        Args:
            base_dir: Base directory that path must be within
            user_input: User-provided path component
            create_dirs: Whether to create directories if they don't exist
            
        Returns:
            Validated Path object
            
        Raises:
            ValueError: If path validation fails or escapes base_dir
            
        Example:
            >>> resolver = SafePathResolver.get_instance()
            >>> safe = resolver.resolve_safe_path("data/users", "../../../etc/passwd")
            ValueError: Path traversal detected
        """
        original_input = user_input
        
        # Sanitize the user input
        try:
            sanitized = self.sanitize_filename(user_input, allow_empty=True)
        except ValueError as e:
            logger.error(f"Path sanitization failed for: {original_input}")
            raise
        
        # Resolve base directory
        try:
            base_path = Path(base_dir).resolve()
        except (OSError, RuntimeError) as e:
            self._record_validation(False, 'invalid_base', base_dir)
            raise ValueError(f"Invalid base directory: {e}")
        
        # Construct target path
        if sanitized:
            target_path = base_path / sanitized
        else:
            target_path = base_path
        
        # Resolve to absolute path
        try:
            target_path = target_path.resolve()
        except (OSError, RuntimeError) as e:
            self._record_validation(False, 'resolution_error', original_input)
            raise ValueError(f"Cannot resolve path: {e}")
        
        # CRITICAL: Verify path is within base directory
        try:
            target_path.relative_to(base_path)
        except ValueError:
            logger.error(
                f"Path traversal blocked: {original_input} "
                f"would escape {base_dir}"
            )
            self._record_validation(False, 'path_traversal', original_input)
            raise ValueError(
                f"Security violation: Path '{original_input}' escapes base directory"
            )
        
        # Create directories if requested
        if create_dirs and not target_path.exists():
            try:
                target_path.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError) as e:
                self._record_validation(False, 'mkdir_error', str(target_path))
                raise ValueError(f"Cannot create directory: {e}")
        
        # Success
        self._record_validation(True)
        return target_path
    
    def resolve_safe_file_path(
        self,
        base_dir: str,
        filename: str,
        subdirectory: Optional[str] = None
    ) -> Path:
        """
        Resolve a safe file path for file operations.
        
        Args:
            base_dir: Base directory for file operations
            filename: Filename (will be sanitized)
            subdirectory: Optional subdirectory within base_dir
            
        Returns:
            Validated Path object for the file
            
        Raises:
            ValueError: If validation fails
        """
        # Sanitize filename
        safe_filename = self.sanitize_filename(filename)
        
        # Resolve directory
        if subdirectory:
            dir_path = self.resolve_safe_path(base_dir, subdirectory, create_dirs=True)
        else:
            dir_path = Path(base_dir).resolve()
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
        
        # Construct file path
        file_path = dir_path / safe_filename
        
        # Final containment check
        try:
            file_path.resolve().relative_to(Path(base_dir).resolve())
        except ValueError:
            self._record_validation(False, 'path_traversal', filename)
            raise ValueError(f"File path validation failed: {file_path}")
        
        return file_path
    
    def get_metrics(self) -> Dict:
        """
        Get current security metrics.
        
        Returns:
            Dictionary with security metrics
        """
        with self.metrics_lock:
            return {
                'total_validations': self.metrics.total_validations,
                'successful_validations': self.metrics.successful_validations,
                'blocked_attacks': self.metrics.blocked_attacks,
                'sanitizations_performed': self.metrics.sanitizations_performed,
                'attack_breakdown': {
                    'path_traversal': self.metrics.path_traversal_attempts,
                    'absolute_path': self.metrics.absolute_path_attempts,
                    'null_byte': self.metrics.null_byte_attempts,
                    'special_chars': self.metrics.special_char_attempts,
                },
                'timestamps': {
                    'first_validation': self.metrics.first_validation,
                    'last_validation': self.metrics.last_validation,
                    'last_attack': self.metrics.last_attack,
                },
                'recent_attacks': self.metrics.recent_attacks.copy(),
                'security_score': self._calculate_security_score()
            }
    
    def _calculate_security_score(self) -> float:
        """
        Calculate security score (0-100).
        
        100 = No attacks detected
        Lower scores indicate more attack attempts
        
        Returns:
            Security score from 0-100
        """
        if self.metrics.total_validations == 0:
            return 100.0
        
        success_rate = (
            self.metrics.successful_validations / 
            self.metrics.total_validations * 100
        )
        
        # Penalize systems with high attack rates
        attack_rate = (
            self.metrics.blocked_attacks / 
            self.metrics.total_validations
        )
        
        if attack_rate > 0.5:  # More than 50% attacks
            penalty = 20
        elif attack_rate > 0.2:  # More than 20% attacks
            penalty = 10
        else:
            penalty = 0
        
        return max(0, min(100, success_rate - penalty))
    
    def get_security_badge(self) -> str:
        """
        Get security badge for CI logs.
        
        Returns:
            Formatted security badge string
        """
        metrics = self.get_metrics()
        score = metrics['security_score']
        
        if score >= 95:
            status = "EXCELLENT"
            icon = "🟢"
        elif score >= 80:
            status = "GOOD"
            icon = "🟡"
        elif score >= 60:
            status = "FAIR"
            icon = "🟠"
        else:
            status = "ALERT"
            icon = "🔴"
        
        badge = f"""
╔══════════════════════════════════════════════════════════╗
║  {icon} SECURITY BADGE - Safe Path Resolver {icon}                 ║
╠══════════════════════════════════════════════════════════╣
║  Status:              {status:<30}        ║
║  Security Score:      {score:.1f}/100                            ║
║  Total Validations:   {metrics['total_validations']:<30}        ║
║  Blocked Attacks:     {metrics['blocked_attacks']:<30}        ║
║  Success Rate:        {(metrics['successful_validations']/max(1,metrics['total_validations'])*100):.1f}%                             ║
╠══════════════════════════════════════════════════════════╣
║  Attack Breakdown:                                       ║
║    Path Traversal:    {metrics['attack_breakdown']['path_traversal']:<30}        ║
║    Absolute Path:     {metrics['attack_breakdown']['absolute_path']:<30}        ║
║    Null Byte:         {metrics['attack_breakdown']['null_byte']:<30}        ║
║    Special Chars:     {metrics['attack_breakdown']['special_chars']:<30}        ║
╚══════════════════════════════════════════════════════════╝
"""
        return badge
    
    def export_metrics(self, filepath: str = "security_metrics.json"):
        """
        Export security metrics to JSON file.
        
        Args:
            filepath: Path to export file
        """
        metrics = self.get_metrics()
        
        with open(filepath, 'w') as f:
            json.dump(metrics, f, indent=2)
        
        logger.info(f"Security metrics exported to {filepath}")
    
    def reset_metrics(self):
        """Reset security metrics (for testing)"""
        with self.metrics_lock:
            self.metrics = SecurityMetrics()


# Convenience functions for backward compatibility
def sanitize_filename(filename: str) -> str:
    """Convenience function using singleton resolver"""
    resolver = SafePathResolver.get_instance()
    return resolver.sanitize_filename(filename)


def validate_output_path(base_dir: str, user_provided_path: str, 
                        allow_create: bool = True) -> Path:
    """Convenience function using singleton resolver"""
    resolver = SafePathResolver.get_instance()
    return resolver.resolve_safe_path(base_dir, user_provided_path, create_dirs=allow_create)


def validate_file_path(base_dir: str, filename: str, 
                       subdirectory: Optional[str] = None) -> Path:
    """Convenience function using singleton resolver"""
    resolver = SafePathResolver.get_instance()
    return resolver.resolve_safe_file_path(base_dir, filename, subdirectory)

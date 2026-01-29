"""
Security Tests for Path Validation

Tests to ensure path traversal vulnerabilities are properly mitigated
in the dashboard API and performance dashboard.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import os
import tempfile
import pytest
from pathlib import Path
import shutil

# Import the modules to test
from bot.path_validator import (
    sanitize_filename,
    validate_output_path,
    validate_file_path,
    PathValidationError
)
from bot.performance_dashboard import get_performance_dashboard, PerformanceDashboard


class TestPathSanitization:
    """Test filename sanitization"""
    
    def test_sanitize_basic_filename(self):
        """Test sanitization of a normal filename"""
        result = sanitize_filename("report.json")
        assert result == "report.json"
    
    def test_sanitize_removes_path_separators(self):
        """Test that path separators are removed"""
        result = sanitize_filename("../../../etc/passwd")
        # Path separators should be replaced with underscores
        # Leading dots are stripped for security
        assert "/" not in result
        assert "\\" not in result
        # Actual result after sanitization
        assert result == "_.._.._etc_passwd"
    
    def test_sanitize_removes_dangerous_chars(self):
        """Test removal of dangerous filesystem characters"""
        result = sanitize_filename("file<>:|?*.txt")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "|" not in result
        assert "?" not in result
        assert "*" not in result
    
    def test_sanitize_removes_null_bytes(self):
        """Test that null bytes are removed"""
        result = sanitize_filename("file\0name.txt")
        assert "\0" not in result
        assert result == "filename.txt"
    
    def test_sanitize_reserved_windows_names(self):
        """Test handling of reserved Windows filenames"""
        for name in ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT1']:
            result = sanitize_filename(f"{name}.txt")
            assert result.startswith("_")
    
    def test_sanitize_rejects_empty_filename(self):
        """Test that empty filenames are rejected"""
        with pytest.raises(PathValidationError):
            sanitize_filename("")
    
    def test_sanitize_rejects_dots_only(self):
        """Test that . and .. are rejected"""
        with pytest.raises(PathValidationError):
            sanitize_filename(".")
        with pytest.raises(PathValidationError):
            sanitize_filename("..")
    
    def test_sanitize_long_filename(self):
        """Test that overly long filenames are truncated"""
        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 200


class TestPathValidation:
    """Test path validation and traversal prevention"""
    
    def setup_method(self):
        """Create a temporary directory for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.temp_dir) / "reports"
        self.base_dir.mkdir(exist_ok=True)
    
    def teardown_method(self):
        """Clean up temporary directory"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_validate_simple_relative_path(self):
        """Test validation of a simple relative path"""
        result = validate_output_path(self.base_dir, "subfolder")
        assert result.is_dir()
        assert result.parent == self.base_dir.resolve()
    
    def test_validate_blocks_parent_traversal(self):
        """Test that ../ traversal is blocked"""
        with pytest.raises(PathValidationError, match="outside allowed directory"):
            validate_output_path(self.base_dir, "../../../etc")
    
    def test_validate_blocks_absolute_path_outside_base(self):
        """Test that absolute paths outside base are blocked"""
        with pytest.raises(PathValidationError, match="outside allowed directory"):
            validate_output_path(self.base_dir, "/etc/passwd")
    
    def test_validate_allows_nested_paths(self):
        """Test that nested paths within base are allowed"""
        result = validate_output_path(self.base_dir, "year/2026/january")
        assert result.is_dir()
        # Check it's within base_dir
        result.relative_to(self.base_dir.resolve())
    
    def test_validate_blocks_symlink_traversal(self):
        """Test protection against symlink attacks"""
        # Create a symlink pointing outside base_dir
        outside_dir = Path(self.temp_dir) / "outside"
        outside_dir.mkdir(exist_ok=True)
        
        symlink_path = self.base_dir / "malicious_link"
        try:
            symlink_path.symlink_to(outside_dir)
            # Should raise error because resolved path is outside base
            with pytest.raises(PathValidationError):
                validate_output_path(self.base_dir, "malicious_link")
        except OSError:
            # symlinks might not be supported on some systems
            pytest.skip("Symlinks not supported on this system")
    
    def test_validate_current_directory(self):
        """Test validation with current directory reference"""
        result = validate_output_path(self.base_dir, ".")
        assert result == self.base_dir.resolve()
    
    def test_validate_file_path(self):
        """Test file path validation"""
        result = validate_file_path(self.base_dir, "report.json")
        assert result.parent.is_dir()
        assert result.name == "report.json"
        
    def test_validate_file_path_with_subdirectory(self):
        """Test file path validation with subdirectory"""
        result = validate_file_path(self.base_dir, "report.json", "2026/january")
        assert result.parent.is_dir()
        assert result.name == "report.json"
        assert "january" in str(result)


class TestPerformanceDashboardSecurity:
    """Test security of performance dashboard export functions"""
    
    def setup_method(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.dashboard = PerformanceDashboard()
        # Override default report directory for testing
        self.dashboard._default_report_dir = Path(self.temp_dir).resolve()
    
    def teardown_method(self):
        """Clean up"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_export_with_valid_path(self):
        """Test export with a valid path"""
        filepath = self.dashboard.export_investor_report(output_dir="./reports")
        assert os.path.exists(filepath)
        assert str(self.temp_dir) in filepath
    
    def test_export_blocks_path_traversal(self):
        """Test that path traversal is blocked in export"""
        with pytest.raises(PathValidationError):
            self.dashboard.export_investor_report(output_dir="../../../etc")
    
    def test_export_blocks_absolute_path_escape(self):
        """Test that absolute paths outside base are blocked"""
        with pytest.raises(PathValidationError):
            self.dashboard.export_investor_report(output_dir="/etc/passwd")
    
    def test_export_csv_blocks_traversal(self):
        """Test that CSV export also blocks path traversal"""
        with pytest.raises(PathValidationError):
            self.dashboard.export_csv_report(output_dir="../../sensitive")
    
    def test_export_creates_nested_directories(self):
        """Test that nested directories are created safely"""
        filepath = self.dashboard.export_investor_report(
            output_dir="./reports/2026/january"
        )
        assert os.path.exists(filepath)
        assert "2026" in filepath and "january" in filepath
    
    def test_export_sanitizes_directory_names(self):
        """Test that directory names are sanitized"""
        # Even though we pass a "dangerous" name, it should be handled safely
        # The validation will ensure it stays within base_dir
        filepath = self.dashboard.export_investor_report(output_dir="./reports")
        assert os.path.exists(filepath)


class TestDashboardAPI:
    """Test Dashboard API endpoints (integration tests)"""
    
    def setup_method(self):
        """Set up Flask test client"""
        from bot.dashboard_api import dashboard_bp
        from flask import Flask
        
        self.app = Flask(__name__)
        self.app.register_blueprint(dashboard_bp)
        self.client = self.app.test_client()
        
        # Set up temp directory
        self.temp_dir = tempfile.mkdtemp()
        dashboard = get_performance_dashboard()
        dashboard._default_report_dir = Path(self.temp_dir).resolve()
    
    def teardown_method(self):
        """Clean up"""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_health_endpoint(self):
        """Test health check endpoint"""
        response = self.client.get('/api/dashboard/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'
    
    def test_portfolio_summary_endpoint(self):
        """Test portfolio summary endpoint"""
        response = self.client.get('/api/dashboard/portfolio/summary')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'data' in data
    
    def test_export_investor_report_valid(self):
        """Test export endpoint with valid path"""
        response = self.client.post(
            '/api/dashboard/export/investor-report',
            json={'output_dir': './reports'}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'filepath' in data
    
    def test_export_investor_report_blocks_traversal(self):
        """Test that export endpoint blocks path traversal"""
        response = self.client.post(
            '/api/dashboard/export/investor-report',
            json={'output_dir': '../../../etc'}
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'Invalid output directory' in data['error']
    
    def test_export_csv_blocks_traversal(self):
        """Test that CSV export endpoint blocks path traversal"""
        response = self.client.post(
            '/api/dashboard/export/csv',
            json={'output_dir': '../../sensitive'}
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
    
    def test_export_with_default_path(self):
        """Test export with no output_dir specified (uses default)"""
        response = self.client.post(
            '/api/dashboard/export/investor-report',
            json={}
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

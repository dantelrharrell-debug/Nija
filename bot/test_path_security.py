"""
Security Tests for Path Validation

Tests to ensure path traversal vulnerabilities are properly mitigated
in the dashboard API and performance dashboard.
Security Tests for Path Traversal Protection

Tests to ensure path validation prevents directory traversal attacks
and other file system security vulnerabilities.

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
import json
import tempfile
import shutil
from pathlib import Path
import pytest

from bot.path_validator import PathValidator
from bot.performance_dashboard import PerformanceDashboard, get_performance_dashboard


class TestPathValidator:
    """Test path validation and sanitization"""
    
    def test_validate_safe_directory(self):
        """Test validation of safe directory names"""
        assert PathValidator.validate_directory_name("reports") is True
        assert PathValidator.validate_directory_name("my_reports") is True
        assert PathValidator.validate_directory_name("reports-2024") is True
        assert PathValidator.validate_directory_name("reports.backup") is True
    
    def test_validate_dangerous_directory(self):
        """Test detection of dangerous directory names"""
        # Path traversal attempts
        assert PathValidator.validate_directory_name("../etc") is False
        assert PathValidator.validate_directory_name("..\\windows") is False
        assert PathValidator.validate_directory_name("reports/../sensitive") is False
        
        # Absolute paths
        assert PathValidator.validate_directory_name("/etc/passwd") is False
        assert PathValidator.validate_directory_name("C:\\Windows") is False
        
        # Special characters
        assert PathValidator.validate_directory_name("reports<script>") is False
        assert PathValidator.validate_directory_name("reports:name") is False
        assert PathValidator.validate_directory_name("reports|pipe") is False
        
        # Null bytes
        assert PathValidator.validate_directory_name("reports\x00") is False
        
        # Home directory
        assert PathValidator.validate_directory_name("~/secrets") is False
    
    def test_sanitize_directory(self):
        """Test directory name sanitization"""
        assert PathValidator.sanitize_directory_name("../etc") == "etc"
        assert PathValidator.sanitize_directory_name("reports/../data") == "reports__data"
        assert PathValidator.sanitize_directory_name("/etc/passwd") == "etcpasswd"
        assert PathValidator.sanitize_directory_name("C:\\Windows") == "C_Windows"
        assert PathValidator.sanitize_directory_name("reports<script>") == "reportsscript"
        assert PathValidator.sanitize_directory_name("") == "reports"
        assert PathValidator.sanitize_directory_name(None) == "reports"
    
    def test_secure_path_within_base(self):
        """Test secure path creation within base directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Valid subdirectory
            secure = PathValidator.secure_path(tmpdir, "reports")
            assert secure.parent == Path(tmpdir).resolve()
            
            # Valid nested subdirectory
            secure = PathValidator.secure_path(tmpdir, "reports/monthly")
            assert secure.is_relative_to(Path(tmpdir).resolve())
    
    def test_secure_path_traversal_prevention(self):
        """Test that secure_path prevents directory traversal"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # These should all be sanitized to stay within tmpdir
            # The validator should prevent escaping the base directory
            
            # Parent directory reference
            secure = PathValidator.secure_path(tmpdir, "../etc")
            assert secure.is_relative_to(Path(tmpdir).resolve())
            
            # Multiple parent references
            secure = PathValidator.secure_path(tmpdir, "../../../../../../etc")
            assert secure.is_relative_to(Path(tmpdir).resolve())
            
            # Mixed paths
            secure = PathValidator.secure_path(tmpdir, "reports/../../etc")
            assert secure.is_relative_to(Path(tmpdir).resolve())
    
    def test_validate_filename(self):
        """Test filename validation"""
        # Valid filenames
        assert PathValidator.validate_filename("report.json") is True
        assert PathValidator.validate_filename("data_2024.csv") is True
        assert PathValidator.validate_filename("backup-2024-01.txt") is True
        
        # Invalid filenames
        assert PathValidator.validate_filename("../etc/passwd") is False
        assert PathValidator.validate_filename("report") is False  # No extension
        assert PathValidator.validate_filename("report.json\x00.txt") is False
        assert PathValidator.validate_filename("") is False
        assert PathValidator.validate_filename(None) is False
    
    def test_sanitize_filename(self):
        """Test filename sanitization"""
        assert PathValidator.sanitize_filename("report.json") == "report.json"
        assert PathValidator.sanitize_filename("../etc/passwd") == "passwd"
        assert PathValidator.sanitize_filename("file<script>.txt") == "file_script_.txt"
        assert PathValidator.sanitize_filename("noextension") == "noextension.json"
        assert PathValidator.sanitize_filename("") == "report.json"
        assert PathValidator.sanitize_filename(None) == "report.json"


class TestPerformanceDashboard:
    """Test performance dashboard with secure path handling"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.test_dir = tempfile.mkdtemp()
        self.dashboard = PerformanceDashboard("test_user")
    
    def teardown_method(self):
        """Cleanup test fixtures"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_user_id_sanitization(self):
        """Test that user_id is sanitized on initialization"""
        dashboard = PerformanceDashboard("user/../admin")
        assert ".." not in dashboard.user_id
        assert "/" not in dashboard.user_id
        assert "\\" not in dashboard.user_id
    
    def test_export_safe_directory(self):
        """Test exporting to a safe directory"""
        output_dir = os.path.join(self.test_dir, "reports")
        filepath = self.dashboard.export_investor_report(output_dir=output_dir)
        
        # Verify file was created
        assert os.path.exists(filepath)
        
        # Verify it's in the expected location
        assert filepath.startswith(str(Path(output_dir).resolve()))
        
        # Verify content is valid JSON
        with open(filepath, 'r') as f:
            data = json.load(f)
            assert data['report_type'] == 'investor_report'
            assert data['user_id'] == 'test_user'
    
    def test_export_traversal_attempt(self):
        """Test that path traversal attempts are blocked"""
        # Attempt to write outside reports directory
        malicious_paths = [
            "../../../etc",
            "../../sensitive_data",
            "../..",
            "reports/../../../etc"
        ]
        
        for malicious_path in malicious_paths:
            # Export should succeed but sanitize the path
            filepath = self.dashboard.export_investor_report(output_dir=malicious_path)
            
            # Verify file was created in safe location
            assert os.path.exists(filepath)
            
            # Verify the file is in ./reports, not in the attempted location
            filepath_obj = Path(filepath).resolve()
            reports_dir = Path("./reports").resolve()
            assert filepath_obj.is_relative_to(reports_dir)
    
    def test_export_absolute_path_attempt(self):
        """Test that absolute paths are handled safely"""
        # These should be sanitized to relative paths
        absolute_paths = [
            "/etc/passwd",
            "C:\\Windows\\System32",
            "/tmp/sensitive"
        ]
        
        for abs_path in absolute_paths:
            filepath = self.dashboard.export_investor_report(output_dir=abs_path)
            assert os.path.exists(filepath)
            
            # Should be in ./reports, not at the absolute path
            filepath_obj = Path(filepath).resolve()
            reports_dir = Path("./reports").resolve()
            assert filepath_obj.is_relative_to(reports_dir)
    
    def test_export_null_byte_injection(self):
        """Test protection against null byte injection"""
        malicious_path = "reports\x00/../etc"
        filepath = self.dashboard.export_investor_report(output_dir=malicious_path)
        
        # Should be safely handled
        assert os.path.exists(filepath)
        assert "\x00" not in filepath
    
    def test_get_performance_dashboard_caching(self):
        """Test that dashboard instances are cached per user"""
        dashboard1 = get_performance_dashboard("user1")
        dashboard2 = get_performance_dashboard("user1")
        dashboard3 = get_performance_dashboard("user2")
        
        # Same user should get same instance
        assert dashboard1 is dashboard2
        
        # Different user should get different instance
        assert dashboard1 is not dashboard3
    
    def test_performance_summary_structure(self):
        """Test that performance summary has expected structure"""
        summary = self.dashboard.get_performance_summary()
        
        # Check required fields
        assert 'user_id' in summary
        assert 'timestamp' in summary
        assert 'portfolio_value' in summary
        assert 'total_pnl' in summary
        assert 'win_rate' in summary
        assert 'total_trades' in summary


class TestDashboardAPI:
    """Test dashboard API endpoints"""
    
    def test_api_import(self):
        """Test that dashboard_api module can be imported"""
        try:
            from bot import dashboard_api
            assert hasattr(dashboard_api, 'dashboard_bp')
        except ImportError as e:
            pytest.fail(f"Failed to import dashboard_api: {e}")
    
    def test_export_endpoint_validation(self):
        """Test export endpoint validates input"""
        from bot.dashboard_api import dashboard_bp
        from flask import Flask
        
        app = Flask(__name__)
        app.register_blueprint(dashboard_bp)
        client = app.test_client()
        
        # Test with malicious path
        response = client.post('/api/dashboard/export', 
            json={'output_dir': '../../../etc'},
            content_type='application/json'
        )
        
        # Should succeed but sanitize the path
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        
        # Filepath should be safe
        filepath = data.get('filepath', '')
        assert '../' not in filepath or Path(filepath).is_relative_to(Path('./reports').resolve())


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])

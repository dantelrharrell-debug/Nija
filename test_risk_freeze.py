"""
Test Suite for RISK FREEZE Enforcement

Tests the risk freeze guard, versioning system, and policy enforcement.

Author: NIJA Trading Systems
Date: February 12, 2026
"""

import unittest
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent))

# Import directly from module files to avoid importing bot.py
import importlib.util

# Load risk_freeze_guard
spec = importlib.util.spec_from_file_location(
    "risk_freeze_guard",
    Path(__file__).parent / "bot" / "risk_freeze_guard.py"
)
risk_freeze_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(risk_freeze_guard)

RiskFreezeGuard = risk_freeze_guard.RiskFreezeGuard
RiskFreezeViolation = risk_freeze_guard.RiskFreezeViolation
EmergencyOverride = risk_freeze_guard.EmergencyOverride

# Load risk_config_versions
spec = importlib.util.spec_from_file_location(
    "risk_config_versions",
    Path(__file__).parent / "bot" / "risk_config_versions.py"
)
risk_config_versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(risk_config_versions)

RiskConfigVersionManager = risk_config_versions.RiskConfigVersionManager
RiskConfigVersion = risk_config_versions.RiskConfigVersion
RiskParameterChange = risk_config_versions.RiskParameterChange
BacktestResults = risk_config_versions.BacktestResults
PaperTradingResults = risk_config_versions.PaperTradingResults
Approval = risk_config_versions.Approval


class TestRiskFreezeGuard(unittest.TestCase):
    """Test Risk Freeze Guard enforcement"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_dir = tempfile.mkdtemp()
        self.baseline_path = Path(self.test_dir) / "baseline.json"
        self.emergency_log_path = Path(self.test_dir) / "emergency.json"
        
        self.guard = RiskFreezeGuard(
            baseline_config_path=str(self.baseline_path),
            emergency_log_path=str(self.emergency_log_path)
        )
        
        # Baseline config
        self.baseline_config = {
            'max_position_size': 0.10,
            'min_position_size': 0.01,
            'max_daily_loss': 0.025,
            'stop_loss_atr_multiplier': 1.5,
        }
    
    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.test_dir)
    
    def test_set_baseline(self):
        """Test setting baseline configuration"""
        self.guard.set_baseline(self.baseline_config)
        
        self.assertIsNotNone(self.guard.baseline_config)
        self.assertIsNotNone(self.guard.baseline_hash)
        self.assertTrue(self.baseline_path.exists())
    
    def test_validate_unchanged_config(self):
        """Test validation passes for unchanged config"""
        self.guard.set_baseline(self.baseline_config)
        
        # Should pass without exception
        result = self.guard.validate_config(self.baseline_config)
        self.assertTrue(result)
    
    def test_detect_protected_parameter_change(self):
        """Test detection of protected parameter changes"""
        self.guard.set_baseline(self.baseline_config)
        
        # Change a protected parameter
        changed_config = self.baseline_config.copy()
        changed_config['max_position_size'] = 0.15  # Changed from 0.10
        
        # Should raise violation
        with self.assertRaises(RiskFreezeViolation) as cm:
            self.guard.validate_config(changed_config)
        
        self.assertIn('max_position_size', str(cm.exception))
    
    def test_allow_non_protected_parameter_change(self):
        """Test non-protected parameters can change"""
        config_with_extra = self.baseline_config.copy()
        config_with_extra['some_other_param'] = 'value'
        
        self.guard.set_baseline(self.baseline_config)
        
        # Should pass (warning logged but no exception)
        result = self.guard.validate_config(config_with_extra)
        self.assertTrue(result)
    
    def test_emergency_override(self):
        """Test emergency override mechanism"""
        self.guard.set_baseline(self.baseline_config)
        
        # Declare emergency override
        self.guard.declare_emergency_override(
            reason="Exchange margin requirement changed",
            authorized_by="Technical Lead",
            parameters_changed=['max_leverage']
        )
        
        self.assertEqual(len(self.guard.emergency_overrides), 1)
        self.assertTrue(self.emergency_log_path.exists())
    
    def test_emergency_override_allows_change(self):
        """Test emergency override allows normally forbidden changes"""
        self.guard.set_baseline(self.baseline_config)
        
        # Change a protected parameter with emergency override
        changed_config = self.baseline_config.copy()
        changed_config['max_position_size'] = 0.15
        
        # Should pass with emergency override
        result = self.guard.validate_config(
            changed_config,
            allow_emergency_override=True
        )
        self.assertTrue(result)
    
    def test_change_detection(self):
        """Test change detection logic"""
        old_config = {'param1': 1, 'param2': 2}
        new_config = {'param1': 1, 'param2': 3, 'param3': 4}
        
        changes = self.guard._detect_changes(old_config, new_config)
        
        self.assertEqual(len(changes), 2)  # param2 changed, param3 added
    
    def test_violation_report(self):
        """Test violation report generation"""
        self.guard.set_baseline(self.baseline_config)
        
        report = self.guard.get_violation_report()
        
        self.assertIn('Risk Freeze Guard', report)
        self.assertIn('Baseline Config Hash', report)


class TestRiskConfigVersioning(unittest.TestCase):
    """Test Risk Configuration Versioning System"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_dir = tempfile.mkdtemp()
        self.version_manager = RiskConfigVersionManager(
            config_dir=str(self.test_dir)
        )
        
        self.risk_params = {
            'max_position_size': 0.10,
            'max_daily_loss': 0.025,
        }
    
    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.test_dir)
    
    def test_create_version(self):
        """Test creating a new risk configuration version"""
        changes = [
            RiskParameterChange(
                parameter='max_position_size',
                old_value=0.10,
                new_value=0.08,
                reason='Reduce exposure during volatility'
            )
        ]
        
        version = self.version_manager.create_version(
            version='RISK_CONFIG_v1.1.0',
            author='Test User',
            changes=changes,
            risk_parameters=self.risk_params
        )
        
        self.assertEqual(version.version, 'RISK_CONFIG_v1.1.0')
        self.assertEqual(version.status, 'proposed')
        self.assertEqual(len(version.changes), 1)
    
    def test_add_backtest_results(self):
        """Test adding backtest results to a version"""
        changes = [RiskParameterChange('param', 1, 2, 'test')]
        version = self.version_manager.create_version(
            'RISK_CONFIG_v1.1.0',
            'Test User',
            changes,
            self.risk_params
        )
        
        results = BacktestResults(
            period_start='2025-01-01',
            period_end='2026-01-01',
            win_rate=0.58,
            max_drawdown=0.12,
            sharpe_ratio=1.75,
            total_return=0.45,
            total_trades=100,
            conclusion='Approved'
        )
        
        self.version_manager.add_backtest_results('RISK_CONFIG_v1.1.0', results)
        
        updated = self.version_manager.get_version('RISK_CONFIG_v1.1.0')
        self.assertIsNotNone(updated.backtesting)
        self.assertEqual(updated.status, 'testing')
    
    def test_add_approvals(self):
        """Test adding approval signatures"""
        changes = [RiskParameterChange('param', 1, 2, 'test')]
        version = self.version_manager.create_version(
            'RISK_CONFIG_v1.1.0',
            'Test User',
            changes,
            self.risk_params
        )
        
        # Add approvals
        approvals = [
            Approval('Technical Lead', 'Alice', '2026-02-12', 'APPROVED'),
            Approval('Risk Manager', 'Bob', '2026-02-12', 'APPROVED'),
            Approval('Strategy Developer', 'Carol', '2026-02-12', 'APPROVED'),
        ]
        
        for approval in approvals:
            self.version_manager.add_approval('RISK_CONFIG_v1.1.0', approval)
        
        updated = self.version_manager.get_version('RISK_CONFIG_v1.1.0')
        self.assertTrue(updated.is_approved())
    
    def test_cannot_activate_without_approval(self):
        """Test that version cannot be activated without full approval"""
        changes = [RiskParameterChange('param', 1, 2, 'test')]
        version = self.version_manager.create_version(
            'RISK_CONFIG_v1.1.0',
            'Test User',
            changes,
            self.risk_params
        )
        
        # Try to activate without approval
        with self.assertRaises(ValueError):
            self.version_manager.activate_version('RISK_CONFIG_v1.1.0')
    
    def test_full_approval_workflow(self):
        """Test complete approval workflow"""
        # Create version
        changes = [RiskParameterChange('max_position_size', 0.10, 0.08, 'test')]
        version = self.version_manager.create_version(
            'RISK_CONFIG_v1.1.0',
            'Test User',
            changes,
            self.risk_params
        )
        
        # Add backtest results
        backtest = BacktestResults(
            period_start='2025-01-01',
            period_end='2026-01-01',
            win_rate=0.58,
            max_drawdown=0.12,
            sharpe_ratio=1.75,
            total_return=0.45,
            total_trades=100,
            conclusion='Approved'
        )
        self.version_manager.add_backtest_results('RISK_CONFIG_v1.1.0', backtest)
        
        # Add paper trading results
        paper = PaperTradingResults(
            period_start='2026-01-15',
            period_end='2026-02-01',
            trades=50,
            win_rate=0.60,
            max_drawdown=0.08,
            conclusion='Approved'
        )
        self.version_manager.add_paper_trading_results('RISK_CONFIG_v1.1.0', paper)
        
        # Add all approvals
        approvals = [
            Approval('Technical Lead', 'Alice', '2026-02-12', 'APPROVED'),
            Approval('Risk Manager', 'Bob', '2026-02-12', 'APPROVED'),
            Approval('Strategy Developer', 'Carol', '2026-02-12', 'APPROVED'),
        ]
        for approval in approvals:
            self.version_manager.add_approval('RISK_CONFIG_v1.1.0', approval)
        
        # Now activation should work
        self.version_manager.activate_version('RISK_CONFIG_v1.1.0')
        
        active = self.version_manager.get_active_version()
        self.assertIsNotNone(active)
        self.assertEqual(active.version, 'RISK_CONFIG_v1.1.0')
        self.assertEqual(active.status, 'active')
    
    def test_get_active_parameters(self):
        """Test getting parameters from active version"""
        # Create and activate a version
        changes = [RiskParameterChange('param', 1, 2, 'test')]
        version = self.version_manager.create_version(
            'RISK_CONFIG_v1.0.0',
            'Test User',
            changes,
            self.risk_params
        )
        
        # Set up for activation
        version.backtesting = BacktestResults(
            '2025-01-01', '2026-01-01', 0.58, 0.12, 1.75, 0.45, 100, 'Approved'
        )
        version.paper_trading = PaperTradingResults(
            '2026-01-15', '2026-02-01', 50, 0.60, 0.08, 'Approved'
        )
        version.approvals = [
            Approval('Technical Lead', 'Alice', '2026-02-12', 'APPROVED'),
            Approval('Risk Manager', 'Bob', '2026-02-12', 'APPROVED'),
            Approval('Strategy Developer', 'Carol', '2026-02-12', 'APPROVED'),
        ]
        version.status = 'approved'
        self.version_manager.versions[version.version] = version
        self.version_manager._save_version(version)
        
        self.version_manager.activate_version('RISK_CONFIG_v1.0.0')
        
        params = self.version_manager.get_active_parameters()
        self.assertEqual(params, self.risk_params)
    
    def test_version_report_generation(self):
        """Test version report generation"""
        changes = [RiskParameterChange('max_position_size', 0.10, 0.08, 'test')]
        version = self.version_manager.create_version(
            'RISK_CONFIG_v1.1.0',
            'Test User',
            changes,
            self.risk_params
        )
        
        report = self.version_manager.generate_version_report('RISK_CONFIG_v1.1.0')
        
        self.assertIn('RISK_CONFIG_v1.1.0', report)
        self.assertIn('max_position_size', report)
        self.assertIn('Test User', report)


class TestEmergencyOverride(unittest.TestCase):
    """Test Emergency Override functionality"""
    
    def test_emergency_override_creation(self):
        """Test creating an emergency override"""
        override = EmergencyOverride(
            reason="Critical bug fix",
            authorized_by="Technical Lead",
            parameters_changed=['max_leverage']
        )
        
        self.assertEqual(override.reason, "Critical bug fix")
        self.assertEqual(len(override.parameters_changed), 1)
    
    def test_emergency_override_serialization(self):
        """Test emergency override to/from dict"""
        override = EmergencyOverride(
            reason="Test",
            authorized_by="User",
            parameters_changed=['param1', 'param2']
        )
        
        data = override.to_dict()
        restored = EmergencyOverride.from_dict(data)
        
        self.assertEqual(override.reason, restored.reason)
        self.assertEqual(override.authorized_by, restored.authorized_by)
        self.assertEqual(override.parameters_changed, restored.parameters_changed)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)

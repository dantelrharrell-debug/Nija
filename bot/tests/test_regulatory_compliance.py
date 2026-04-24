"""
Test Suite for Regulatory Compliance Framework
==============================================

Tests app store compliance, financial regulations, and risk disclosures.
"""

import pytest
from bot.regulatory_compliance import (
    RegulatoryComplianceTester,
    ComplianceLevel,
    ComplianceStatus
)


class TestComplianceFramework:
    """Test the compliance testing framework"""

    def test_all_checks_run(self):
        """All compliance checks should execute"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        assert report['summary']['total_checks'] > 0
        assert len(report['checks']) > 0

    def test_compliance_score_calculation(self):
        """Compliance score should be calculated correctly"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        total = report['summary']['total_checks']
        passed = report['summary']['passed']
        expected_score = (passed / total * 100) if total > 0 else 0

        assert report['summary']['compliance_score'] == round(expected_score, 2)


class TestAppStoreCompliance:
    """Test app store policy compliance checks"""

    def test_no_profit_guarantees_check(self):
        """Platform should not guarantee profits"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        # Find the specific check
        check = next(
            (c for c in report['checks'] if c['check_id'] == 'APP_STORE_001'),
            None
        )

        assert check is not None
        assert check['name'] == 'No Profit Guarantees'
        assert check['level'] == ComplianceLevel.CRITICAL.value
        assert check['status'] == ComplianceStatus.PASS.value

    def test_risk_warnings_check(self):
        """Platform should display risk warnings"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'APP_STORE_002'),
            None
        )

        assert check is not None
        assert check['name'] == 'Risk Warnings Displayed'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_age_restriction_check(self):
        """Platform should enforce 18+ age restriction"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'APP_STORE_003'),
            None
        )

        assert check is not None
        assert check['name'] == 'Age Restriction (18+)'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_paper_trading_available_check(self):
        """Platform should offer paper trading"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'APP_STORE_004'),
            None
        )

        assert check is not None
        assert check['name'] == 'Paper Trading Mode'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_subscription_transparency_check(self):
        """Subscription terms should be transparent"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'APP_STORE_005'),
            None
        )

        assert check is not None
        assert check['name'] == 'Transparent Subscription Terms'
        assert check['status'] == ComplianceStatus.PASS.value


class TestFinancialRegulations:
    """Test financial regulatory compliance checks"""

    def test_no_investment_advice_check(self):
        """Platform should not provide investment advice"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'FIN_REG_001'),
            None
        )

        assert check is not None
        assert check['name'] == 'No Investment Advice'
        assert check['level'] == ComplianceLevel.CRITICAL.value
        assert check['status'] == ComplianceStatus.PASS.value

    def test_liability_disclaimers_check(self):
        """Platform should have liability disclaimers"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'FIN_REG_002'),
            None
        )

        assert check is not None
        assert check['name'] == 'Liability Disclaimers'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_user_authorization_check(self):
        """Platform should require user authorization for trades"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'FIN_REG_003'),
            None
        )

        assert check is not None
        assert check['name'] == 'User Authorization Required'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_risk_management_controls_check(self):
        """Platform should enforce risk management"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'FIN_REG_004'),
            None
        )

        assert check is not None
        assert check['name'] == 'Risk Management Controls'
        assert check['status'] == ComplianceStatus.PASS.value


class TestDataPrivacy:
    """Test data privacy compliance checks"""

    def test_encrypted_api_keys_check(self):
        """API keys should be encrypted"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'PRIVACY_001'),
            None
        )

        assert check is not None
        assert check['name'] == 'Encrypted API Key Storage'
        assert check['level'] == ComplianceLevel.CRITICAL.value
        assert check['status'] == ComplianceStatus.PASS.value

    def test_no_pii_in_logs_check(self):
        """PII should not appear in logs"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'PRIVACY_002'),
            None
        )

        assert check is not None
        assert check['name'] == 'No PII in Logs'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_data_deletion_check(self):
        """Users should be able to delete their data"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'PRIVACY_003'),
            None
        )

        assert check is not None
        assert check['name'] == 'User Data Deletion'
        assert check['status'] == ComplianceStatus.PASS.value


class TestConsumerProtection:
    """Test consumer protection compliance checks"""

    def test_emergency_stop_check(self):
        """Platform should have emergency stop mechanism"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'CONSUMER_001'),
            None
        )

        assert check is not None
        assert check['name'] == 'Emergency Stop/Kill-Switch'
        assert check['level'] == ComplianceLevel.CRITICAL.value
        assert check['status'] == ComplianceStatus.PASS.value

    def test_fee_transparency_check(self):
        """Fees should be transparent"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'CONSUMER_002'),
            None
        )

        assert check is not None
        assert check['name'] == 'Fee Transparency'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_performance_reporting_check(self):
        """Performance reporting should be accurate"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'CONSUMER_003'),
            None
        )

        assert check is not None
        assert check['name'] == 'Accurate Performance Reporting'
        assert check['status'] == ComplianceStatus.PASS.value


class TestRiskDisclosures:
    """Test risk disclosure compliance checks"""

    def test_trading_risk_warnings_check(self):
        """Trading risk warnings should be displayed"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'RISK_001'),
            None
        )

        assert check is not None
        assert check['name'] == 'Trading Risk Warnings'
        assert check['level'] == ComplianceLevel.CRITICAL.value
        assert check['status'] == ComplianceStatus.PASS.value

    def test_automated_trading_risks_check(self):
        """Automated trading risks should be disclosed"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'RISK_002'),
            None
        )

        assert check is not None
        assert check['name'] == 'Automated Trading Risks'
        assert check['status'] == ComplianceStatus.PASS.value

    def test_suitability_warning_check(self):
        """Platform should warn that trading is not suitable for everyone"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        check = next(
            (c for c in report['checks'] if c['check_id'] == 'RISK_003'),
            None
        )

        assert check is not None
        assert check['name'] == 'Suitability Warning'
        assert check['status'] == ComplianceStatus.PASS.value


class TestSubmissionReadiness:
    """Test overall submission readiness"""

    def test_ready_for_submission_when_no_critical_failures(self):
        """Platform should be ready for submission with all checks passing"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        assert report['summary']['ready_for_submission'] is True
        assert report['summary']['critical_failures'] == 0

    def test_not_ready_for_submission_with_critical_failures(self):
        """Platform should not be ready if critical checks fail"""
        tester = RegulatoryComplianceTester()

        # Simulate a critical failure
        tester._add_check(
            check_id="TEST_CRITICAL",
            name="Test Critical Check",
            description="Test critical failure",
            level=ComplianceLevel.CRITICAL,
            status=ComplianceStatus.FAIL,
            details="This is a test failure",
            remediation="Fix the test"
        )

        report = tester._generate_report()

        assert report['summary']['ready_for_submission'] is False
        assert report['summary']['critical_failures'] > 0


class TestReportGeneration:
    """Test compliance report generation"""

    def test_report_includes_summary(self):
        """Report should include summary section"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        assert 'summary' in report
        assert 'timestamp' in report['summary']
        assert 'total_checks' in report['summary']
        assert 'passed' in report['summary']
        assert 'failed' in report['summary']
        assert 'compliance_score' in report['summary']

    def test_report_includes_all_checks(self):
        """Report should include all individual checks"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        assert 'checks' in report
        assert len(report['checks']) > 0

    def test_report_includes_recommendations(self):
        """Report should include recommendations"""
        tester = RegulatoryComplianceTester()
        report = tester.run_all_checks()

        assert 'recommendations' in report
        assert len(report['recommendations']) > 0

    def test_critical_failures_listed_separately(self):
        """Critical failures should be listed separately"""
        tester = RegulatoryComplianceTester()

        # Add a critical failure
        tester._add_check(
            check_id="TEST_FAIL",
            name="Test Failure",
            description="Test",
            level=ComplianceLevel.CRITICAL,
            status=ComplianceStatus.FAIL,
            details="Test failure",
            remediation="Fix it"
        )

        report = tester._generate_report()

        assert 'critical_failures' in report
        assert len(report['critical_failures']) > 0


class TestComplianceExecution:
    """Test compliance test execution"""

    def test_can_run_standalone(self):
        """Compliance tests can run as standalone script"""
        from bot.regulatory_compliance import run_compliance_test

        report = run_compliance_test()

        assert report is not None
        assert 'summary' in report

    def test_print_report_executes_without_error(self):
        """Print report should execute without errors"""
        tester = RegulatoryComplianceTester()
        tester.run_all_checks()

        # Should not raise any exceptions
        try:
            tester.print_report()
            success = True
        except Exception:
            success = False

        assert success is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

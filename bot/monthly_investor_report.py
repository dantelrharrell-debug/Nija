"""
NIJA Monthly Investor Report Generator

Generates comprehensive monthly investor reports including:
- Performance summary
- Risk metrics
- Market commentary
- Strategy activity summary  
- Capital changes

This is fund reporting infrastructure.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json

try:
    from performance_dashboard import PerformanceDashboard
    from strategy_portfolio_manager import StrategyPortfolioManager
except ImportError:
    from bot.performance_dashboard import PerformanceDashboard
    from bot.strategy_portfolio_manager import StrategyPortfolioManager

logger = logging.getLogger("nija.monthly_report")


class MonthlyInvestorReportGenerator:
    """
    Generate comprehensive monthly investor reports
    
    Fund reporting infrastructure that produces investor-grade
    monthly performance reports.
    """
    
    def __init__(self, dashboard: PerformanceDashboard,
                 portfolio_manager: StrategyPortfolioManager):
        """
        Initialize report generator
        
        Args:
            dashboard: Performance dashboard instance
            portfolio_manager: Strategy portfolio manager instance
        """
        self.dashboard = dashboard
        self.portfolio = portfolio_manager
        
        logger.info("✅ Monthly Investor Report Generator initialized")
    
    def generate_performance_summary(self, year: int, month: int) -> Dict:
        """
        Generate performance summary section
        
        Args:
            year: Report year
            month: Report month
        
        Returns:
            Dictionary with performance summary
        """
        # Get monthly report data
        monthly_data = self.dashboard.get_monthly_report(year, month)
        
        # Get current metrics for comparison
        current_metrics = self.dashboard.get_current_metrics()
        
        return {
            'period': f"{year}-{month:02d}",
            'nav_start': monthly_data.get('start_equity', 0),
            'nav_end': monthly_data.get('end_equity', 0),
            'monthly_return_pct': monthly_data.get('monthly_return_pct', 0),
            'ytd_return_pct': current_metrics['total_return_pct'],
            'total_trades': monthly_data.get('total_trades', 0),
            'win_rate_pct': monthly_data.get('win_rate_pct', 0),
            'trading_days': monthly_data.get('trading_days', 0)
        }
    
    def generate_risk_metrics(self, year: int, month: int) -> Dict:
        """
        Generate risk metrics section
        
        Args:
            year: Report year
            month: Report month
        
        Returns:
            Dictionary with risk metrics
        """
        monthly_data = self.dashboard.get_monthly_report(year, month)
        current_metrics = self.dashboard.get_current_metrics()
        
        return {
            'sharpe_ratio': monthly_data.get('max_dd_month', current_metrics['sharpe_ratio']),
            'sortino_ratio': current_metrics['sortino_ratio'],
            'calmar_ratio': current_metrics['calmar_ratio'],
            'max_drawdown_month_pct': monthly_data.get('max_drawdown_pct', 0),
            'max_drawdown_ytd_pct': current_metrics['max_drawdown_pct'],
            'current_drawdown_pct': current_metrics['current_drawdown_pct'],
            'volatility_pct': monthly_data.get('volatility_pct', current_metrics['annualized_volatility_pct']),
            'profit_factor': current_metrics.get('profit_factor', 0)
        }
    
    def generate_market_commentary(self, year: int, month: int) -> Dict:
        """
        Generate market commentary section
        
        Args:
            year: Report year
            month: Report month
        
        Returns:
            Dictionary with market commentary
        """
        portfolio_summary = self.portfolio.get_portfolio_summary()
        
        # Generate commentary based on regime and performance
        regime = portfolio_summary['current_regime']
        monthly_return = self.dashboard.get_monthly_report(year, month).get('monthly_return_pct', 0)
        
        commentary = []
        
        # Regime commentary
        regime_comments = {
            'bull_trending': "Market exhibited strong bullish trends with sustained upward momentum.",
            'bear_trending': "Market showed bearish pressure with downward trends dominating the period.",
            'ranging': "Market traded in a range-bound pattern with limited directional movement.",
            'volatile': "Market experienced heightened volatility with rapid price fluctuations.",
            'crisis': "Market conditions were characterized by extreme volatility and risk-off sentiment."
        }
        commentary.append(regime_comments.get(regime, "Market conditions were mixed."))
        
        # Performance commentary
        if monthly_return > 5:
            commentary.append("Strong performance driven by favorable market conditions and effective strategy execution.")
        elif monthly_return > 0:
            commentary.append("Positive performance achieved through disciplined risk management.")
        elif monthly_return > -3:
            commentary.append("Minor drawdown contained through active risk controls.")
        else:
            commentary.append("Drawdown protection protocols activated to preserve capital.")
        
        return {
            'market_regime': regime,
            'commentary': commentary,
            'key_observations': [
                f"Portfolio operated in {regime.replace('_', ' ')} market regime",
                f"Diversification score: {portfolio_summary.get('diversification_score', 0):.1f}/100",
                f"Active strategies: {portfolio_summary.get('active_strategies', 0)}"
            ]
        }
    
    def generate_strategy_activity(self, year: int, month: int) -> Dict:
        """
        Generate strategy activity summary
        
        Args:
            year: Report year
            month: Report month
        
        Returns:
            Dictionary with strategy activity
        """
        portfolio_summary = self.portfolio.get_portfolio_summary()
        
        # Get strategy scores
        scores = self.portfolio.score_strategies()
        
        # Get strategy allocations
        allocations = portfolio_summary.get('allocations', {})
        
        # Build strategy summaries
        strategy_summaries = []
        for name, perf in portfolio_summary.get('strategy_performance', {}).items():
            strategy_summaries.append({
                'name': name,
                'allocation_pct': allocations.get(name, 0),
                'score': scores.get(name, 0),
                'total_trades': perf.get('total_trades', 0),
                'win_rate_pct': perf.get('win_rate_pct', 0),
                'total_pnl': perf.get('total_pnl', 0)
            })
        
        # Sort by allocation
        strategy_summaries.sort(key=lambda x: x['allocation_pct'], reverse=True)
        
        return {
            'active_strategies': len(strategy_summaries),
            'strategy_breakdown': strategy_summaries,
            'top_performer': strategy_summaries[0]['name'] if strategy_summaries else None,
            'diversification_score': portfolio_summary.get('diversification_score', 0)
        }
    
    def generate_capital_changes(self, year: int, month: int) -> Dict:
        """
        Generate capital changes section
        
        Args:
            year: Report year
            month: Report month
        
        Returns:
            Dictionary with capital changes
        """
        monthly_data = self.dashboard.get_monthly_report(year, month)
        
        start_nav = monthly_data.get('start_equity', 0)
        end_nav = monthly_data.get('end_equity', 0)
        change = end_nav - start_nav
        change_pct = (change / start_nav * 100) if start_nav > 0 else 0
        
        return {
            'beginning_nav': start_nav,
            'ending_nav': end_nav,
            'net_change': change,
            'net_change_pct': change_pct,
            'deposits': 0,  # Would track actual deposits/withdrawals
            'withdrawals': 0,
            'investment_return': change,
            'investment_return_pct': monthly_data.get('monthly_return_pct', 0)
        }
    
    def generate_full_report(self, year: int, month: int) -> Dict:
        """
        Generate complete monthly investor report
        
        Args:
            year: Report year
            month: Report month
        
        Returns:
            Complete monthly report dictionary
        """
        logger.info(f"Generating monthly report for {year}-{month:02d}")
        
        report = {
            'report_date': datetime.now().isoformat(),
            'period': {
                'year': year,
                'month': month,
                'month_name': datetime(year, month, 1).strftime('%B')
            },
            
            # Core sections
            'performance_summary': self.generate_performance_summary(year, month),
            'risk_metrics': self.generate_risk_metrics(year, month),
            'market_commentary': self.generate_market_commentary(year, month),
            'strategy_activity': self.generate_strategy_activity(year, month),
            'capital_changes': self.generate_capital_changes(year, month),
            
            # Additional data
            'equity_curve': self.dashboard.get_equity_curve(days=30),
            'drawdown_curve': self.dashboard.get_drawdown_curve(days=30),
            
            # Metadata
            'generated_by': 'NIJA Trading Systems',
            'report_version': '1.0'
        }
        
        logger.info(f"✅ Monthly report generated successfully")
        
        return report
    
    def export_report(self, year: int, month: int, 
                      output_dir: str = "./reports/monthly",
                      format: str = "json") -> str:
        """
        Export monthly report to file
        
        Args:
            year: Report year
            month: Report month
            output_dir: Output directory
            format: Export format (json, html, pdf)
        
        Returns:
            Path to exported report
        """
        # Generate report
        report = self.generate_full_report(year, month)
        
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)
        
        # Generate filename
        month_name = datetime(year, month, 1).strftime('%B')
        filename = f"monthly_report_{year}_{month:02d}_{month_name}.{format}"
        filepath = output_path / filename
        
        if format == "json":
            # Export as JSON
            with open(filepath, 'w') as f:
                json.dump(report, f, indent=2, default=str)
        
        elif format == "html":
            # Export as HTML (simplified)
            html = self._generate_html_report(report)
            with open(filepath, 'w') as f:
                f.write(html)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        logger.info(f"📄 Report exported to: {filepath}")
        
        return str(filepath)
    
    def _generate_html_report(self, report: Dict) -> str:
        """Generate HTML version of report"""
        period = report['period']
        perf = report['performance_summary']
        risk = report['risk_metrics']
        
        html = f"""
        <html>
        <head>
            <title>Monthly Investor Report - {period['month_name']} {period['year']}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                h1 {{ color: #2c3e50; }}
                h2 {{ color: #34495e; margin-top: 30px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #3498db; color: white; }}
                .metric {{ font-size: 1.2em; font-weight: bold; }}
                .positive {{ color: #27ae60; }}
                .negative {{ color: #e74c3c; }}
            </style>
        </head>
        <body>
            <h1>Monthly Investor Report</h1>
            <h2>{period['month_name']} {period['year']}</h2>
            
            <h2>Performance Summary</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>NAV (Start)</td><td>${perf['nav_start']:,.2f}</td></tr>
                <tr><td>NAV (End)</td><td>${perf['nav_end']:,.2f}</td></tr>
                <tr><td>Monthly Return</td><td class="metric {'positive' if perf['monthly_return_pct'] > 0 else 'negative'}">{perf['monthly_return_pct']:.2f}%</td></tr>
                <tr><td>Win Rate</td><td>{perf['win_rate_pct']:.1f}%</td></tr>
            </table>
            
            <h2>Risk Metrics</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Sharpe Ratio</td><td class="metric">{risk['sharpe_ratio']:.2f}</td></tr>
                <tr><td>Max Drawdown (Month)</td><td>{risk['max_drawdown_month_pct']:.2f}%</td></tr>
                <tr><td>Volatility</td><td>{risk['volatility_pct']:.2f}%</td></tr>
            </table>
            
            <p><em>Generated by NIJA Trading Systems on {report['report_date']}</em></p>
        </body>
        </html>
        """
        
        return html


def create_monthly_report(dashboard: PerformanceDashboard,
                         portfolio: StrategyPortfolioManager,
                         year: int, month: int,
                         export_path: Optional[str] = None) -> Dict:
    """
    Convenience function to generate monthly report
    
    Args:
        dashboard: Performance dashboard
        portfolio: Portfolio manager
        year: Report year
        month: Report month
        export_path: Optional export path
    
    Returns:
        Monthly report dictionary
    """
    generator = MonthlyInvestorReportGenerator(dashboard, portfolio)
    
    report = generator.generate_full_report(year, month)
    
    if export_path:
        generator.export_report(year, month, output_dir=export_path)
    
    return report

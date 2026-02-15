"""
NIJA Risk-of-Ruin Probability Model
===================================

Institutional-grade risk-of-ruin calculation using:
- Kelly Criterion optimal sizing
- Gambler's Ruin probability formulas
- Monte Carlo path simulation
- Win rate and payoff ratio analysis
- Drawdown-to-ruin thresholds

This quantifies the probability of account destruction under various scenarios,
enabling capital preservation at institutional standards.

Author: NIJA Trading Systems
Version: 1.0
Date: February 15, 2026
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger("nija.risk_of_ruin")


@dataclass
class RiskOfRuinParameters:
    """Parameters for risk-of-ruin calculation"""
    # Trading statistics
    win_rate: float = 0.55  # Probability of winning trade
    avg_win: float = 1.5  # Average win in R multiples
    avg_loss: float = 1.0  # Average loss in R multiples
    
    # Account parameters
    initial_capital: float = 100000.0
    ruin_threshold_pct: float = 0.50  # Account considered ruined at 50% loss
    position_size_pct: float = 0.02  # Risk per trade as % of capital
    
    # Simulation parameters
    num_trades: int = 1000
    num_simulations: int = 10000
    
    # Risk parameters
    max_consecutive_losses: int = 10  # Psychological limit
    daily_loss_limit_pct: float = 0.05  # Max 5% daily loss
    
    def __post_init__(self):
        """Validate parameters"""
        assert 0 < self.win_rate < 1, "Win rate must be between 0 and 1"
        assert self.avg_win > 0, "Average win must be positive"
        assert self.avg_loss > 0, "Average loss must be positive"
        assert 0 < self.position_size_pct < 1, "Position size must be between 0 and 1"
        assert 0 < self.ruin_threshold_pct < 1, "Ruin threshold must be between 0 and 1"


@dataclass
class RiskOfRuinResult:
    """Results from risk-of-ruin analysis"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Input parameters
    parameters: RiskOfRuinParameters = None
    
    # Theoretical calculations
    theoretical_ruin_probability: float = 0.0
    kelly_criterion_pct: float = 0.0
    kelly_half_pct: float = 0.0
    expectancy: float = 0.0
    payoff_ratio: float = 0.0
    
    # Monte Carlo results
    simulated_ruin_probability: float = 0.0
    mean_final_capital: float = 0.0
    median_final_capital: float = 0.0
    percentile_5_capital: float = 0.0
    percentile_95_capital: float = 0.0
    max_drawdown_mean: float = 0.0
    max_drawdown_worst: float = 0.0
    
    # Consecutive loss analysis
    max_consecutive_losses_observed: int = 0
    prob_exceed_max_consecutive_losses: float = 0.0
    
    # Regime-specific risks
    bull_market_ruin_prob: float = 0.0
    bear_market_ruin_prob: float = 0.0
    high_volatility_ruin_prob: float = 0.0
    
    # Recommendations
    recommended_position_size_pct: float = 0.0
    risk_rating: str = "UNKNOWN"  # LOW, MODERATE, HIGH, EXTREME
    warnings: List[str] = field(default_factory=list)


class RiskOfRuinEngine:
    """
    Risk-of-Ruin probability calculation engine
    
    Implements multiple methods:
    1. Theoretical gambler's ruin formula
    2. Kelly Criterion optimal sizing
    3. Monte Carlo simulation
    4. Regime-specific analysis
    """
    
    def __init__(self, params: Optional[RiskOfRuinParameters] = None):
        """
        Initialize Risk-of-Ruin Engine
        
        Args:
            params: Risk-of-ruin parameters
        """
        self.params = params or RiskOfRuinParameters()
        
        logger.info("=" * 70)
        logger.info("💀 Risk-of-Ruin Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Win Rate: {self.params.win_rate*100:.2f}%")
        logger.info(f"Avg Win: {self.params.avg_win:.2f}R")
        logger.info(f"Avg Loss: {self.params.avg_loss:.2f}R")
        logger.info(f"Position Size: {self.params.position_size_pct*100:.2f}%")
        logger.info(f"Ruin Threshold: {self.params.ruin_threshold_pct*100:.0f}% loss")
        logger.info("=" * 70)
    
    def calculate_expectancy(self) -> float:
        """
        Calculate trading expectancy (expected value per trade)
        
        Formula: Expectancy = (Win% × AvgWin) - (Loss% × AvgLoss)
        
        Returns:
            Expectancy in R multiples
        """
        win_expectancy = self.params.win_rate * self.params.avg_win
        loss_expectancy = (1 - self.params.win_rate) * self.params.avg_loss
        expectancy = win_expectancy - loss_expectancy
        
        logger.info(f"Expectancy: {expectancy:.4f}R per trade")
        return expectancy
    
    def calculate_kelly_criterion(self) -> Tuple[float, float]:
        """
        Calculate Kelly Criterion optimal position size
        
        Kelly% = (Win% × PayoffRatio - Loss%) / PayoffRatio
        
        Where PayoffRatio = AvgWin / AvgLoss
        
        Returns:
            Tuple of (kelly_pct, half_kelly_pct)
        """
        payoff_ratio = self.params.avg_win / self.params.avg_loss
        loss_rate = 1 - self.params.win_rate
        
        # Kelly formula
        kelly_pct = (self.params.win_rate * payoff_ratio - loss_rate) / payoff_ratio
        
        # Ensure non-negative
        kelly_pct = max(0.0, kelly_pct)
        
        # Half Kelly (recommended for real trading)
        half_kelly = kelly_pct / 2
        
        logger.info(f"Kelly Criterion: {kelly_pct*100:.2f}%")
        logger.info(f"Half Kelly (Recommended): {half_kelly*100:.2f}%")
        
        return kelly_pct, half_kelly
    
    def calculate_theoretical_ruin_probability(self) -> float:
        """
        Calculate theoretical risk-of-ruin using gambler's ruin formula
        
        For positive expectancy:
        P(ruin) = ((q/p)^a - (q/p)^(a+b)) / (1 - (q/p)^(a+b))
        
        Where:
        - p = win probability
        - q = loss probability  
        - a = starting units
        - b = units needed to reach goal
        
        Simplified for infinite goal (trading):
        P(ruin) = (q/p)^a if p > q
        P(ruin) = 1 if p <= q
        
        Returns:
            Probability of ruin (0-1)
        """
        p = self.params.win_rate
        q = 1 - p
        
        # Calculate units (account units before ruin)
        # If we risk 2% per trade and ruin is at 50% loss, we have 25 losing units
        units = self.params.ruin_threshold_pct / self.params.position_size_pct
        
        if p <= q:
            # Negative expectancy = certain ruin
            ruin_prob = 1.0
            logger.warning("⚠️ NEGATIVE EXPECTANCY: Ruin is certain with enough trades")
        else:
            # Positive expectancy
            ratio = q / p
            ruin_prob = ratio ** units
        
        logger.info(f"Theoretical Ruin Probability: {ruin_prob:.4%}")
        logger.info(f"Units to ruin: {units:.1f}")
        
        return ruin_prob
    
    def simulate_trading_sequence(self, regime: str = "normal") -> Tuple[float, int, float]:
        """
        Simulate a single trading sequence
        
        Args:
            regime: Market regime ("normal", "bull", "bear", "high_vol")
        
        Returns:
            Tuple of (final_capital, max_consecutive_losses, max_drawdown_pct)
        """
        capital = self.params.initial_capital
        ruin_threshold = self.params.initial_capital * (1 - self.params.ruin_threshold_pct)
        
        peak_capital = capital
        max_drawdown = 0.0
        consecutive_losses = 0
        max_consecutive_losses = 0
        
        # Adjust parameters based on regime
        if regime == "bull":
            win_rate = min(0.95, self.params.win_rate * 1.1)
            avg_win = self.params.avg_win * 1.2
            avg_loss = self.params.avg_loss * 0.9
        elif regime == "bear":
            win_rate = max(0.05, self.params.win_rate * 0.9)
            avg_win = self.params.avg_win * 0.9
            avg_loss = self.params.avg_loss * 1.1
        elif regime == "high_vol":
            win_rate = self.params.win_rate
            avg_win = self.params.avg_win * 1.3
            avg_loss = self.params.avg_loss * 1.3
        else:  # normal
            win_rate = self.params.win_rate
            avg_win = self.params.avg_win
            avg_loss = self.params.avg_loss
        
        for trade_num in range(self.params.num_trades):
            if capital <= ruin_threshold:
                # Account ruined
                return capital, max_consecutive_losses, max_drawdown
            
            # Calculate risk amount
            risk_amount = capital * self.params.position_size_pct
            
            # Determine win/loss
            is_win = np.random.random() < win_rate
            
            if is_win:
                # Win: gain = risk_amount * avg_win
                gain = risk_amount * avg_win
                capital += gain
                consecutive_losses = 0
            else:
                # Loss: lose = risk_amount * avg_loss
                loss = risk_amount * avg_loss
                capital -= loss
                consecutive_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            
            # Track drawdown
            if capital > peak_capital:
                peak_capital = capital
            
            drawdown = (peak_capital - capital) / peak_capital * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        return capital, max_consecutive_losses, max_drawdown
    
    def run_monte_carlo_simulation(self) -> Dict[str, float]:
        """
        Run Monte Carlo simulation to estimate risk-of-ruin
        
        Returns:
            Dictionary with simulation results
        """
        logger.info(f"🎲 Running {self.params.num_simulations:,} Monte Carlo simulations...")
        
        # Track results
        ruined_count = 0
        final_capitals = []
        max_consecutive_losses_list = []
        max_drawdowns = []
        
        # Run normal regime simulations
        for i in range(self.params.num_simulations):
            final_capital, max_consec_losses, max_dd = self.simulate_trading_sequence("normal")
            
            if final_capital <= self.params.initial_capital * (1 - self.params.ruin_threshold_pct):
                ruined_count += 1
            
            final_capitals.append(final_capital)
            max_consecutive_losses_list.append(max_consec_losses)
            max_drawdowns.append(max_dd)
        
        # Calculate statistics
        ruin_prob = ruined_count / self.params.num_simulations
        mean_final = np.mean(final_capitals)
        median_final = np.median(final_capitals)
        p5 = np.percentile(final_capitals, 5)
        p95 = np.percentile(final_capitals, 95)
        max_dd_mean = np.mean(max_drawdowns)
        max_dd_worst = np.max(max_drawdowns)
        max_consec_losses = int(np.max(max_consecutive_losses_list))
        
        # Probability of exceeding max consecutive losses threshold
        prob_exceed_max = np.sum(np.array(max_consecutive_losses_list) > self.params.max_consecutive_losses) / self.params.num_simulations
        
        logger.info(f"✅ Simulation complete")
        logger.info(f"   Ruin Probability: {ruin_prob:.2%}")
        logger.info(f"   Mean Final Capital: ${mean_final:,.2f}")
        logger.info(f"   Max Consecutive Losses: {max_consec_losses}")
        
        return {
            'ruin_probability': ruin_prob,
            'mean_final_capital': mean_final,
            'median_final_capital': median_final,
            'percentile_5': p5,
            'percentile_95': p95,
            'max_drawdown_mean': max_dd_mean,
            'max_drawdown_worst': max_dd_worst,
            'max_consecutive_losses': max_consec_losses,
            'prob_exceed_max_consecutive_losses': prob_exceed_max
        }
    
    def analyze_regime_risks(self) -> Dict[str, float]:
        """
        Analyze risk-of-ruin under different market regimes
        
        Returns:
            Dictionary with regime-specific ruin probabilities
        """
        logger.info("📊 Analyzing regime-specific risks...")
        
        regimes = ["bull", "bear", "high_vol"]
        regime_results = {}
        
        for regime in regimes:
            ruined_count = 0
            
            # Run simulations for this regime
            num_sims = max(1000, self.params.num_simulations // 5)  # Fewer sims per regime
            
            for _ in range(num_sims):
                final_capital, _, _ = self.simulate_trading_sequence(regime)
                if final_capital <= self.params.initial_capital * (1 - self.params.ruin_threshold_pct):
                    ruined_count += 1
            
            regime_prob = ruined_count / num_sims
            regime_results[regime] = regime_prob
            logger.info(f"   {regime.upper()}: {regime_prob:.2%} ruin probability")
        
        return regime_results
    
    def generate_risk_rating(self, result: RiskOfRuinResult) -> str:
        """
        Generate risk rating based on ruin probability
        
        Args:
            result: RiskOfRuinResult
        
        Returns:
            Risk rating string
        """
        ruin_prob = result.simulated_ruin_probability
        
        if ruin_prob < 0.01:
            return "LOW"
        elif ruin_prob < 0.05:
            return "MODERATE"
        elif ruin_prob < 0.15:
            return "HIGH"
        else:
            return "EXTREME"
    
    def generate_warnings(self, result: RiskOfRuinResult) -> List[str]:
        """
        Generate warnings based on analysis
        
        Args:
            result: RiskOfRuinResult
        
        Returns:
            List of warning strings
        """
        warnings = []
        
        # Check ruin probability
        if result.simulated_ruin_probability > 0.10:
            warnings.append(f"⚠️ High ruin probability: {result.simulated_ruin_probability:.2%}")
        
        # Check position sizing vs Kelly
        if result.parameters.position_size_pct > result.kelly_criterion_pct:
            warnings.append(f"⚠️ Position size ({result.parameters.position_size_pct*100:.2f}%) exceeds Kelly ({result.kelly_criterion_pct*100:.2f}%)")
        
        # Check expectancy
        if result.expectancy <= 0:
            warnings.append("🚨 NEGATIVE EXPECTANCY: Strategy has no edge")
        
        # Check consecutive losses
        if result.max_consecutive_losses_observed > self.params.max_consecutive_losses:
            warnings.append(f"⚠️ Max consecutive losses ({result.max_consecutive_losses_observed}) exceeds threshold ({self.params.max_consecutive_losses})")
        
        # Check regime risks
        if result.bear_market_ruin_prob > 0.20:
            warnings.append(f"⚠️ High bear market risk: {result.bear_market_ruin_prob:.2%}")
        
        if result.high_volatility_ruin_prob > 0.15:
            warnings.append(f"⚠️ High volatility risk: {result.high_volatility_ruin_prob:.2%}")
        
        return warnings
    
    def calculate_recommended_position_size(self, kelly_pct: float, expectancy: float) -> float:
        """
        Calculate recommended position size
        
        Uses Half Kelly as baseline, adjusted for expectancy
        
        Args:
            kelly_pct: Kelly Criterion percentage
            expectancy: Trading expectancy
        
        Returns:
            Recommended position size percentage
        """
        # Start with Half Kelly
        recommended = kelly_pct / 2
        
        # Further reduce if expectancy is low
        if expectancy < 0.1:
            recommended *= 0.75
        
        # Cap at 5% for safety
        recommended = min(0.05, recommended)
        
        # Floor at 0.5% 
        recommended = max(0.005, recommended)
        
        return recommended
    
    def analyze(self) -> RiskOfRuinResult:
        """
        Complete risk-of-ruin analysis
        
        Returns:
            RiskOfRuinResult with all metrics
        """
        logger.info("\n" + "=" * 70)
        logger.info("💀 RISK-OF-RUIN ANALYSIS")
        logger.info("=" * 70)
        
        # Calculate expectancy
        expectancy = self.calculate_expectancy()
        payoff_ratio = self.params.avg_win / self.params.avg_loss
        
        # Calculate Kelly
        kelly_pct, half_kelly = self.calculate_kelly_criterion()
        
        # Theoretical ruin probability
        theoretical_ruin = self.calculate_theoretical_ruin_probability()
        
        # Monte Carlo simulation
        mc_results = self.run_monte_carlo_simulation()
        
        # Regime analysis
        regime_risks = self.analyze_regime_risks()
        
        # Build result
        result = RiskOfRuinResult(
            parameters=self.params,
            theoretical_ruin_probability=theoretical_ruin,
            kelly_criterion_pct=kelly_pct,
            kelly_half_pct=half_kelly,
            expectancy=expectancy,
            payoff_ratio=payoff_ratio,
            simulated_ruin_probability=mc_results['ruin_probability'],
            mean_final_capital=mc_results['mean_final_capital'],
            median_final_capital=mc_results['median_final_capital'],
            percentile_5_capital=mc_results['percentile_5'],
            percentile_95_capital=mc_results['percentile_95'],
            max_drawdown_mean=mc_results['max_drawdown_mean'],
            max_drawdown_worst=mc_results['max_drawdown_worst'],
            max_consecutive_losses_observed=mc_results['max_consecutive_losses'],
            prob_exceed_max_consecutive_losses=mc_results['prob_exceed_max_consecutive_losses'],
            bull_market_ruin_prob=regime_risks.get('bull', 0.0),
            bear_market_ruin_prob=regime_risks.get('bear', 0.0),
            high_volatility_ruin_prob=regime_risks.get('high_vol', 0.0),
        )
        
        # Calculate recommended position size
        result.recommended_position_size_pct = self.calculate_recommended_position_size(kelly_pct, expectancy)
        
        # Generate risk rating
        result.risk_rating = self.generate_risk_rating(result)
        
        # Generate warnings
        result.warnings = self.generate_warnings(result)
        
        # Log results
        self._log_results(result)
        
        return result
    
    def _log_results(self, result: RiskOfRuinResult) -> None:
        """Log analysis results"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 RISK-OF-RUIN RESULTS")
        logger.info("=" * 70)
        logger.info("\n📈 Trading Statistics:")
        logger.info(f"  Expectancy: {result.expectancy:.4f}R")
        logger.info(f"  Payoff Ratio: {result.payoff_ratio:.2f}")
        logger.info(f"  Win Rate: {result.parameters.win_rate*100:.2f}%")
        
        logger.info("\n💀 Ruin Probabilities:")
        logger.info(f"  Theoretical: {result.theoretical_ruin_probability:.4%}")
        logger.info(f"  Monte Carlo: {result.simulated_ruin_probability:.4%}")
        logger.info(f"  Risk Rating: {result.risk_rating}")
        
        logger.info("\n📊 Regime-Specific Risks:")
        logger.info(f"  Bull Market: {result.bull_market_ruin_prob:.2%}")
        logger.info(f"  Bear Market: {result.bear_market_ruin_prob:.2%}")
        logger.info(f"  High Volatility: {result.high_volatility_ruin_prob:.2%}")
        
        logger.info("\n⚖️  Position Sizing:")
        logger.info(f"  Kelly Criterion: {result.kelly_criterion_pct*100:.2f}%")
        logger.info(f"  Half Kelly: {result.kelly_half_pct*100:.2f}%")
        logger.info(f"  Current Size: {result.parameters.position_size_pct*100:.2f}%")
        logger.info(f"  Recommended: {result.recommended_position_size_pct*100:.2f}%")
        
        logger.info("\n📉 Drawdown Analysis:")
        logger.info(f"  Mean Max DD: {result.max_drawdown_mean:.2f}%")
        logger.info(f"  Worst DD: {result.max_drawdown_worst:.2f}%")
        logger.info(f"  Max Consecutive Losses: {result.max_consecutive_losses_observed}")
        
        if result.warnings:
            logger.info("\n⚠️  WARNINGS:")
            for warning in result.warnings:
                logger.info(f"  {warning}")
        
        logger.info("=" * 70)
    
    def export_results(self, result: RiskOfRuinResult, output_dir: str = "./data/risk_analysis") -> str:
        """
        Export results to JSON
        
        Args:
            result: RiskOfRuinResult
            output_dir: Output directory
        
        Returns:
            Path to exported file
        """
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"risk_of_ruin_{timestamp}.json"
        filepath = output_path / filename
        
        # Prepare export data
        export_data = {
            'timestamp': result.timestamp,
            'parameters': {
                'win_rate': result.parameters.win_rate,
                'avg_win': result.parameters.avg_win,
                'avg_loss': result.parameters.avg_loss,
                'position_size_pct': result.parameters.position_size_pct,
                'ruin_threshold_pct': result.parameters.ruin_threshold_pct
            },
            'analysis': {
                'expectancy': result.expectancy,
                'payoff_ratio': result.payoff_ratio,
                'theoretical_ruin_probability': result.theoretical_ruin_probability,
                'simulated_ruin_probability': result.simulated_ruin_probability,
                'risk_rating': result.risk_rating
            },
            'kelly': {
                'kelly_criterion_pct': result.kelly_criterion_pct,
                'kelly_half_pct': result.kelly_half_pct,
                'recommended_position_size_pct': result.recommended_position_size_pct
            },
            'regime_risks': {
                'bull_market': result.bull_market_ruin_prob,
                'bear_market': result.bear_market_ruin_prob,
                'high_volatility': result.high_volatility_ruin_prob
            },
            'warnings': result.warnings
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"📄 Results exported to: {filepath}")
        
        return str(filepath)


def analyze_risk_of_ruin(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    position_size_pct: float = 0.02,
    initial_capital: float = 100000.0
) -> RiskOfRuinResult:
    """
    Convenience function to analyze risk-of-ruin
    
    Args:
        win_rate: Probability of winning trade (0-1)
        avg_win: Average win in R multiples
        avg_loss: Average loss in R multiples
        position_size_pct: Position size as % of capital
        initial_capital: Starting capital
    
    Returns:
        RiskOfRuinResult
    """
    params = RiskOfRuinParameters(
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        position_size_pct=position_size_pct,
        initial_capital=initial_capital
    )
    
    engine = RiskOfRuinEngine(params)
    result = engine.analyze()
    engine.export_results(result)
    
    return result


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Example 1: Conservative strategy
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Conservative Strategy")
    print("=" * 70)
    
    result1 = analyze_risk_of_ruin(
        win_rate=0.60,
        avg_win=1.5,
        avg_loss=1.0,
        position_size_pct=0.02,
        initial_capital=100000.0
    )
    
    # Example 2: Aggressive strategy
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Aggressive Strategy")
    print("=" * 70)
    
    result2 = analyze_risk_of_ruin(
        win_rate=0.45,
        avg_win=2.5,
        avg_loss=1.0,
        position_size_pct=0.05,
        initial_capital=100000.0
    )

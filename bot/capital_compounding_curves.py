"""
NIJA Capital Compounding Curves Designer
=========================================

Designs and implements exponential capital growth curves with:
1. Milestone-based acceleration
2. Kelly Criterion optimization
3. Drawdown-aware compounding
4. Progressive position sizing
5. Risk scaling based on equity growth

Creates institutional-grade compounding strategies that maximize growth
while managing risk appropriately.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import numpy as np
import math
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("nija.compounding_curves")


class CompoundingCurve(Enum):
    """Compounding curve types"""
    LINEAR = "linear"  # Constant reinvestment rate
    EXPONENTIAL = "exponential"  # Accelerating reinvestment
    LOGARITHMIC = "logarithmic"  # Decelerating reinvestment (safety-first)
    S_CURVE = "s_curve"  # Slow start, rapid middle, slow end
    KELLY_OPTIMIZED = "kelly_optimized"  # Optimal bet sizing


@dataclass
class MilestoneTarget:
    """Capital milestone definition"""
    name: str
    target_amount: float
    reinvest_pct: float  # % to reinvest after reaching
    position_size_multiplier: float  # Position size adjustment
    risk_tolerance: float  # Risk tolerance adjustment (0.5-2.0)
    celebration_message: str = ""
    achieved: bool = False
    achieved_date: Optional[datetime] = None


@dataclass
class CompoundingCurveConfig:
    """Configuration for compounding curves"""
    curve_type: CompoundingCurve = CompoundingCurve.KELLY_OPTIMIZED
    
    # Base compounding parameters
    initial_reinvest_pct: float = 0.75  # Start at 75% reinvestment
    max_reinvest_pct: float = 0.95  # Cap at 95% reinvestment
    min_reinvest_pct: float = 0.50  # Floor at 50% reinvestment
    
    # Acceleration parameters
    enable_milestone_acceleration: bool = True
    acceleration_factor: float = 1.1  # 10% increase per milestone
    
    # Risk scaling
    enable_equity_risk_scaling: bool = True
    min_position_multiplier: float = 0.5
    max_position_multiplier: float = 3.0
    
    # Drawdown protection
    enable_drawdown_deceleration: bool = True
    drawdown_threshold: float = 0.10  # 10% drawdown triggers deceleration
    drawdown_multiplier: float = 0.5  # Reduce compounding by 50% in drawdown
    
    # Kelly optimization
    kelly_fraction: float = 0.25  # Use 25% of full Kelly
    kelly_min_trades: int = 20  # Minimum trades before using Kelly


class CapitalCompoundingCurvesDesigner:
    """
    Designs and manages capital growth curves optimized for exponential growth
    
    Key Features:
    1. Multiple curve types for different risk profiles
    2. Milestone-based acceleration (compound more as you grow)
    3. Kelly Criterion for optimal bet sizing
    4. Automatic drawdown deceleration
    5. Progressive position sizing with equity growth
    """
    
    def __init__(self, base_capital: float,
                 config: Optional[CompoundingCurveConfig] = None):
        """
        Initialize Capital Compounding Curves Designer
        
        Args:
            base_capital: Starting capital
            config: Compounding curve configuration
        """
        self.config = config or CompoundingCurveConfig()
        self.base_capital = base_capital
        self.current_capital = base_capital
        self.peak_capital = base_capital
        
        # Milestones
        self.milestones: List[MilestoneTarget] = self._create_default_milestones()
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0.0
        self.total_fees = 0.0
        
        # Kelly parameters
        self.win_rate = 0.50
        self.avg_win = 1.0
        self.avg_loss = 1.0
        
        # Current state
        self.current_reinvest_pct = self.config.initial_reinvest_pct
        self.current_position_multiplier = 1.0
        
        logger.info("=" * 70)
        logger.info("📈 Capital Compounding Curves Designer Initialized")
        logger.info("=" * 70)
        logger.info(f"Base Capital: ${self.base_capital:,.2f}")
        logger.info(f"Curve Type: {self.config.curve_type.value}")
        logger.info(f"Initial Reinvestment: {self.current_reinvest_pct*100:.0f}%")
        logger.info(f"Milestones: {len(self.milestones)}")
        logger.info("=" * 70)
    
    def _create_default_milestones(self) -> List[MilestoneTarget]:
        """Create default milestone structure"""
        base = self.base_capital
        
        milestones = [
            MilestoneTarget(
                name="First Profit",
                target_amount=base * 1.10,  # 10% profit
                reinvest_pct=0.75,
                position_size_multiplier=1.0,
                risk_tolerance=1.0,
                celebration_message="🎉 First 10% profit achieved!"
            ),
            MilestoneTarget(
                name="Quarter Growth",
                target_amount=base * 1.25,  # 25% profit
                reinvest_pct=0.80,
                position_size_multiplier=1.1,
                risk_tolerance=1.05,
                celebration_message="🎉 25% growth achieved!"
            ),
            MilestoneTarget(
                name="Half Growth",
                target_amount=base * 1.50,  # 50% profit
                reinvest_pct=0.85,
                position_size_multiplier=1.2,
                risk_tolerance=1.10,
                celebration_message="🚀 50% growth achieved!"
            ),
            MilestoneTarget(
                name="Double",
                target_amount=base * 2.0,  # 100% profit
                reinvest_pct=0.90,
                position_size_multiplier=1.3,
                risk_tolerance=1.15,
                celebration_message="🎆 Capital DOUBLED!"
            ),
            MilestoneTarget(
                name="Triple",
                target_amount=base * 3.0,  # 200% profit
                reinvest_pct=0.92,
                position_size_multiplier=1.5,
                risk_tolerance=1.20,
                celebration_message="💎 Capital TRIPLED!"
            ),
            MilestoneTarget(
                name="5x Growth",
                target_amount=base * 5.0,  # 400% profit
                reinvest_pct=0.95,
                position_size_multiplier=1.8,
                risk_tolerance=1.25,
                celebration_message="🏆 5X GROWTH ACHIEVED!"
            ),
            MilestoneTarget(
                name="10x Growth",
                target_amount=base * 10.0,  # 900% profit
                reinvest_pct=0.95,
                position_size_multiplier=2.0,
                risk_tolerance=1.30,
                celebration_message="👑 10X GROWTH - LEGENDARY!"
            ),
        ]
        
        return milestones
    
    def calculate_compound_projection(
        self, days: int, avg_daily_return_pct: float,
        win_rate: Optional[float] = None
    ) -> Dict:
        """
        Project capital growth over time using compound curve
        
        Args:
            days: Number of days to project
            avg_daily_return_pct: Average daily return percentage
            win_rate: Win rate for Kelly optimization (optional)
        
        Returns:
            Dictionary with projection details
        """
        projections = []
        capital = self.current_capital
        
        if win_rate:
            self.win_rate = win_rate
        
        for day in range(days + 1):
            # Calculate reinvestment rate for this day
            reinvest_pct = self._calculate_reinvest_rate(capital, day, days)
            
            # Calculate position multiplier
            position_mult = self._calculate_position_multiplier(capital)
            
            # Calculate growth for the day
            daily_return = avg_daily_return_pct / 100
            
            # Apply position multiplier to returns
            adjusted_return = daily_return * position_mult
            
            # Calculate new capital
            profit = capital * adjusted_return
            reinvested = profit * reinvest_pct
            capital += reinvested
            
            # Check for milestones
            milestone_reached = self._check_milestones(capital)
            
            projections.append({
                'day': day,
                'capital': capital,
                'profit': profit,
                'reinvested': reinvested,
                'reinvest_pct': reinvest_pct,
                'position_mult': position_mult,
                'milestone': milestone_reached,
            })
        
        # Calculate summary statistics
        final_capital = projections[-1]['capital']
        total_growth = final_capital - self.current_capital
        growth_pct = (total_growth / self.current_capital) * 100
        
        # Calculate CAGR
        years = days / 365.0
        cagr = ((final_capital / self.current_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
        
        return {
            'projections': projections,
            'final_capital': final_capital,
            'total_growth': total_growth,
            'growth_pct': growth_pct,
            'cagr': cagr,
            'days': days,
            'start_capital': self.current_capital,
        }
    
    def _calculate_reinvest_rate(
        self, current_capital: float, current_day: int, total_days: int
    ) -> float:
        """Calculate reinvestment rate based on curve type and progress"""
        # Get base rate from curve
        if self.config.curve_type == CompoundingCurve.LINEAR:
            rate = self.config.initial_reinvest_pct
        
        elif self.config.curve_type == CompoundingCurve.EXPONENTIAL:
            # Exponential: y = initial * e^(k*x)
            progress = current_day / total_days
            k = 0.5  # Growth rate
            rate = self.config.initial_reinvest_pct * math.exp(k * progress)
        
        elif self.config.curve_type == CompoundingCurve.LOGARITHMIC:
            # Logarithmic: y = initial + k * log(x + 1)
            progress = current_day / total_days
            k = 0.2
            rate = self.config.initial_reinvest_pct + k * math.log(progress + 1)
        
        elif self.config.curve_type == CompoundingCurve.S_CURVE:
            # Sigmoid S-curve: y = 1 / (1 + e^(-k*(x - 0.5)))
            progress = current_day / total_days
            k = 10  # Steepness
            sigmoid = 1 / (1 + math.exp(-k * (progress - 0.5)))
            rate = (
                self.config.initial_reinvest_pct +
                (self.config.max_reinvest_pct - self.config.initial_reinvest_pct) * sigmoid
            )
        
        elif self.config.curve_type == CompoundingCurve.KELLY_OPTIMIZED:
            # Use Kelly Criterion if enough data
            if self.total_trades >= self.config.kelly_min_trades:
                kelly_pct = self._calculate_kelly_criterion()
                rate = kelly_pct * self.config.kelly_fraction
            else:
                rate = self.config.initial_reinvest_pct
        
        else:
            rate = self.config.initial_reinvest_pct
        
        # Apply milestone acceleration
        if self.config.enable_milestone_acceleration:
            milestones_achieved = sum(1 for m in self.milestones if m.achieved)
            acceleration = self.config.acceleration_factor ** milestones_achieved
            rate *= acceleration
        
        # Apply drawdown deceleration
        if self.config.enable_drawdown_deceleration:
            drawdown = (self.peak_capital - current_capital) / self.peak_capital
            if drawdown >= self.config.drawdown_threshold:
                rate *= self.config.drawdown_multiplier
        
        # Ensure within bounds
        rate = max(min(rate, self.config.max_reinvest_pct), self.config.min_reinvest_pct)
        
        return rate
    
    def _calculate_position_multiplier(self, current_capital: float) -> float:
        """Calculate position size multiplier based on equity growth"""
        if not self.config.enable_equity_risk_scaling:
            return 1.0
        
        # Calculate equity growth factor
        growth_factor = current_capital / self.base_capital
        
        # Square root scaling (conservative)
        # If capital doubles, position increases by sqrt(2) = 1.41x
        multiplier = math.sqrt(growth_factor)
        
        # Get milestone-based multiplier
        current_milestone = self._get_current_milestone()
        if current_milestone:
            milestone_mult = current_milestone.position_size_multiplier
            multiplier *= milestone_mult
        
        # Apply drawdown reduction
        drawdown = (self.peak_capital - current_capital) / self.peak_capital
        if drawdown >= self.config.drawdown_threshold:
            multiplier *= 0.7  # Reduce by 30% in drawdown
        
        # Ensure within bounds
        multiplier = max(
            min(multiplier, self.config.max_position_multiplier),
            self.config.min_position_multiplier
        )
        
        return multiplier
    
    def _calculate_kelly_criterion(self) -> float:
        """
        Calculate Kelly Criterion percentage
        
        Kelly % = (Win% * Avg_Win - Loss% * Avg_Loss) / Avg_Loss
        """
        if self.total_trades < self.config.kelly_min_trades:
            return self.config.initial_reinvest_pct
        
        win_pct = self.win_rate
        loss_pct = 1.0 - win_pct
        
        kelly = (win_pct * self.avg_win - loss_pct * self.avg_loss) / self.avg_loss
        
        # Ensure positive and reasonable
        kelly = max(0.0, min(kelly, 1.0))
        
        return kelly
    
    def _check_milestones(self, current_capital: float) -> Optional[str]:
        """Check if any milestones have been reached"""
        for milestone in self.milestones:
            if not milestone.achieved and current_capital >= milestone.target_amount:
                milestone.achieved = True
                milestone.achieved_date = datetime.now()
                
                # Update compounding parameters
                self.current_reinvest_pct = milestone.reinvest_pct
                self.current_position_multiplier = milestone.position_size_multiplier
                
                logger.info("=" * 70)
                logger.info(f"{milestone.celebration_message}")
                logger.info(f"💰 Capital: ${current_capital:,.2f}")
                logger.info(f"📈 Reinvestment increased to {milestone.reinvest_pct*100:.0f}%")
                logger.info(f"📊 Position sizing increased to {milestone.position_size_multiplier:.2f}x")
                logger.info("=" * 70)
                
                return milestone.name
        
        return None
    
    def _get_current_milestone(self) -> Optional[MilestoneTarget]:
        """Get the most recent achieved milestone"""
        achieved = [m for m in self.milestones if m.achieved]
        return achieved[-1] if achieved else None
    
    def update_capital(self, new_capital: float):
        """Update current capital and check milestones"""
        self.current_capital = new_capital
        
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital
        
        self._check_milestones(new_capital)
    
    def record_trade(self, profit: float, fees: float, is_win: bool):
        """Record trade for Kelly Criterion calculation"""
        self.total_trades += 1
        
        if is_win:
            self.winning_trades += 1
        
        self.total_profit += profit
        self.total_fees += fees
        
        # Update Kelly parameters (guard against division by zero)
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
        
        # Update average win/loss (exponential moving average)
        alpha = 0.1
        if is_win and profit > 0:
            r_multiple = profit / (self.base_capital * 0.01) if self.base_capital > 0 else profit  # Assuming 1% risk
            self.avg_win = (1 - alpha) * self.avg_win + alpha * r_multiple
        elif not is_win and profit < 0:
            r_multiple = abs(profit) / (self.base_capital * 0.01) if self.base_capital > 0 else abs(profit)
            self.avg_loss = (1 - alpha) * self.avg_loss + alpha * r_multiple
    
    def get_current_parameters(self) -> Dict:
        """Get current compounding parameters"""
        return {
            'current_capital': self.current_capital,
            'base_capital': self.base_capital,
            'peak_capital': self.peak_capital,
            'reinvest_pct': self.current_reinvest_pct,
            'position_multiplier': self.current_position_multiplier,
            'win_rate': self.win_rate,
            'kelly_criterion': self._calculate_kelly_criterion() if self.total_trades >= self.config.kelly_min_trades else None,
            'milestones_achieved': sum(1 for m in self.milestones if m.achieved),
            'next_milestone': self._get_next_milestone(),
        }
    
    def _get_next_milestone(self) -> Optional[Dict]:
        """Get next unachieved milestone"""
        for milestone in self.milestones:
            if not milestone.achieved:
                progress_pct = (self.current_capital / milestone.target_amount) * 100
                remaining = milestone.target_amount - self.current_capital
                return {
                    'name': milestone.name,
                    'target': milestone.target_amount,
                    'progress_pct': progress_pct,
                    'remaining': remaining,
                }
        return None
    
    def generate_growth_report(self) -> str:
        """Generate comprehensive growth report"""
        params = self.get_current_parameters()
        
        report = [
            "\n" + "=" * 90,
            "CAPITAL COMPOUNDING CURVES - GROWTH REPORT",
            "=" * 90,
            f"Curve Type: {self.config.curve_type.value.upper()}",
            ""
        ]
        
        # Current status
        growth = self.current_capital - self.base_capital
        growth_pct = (growth / self.base_capital) * 100
        
        report.extend([
            "💰 CURRENT STATUS",
            "-" * 90,
            f"  Base Capital:         ${self.base_capital:>12,.2f}",
            f"  Current Capital:      ${self.current_capital:>12,.2f}",
            f"  Peak Capital:         ${self.peak_capital:>12,.2f}",
            f"  Total Growth:         ${growth:>12,.2f} ({growth_pct:>6.2f}%)",
            ""
        ])
        
        # Compounding parameters
        report.extend([
            "⚙️  COMPOUNDING PARAMETERS",
            "-" * 90,
            f"  Reinvestment Rate:    {self.current_reinvest_pct*100:>12.0f}%",
            f"  Position Multiplier:  {self.current_position_multiplier:>12.2f}x",
        ])
        
        if params['kelly_criterion']:
            report.append(f"  Kelly Criterion:      {params['kelly_criterion']*100:>12.1f}%")
        
        report.append("")
        
        # Milestones
        report.extend([
            "🎯 MILESTONES",
            "-" * 90,
            f"  Achieved: {params['milestones_achieved']}/{len(self.milestones)}",
            ""
        ])
        
        for milestone in self.milestones:
            if milestone.achieved:
                status = f"✅ {milestone.achieved_date.strftime('%Y-%m-%d')}"
            else:
                progress = (self.current_capital / milestone.target_amount) * 100
                status = f"⏳ {progress:.0f}%"
            
            report.append(
                f"  {milestone.name:20s} ${milestone.target_amount:>12,.2f} {status}"
            )
        
        report.append("")
        
        # Next milestone
        next_ms = params['next_milestone']
        if next_ms:
            report.extend([
                "📍 NEXT MILESTONE",
                "-" * 90,
                f"  Target: {next_ms['name']} at ${next_ms['target']:,.2f}",
                f"  Progress: {next_ms['progress_pct']:.1f}%",
                f"  Remaining: ${next_ms['remaining']:,.2f}",
                ""
            ])
        
        # Performance metrics
        if self.total_trades > 0:
            report.extend([
                "📊 PERFORMANCE METRICS",
                "-" * 90,
                f"  Total Trades:         {self.total_trades:>12,}",
                f"  Win Rate:             {self.win_rate*100:>12.1f}%",
                f"  Average Win:          {self.avg_win:>12.2f}R",
                f"  Average Loss:         {self.avg_loss:>12.2f}R",
                ""
            ])
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)


def create_compounding_curve_designer(
    base_capital: float,
    curve_type: str = "kelly_optimized",
    enable_milestones: bool = True,
    enable_equity_scaling: bool = True
) -> CapitalCompoundingCurvesDesigner:
    """
    Factory function to create CapitalCompoundingCurvesDesigner
    
    Args:
        base_capital: Starting capital
        curve_type: Type of compounding curve
        enable_milestones: Enable milestone-based acceleration
        enable_equity_scaling: Enable equity-based risk scaling
    
    Returns:
        CapitalCompoundingCurvesDesigner instance
    """
    curve_enum = CompoundingCurve(curve_type.lower())
    
    config = CompoundingCurveConfig(
        curve_type=curve_enum,
        enable_milestone_acceleration=enable_milestones,
        enable_equity_risk_scaling=enable_equity_scaling
    )
    
    return CapitalCompoundingCurvesDesigner(base_capital, config)


if __name__ == "__main__":
    # Test/demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create designer
    designer = create_compounding_curve_designer(
        base_capital=10000.0,
        curve_type="kelly_optimized",
        enable_milestones=True,
        enable_equity_scaling=True
    )
    
    print("\n" + "=" * 90)
    print("CAPITAL COMPOUNDING PROJECTION")
    print("=" * 90)
    
    # Project 365 days with 0.5% average daily return
    projection = designer.calculate_compound_projection(
        days=365,
        avg_daily_return_pct=0.5,
        win_rate=0.65
    )
    
    print(f"\nStarting Capital: ${projection['start_capital']:,.2f}")
    print(f"Projected Days: {projection['days']}")
    print(f"Average Daily Return: 0.5%")
    print(f"\n✅ PROJECTED FINAL CAPITAL: ${projection['final_capital']:,.2f}")
    print(f"   Total Growth: ${projection['total_growth']:,.2f} ({projection['growth_pct']:.1f}%)")
    print(f"   CAGR: {projection['cagr']:.1f}%")
    
    # Show key milestones from projection
    print(f"\n📍 Milestones Reached:")
    for p in projection['projections']:
        if p['milestone']:
            print(f"   Day {p['day']}: {p['milestone']} at ${p['capital']:,.2f}")
    
    # Show current parameters
    print(designer.generate_growth_report())

#!/usr/bin/env python3
"""
NIJA Greenlight Report Generator

Generates a scaling greenlight report for a user based on current performance.

Usage:
    python generate_greenlight_report.py --user platform
    python generate_greenlight_report.py --user platform --output report.txt
    python generate_greenlight_report.py --user platform --json > report.json

Author: NIJA Trading Systems
Version: 1.0
Date: February 6, 2026
"""

import argparse
import sys
import json
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

from bot.scaling_greenlight import (
    get_greenlight_system,
    ScalingTier,
    GreenlightCriteria
)
from bot.profit_proven_rule import get_profit_proven_tracker
from controls import get_hard_controls


def get_risk_metrics(user_id: str) -> dict:
    """
    Get risk violation metrics for a user.
    
    Args:
        user_id: User identifier
    
    Returns:
        Dict with risk metrics
    """
    hard_controls = get_hard_controls()
    
    # Get position validation stats
    validation_stats = hard_controls.get_rejection_stats(user_id=user_id)
    
    # Get kill switch and daily limit data
    # Note: These would typically come from tracker - using defaults for now
    kill_switch_triggers = 0
    daily_limit_hits = 0
    
    return {
        'kill_switch_triggers': kill_switch_triggers,
        'daily_limit_hits': daily_limit_hits,
        'position_rejections': validation_stats.get('rejected', 0),
        'total_validations': validation_stats.get('total_validations', 0),
    }


def generate_report(
    user_id: str,
    current_tier: ScalingTier = ScalingTier.MICRO,
    output_file: str = None,
    json_output: bool = False
) -> None:
    """
    Generate and display greenlight report.
    
    Args:
        user_id: User identifier
        current_tier: Current scaling tier
        output_file: Optional output file path
        json_output: Output as JSON instead of text
    """
    print(f"Generating greenlight report for user: {user_id}", file=sys.stderr)
    print(f"Current tier: {current_tier.name}", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Get profit proven tracker
    tracker = get_profit_proven_tracker()
    
    # Check if tracker has data
    if not tracker.trades:
        print("❌ ERROR: No trades recorded yet", file=sys.stderr)
        print("   Record at least one trade before generating greenlight report", file=sys.stderr)
        sys.exit(1)
    
    # Get performance metrics
    print("Calculating performance metrics...", file=sys.stderr)
    is_proven, status, performance_metrics = tracker.check_profit_proven()
    
    # Get risk metrics
    print("Checking risk violations...", file=sys.stderr)
    risk_metrics = get_risk_metrics(user_id)
    
    # Generate greenlight report
    print("Generating greenlight report...", file=sys.stderr)
    greenlight_system = get_greenlight_system()
    report = greenlight_system.generate_greenlight_report(
        user_id=user_id,
        current_tier=current_tier,
        performance_metrics=performance_metrics,
        risk_metrics=risk_metrics
    )
    
    print("", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    
    # Output report
    if json_output:
        output = report.to_json()
    else:
        output = report.to_text_report()
    
    if output_file:
        with open(output_file, 'w') as f:
            f.write(output)
        print(f"✅ Report saved to: {output_file}", file=sys.stderr)
    else:
        print(output)
    
    # Log decision
    if report.all_criteria_met:
        print("", file=sys.stderr)
        print("✅ GREENLIGHT APPROVED - User can scale to next tier", file=sys.stderr)
    else:
        print("", file=sys.stderr)
        print("⏳ TESTING - User should continue at current tier", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Generate NIJA scaling greenlight report'
    )
    parser.add_argument(
        '--user',
        type=str,
        default='platform',
        help='User ID (default: platform)'
    )
    parser.add_argument(
        '--tier',
        type=str,
        choices=['micro', 'small', 'medium', 'large'],
        default='micro',
        help='Current scaling tier (default: micro)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file path (default: stdout)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of text'
    )
    
    args = parser.parse_args()
    
    # Map tier string to enum
    tier_map = {
        'micro': ScalingTier.MICRO,
        'small': ScalingTier.SMALL,
        'medium': ScalingTier.MEDIUM,
        'large': ScalingTier.LARGE,
    }
    current_tier = tier_map[args.tier]
    
    # Generate report
    generate_report(
        user_id=args.user,
        current_tier=current_tier,
        output_file=args.output,
        json_output=args.json
    )


if __name__ == '__main__':
    main()

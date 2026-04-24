# Institutional-Grade Guardrails

**Version**: 1.0  
**Last Updated**: January 31, 2026  
**Purpose**: Production-ready safety controls for algorithmic trading platform

## Overview

This document specifies institutional-grade safety guardrails that protect users, comply with regulations, and maintain platform integrity. These guardrails go beyond basic risk management to implement the silent safeguards that regulators and app reviewers expect.

---

## 1. Enhanced Circuit Breakers

### 1.1 Multi-Layer Circuit Breaker System

**Layer 1: Individual Position Level**
```python
class PositionCircuitBreaker:
    """Protects individual positions from runaway losses"""
    
    # Unrealized loss exceeds threshold
    if position.unrealized_loss_pct > 0.10:  # 10% loss
        trigger = "position_loss_10pct"
        force_close_position(position_id, reason=trigger)
        notify_user("Position closed: 10% loss limit")
    
    # Position held too long without profit
    if position.hours_open > 72 and position.pnl < 0:  # 3 days
        trigger = "stale_losing_position"
        warn_user("Consider closing: 3-day old losing position")
    
    # Sudden adverse movement
    if position.price_change_5min < -0.05:  # 5% drop in 5 minutes
        trigger = "rapid_adverse_movement"
        tighten_stop_loss(position_id, factor=0.5)
        alert_user("Stop-loss tightened: rapid price movement")
```

**Layer 2: Account Level**
```python
class AccountCircuitBreaker:
    """Protects entire account from cascading failures"""
    
    # Total unrealized loss
    if account.total_unrealized_loss_pct > 0.08:  # 8% of account
        trigger = "account_drawdown_8pct"
        halt_new_positions(duration_hours=24)
        suggest_reduce_exposure()
    
    # Too many open positions
    if account.open_positions > account.max_positions * 0.8:  # 80% of limit
        trigger = "position_concentration"
        warn_user("Approaching position limit: reduce concentration")
    
    # Correlation risk
    if account.portfolio_correlation > 0.85:  # High correlation
        trigger = "high_correlation_risk"
        block_similar_positions()
        warn_user("Portfolio too concentrated: diversify")
```

**Layer 3: Platform Level**
```python
class PlatformCircuitBreaker:
    """Protects platform from systemic issues"""
    
    # Abnormal loss rate across users
    if platform.user_loss_rate_1h > 0.70:  # 70% users losing
        trigger = "platform_wide_losses"
        activate_global_review()
        notify_admins("Abnormal loss pattern detected")
    
    # Exchange connectivity issues
    if platform.failed_api_calls_rate > 0.20:  # 20% failure rate
        trigger = "exchange_connectivity"
        pause_new_orders_all_users()
        escalate_to_on_call()
    
    # Unusual trading volume
    if platform.volume_spike > 5.0:  # 5x normal volume
        trigger = "volume_anomaly"
        increase_monitoring()
        review_for_manipulation()
```

### 1.2 Time-Based Circuit Breakers

**Intraday Volatility Protection**
```python
class VolatilityCircuitBreaker:
    """Protects during high volatility periods"""
    
    # Market volatility exceeds threshold
    if market.realized_volatility_1h > historical_avg * 2.5:
        trigger = "elevated_volatility"
        reduce_position_sizes(factor=0.5)
        widen_stop_losses(factor=1.5)
        notify_all_users("High volatility: reduced position sizes")
    
    # Flash crash detection
    if market.price_drop_5min > 0.15:  # 15% in 5 minutes
        trigger = "flash_crash_suspected"
        halt_all_trading(duration_minutes=15)
        await_market_stabilization()
    
    # Weekend/holiday approaching
    if time_to_market_close < 2 * 3600:  # 2 hours to close
        trigger = "approaching_market_close"
        remind_users_to_close_positions()
        auto_close_risky_positions()  # If configured
```

### 1.3 Behavioral Circuit Breakers

**Gambling Behavior Detection**
```python
class BehavioralCircuitBreaker:
    """Detects and prevents gambling-like behavior"""
    
    # Revenge trading (increasing size after loss)
    if recent_loss and next_trade_size > avg_size * 2.0:
        trigger = "suspected_revenge_trading"
        block_trade()
        require_cooldown(duration_hours=4)
        send_education("Avoid revenge trading")
    
    # Excessive trading frequency
    if trades_last_hour > 10 and user.level == Level.LIMITED_LIVE:
        trigger = "excessive_frequency"
        enforce_cooldown(duration_minutes=30)
        warn_user("Trading too frequently: take a break")
    
    # Overconcentration in single asset
    if position_size_pct_in_asset > 0.50:  # 50% in one asset
        trigger = "overconcentration"
        block_additional_exposure()
        suggest_diversification()
    
    # Late night trading (potential emotional trading)
    if local_time.hour >= 23 or local_time.hour <= 5:
        trigger = "late_night_trading"
        confirm_user_alert("Trading outside normal hours - confirm?")
        log_for_pattern_analysis()
```

---

## 2. Mandatory Cooling-Off Periods

### 2.1 Loss-Triggered Cooling-Off

**After Significant Loss**
```python
class LossCoolingOff:
    """Mandatory breaks after losses"""
    
    # Single trade loss > 5% of account
    if trade_loss_pct > 0.05:
        cooloff = 2 * 3600  # 2 hours
        enforce_break(user_id, cooloff, "Large single trade loss")
        suggest_review_strategy()
    
    # Daily loss > 10% of account
    if daily_loss_pct > 0.10:
        cooloff = 24 * 3600  # 24 hours
        enforce_break(user_id, cooloff, "Significant daily loss")
        require_written_reflection()  # User must document what went wrong
    
    # Weekly loss > 15% of account
    if weekly_loss_pct > 0.15:
        cooloff = 7 * 24 * 3600  # 7 days
        enforce_break(user_id, cooloff, "Large weekly loss")
        require_compliance_review()
        offer_counseling_resources()
```

**After Consecutive Losses**
```python
class StreakCoolingOff:
    """Breaks after losing streaks"""
    
    # 3 consecutive losses
    if consecutive_losses == 3:
        cooloff = 1 * 3600  # 1 hour
        enforce_break(user_id, cooloff, "3 consecutive losses")
        display_motivation("It happens - take a break")
    
    # 5 consecutive losses
    if consecutive_losses == 5:
        cooloff = 24 * 3600  # 24 hours
        enforce_break(user_id, cooloff, "5 consecutive losses")
        require_strategy_review()
        offer_coaching_session()
    
    # 10 consecutive losses (highly unusual)
    if consecutive_losses >= 10:
        cooloff = 7 * 24 * 3600  # 7 days
        enforce_break(user_id, cooloff, "Unusual losing streak")
        trigger_compliance_investigation()
        check_algorithm_malfunction()
```

### 2.2 Mandatory Weekend Breaks

**Weekend Position Risk**
```python
class WeekendBreak:
    """Enforces weekend risk management"""
    
    # Friday before weekend close (crypto 24/7, but user protection)
    if is_friday and hour >= 20:  # 8 PM Friday
        trigger = "weekend_approaching"
        
        # For Level 1 & 2 users
        if user.level in [Level.PAPER, Level.LIMITED_LIVE]:
            warn_user("Weekend approaching: Consider closing positions")
            disable_new_positions()
        
        # For all users with high-risk positions
        if has_leveraged_positions or position_count > 5:
            require_review("Review open positions before weekend")
            suggest_reduce_exposure()
    
    # Saturday/Sunday new position restrictions
    if is_weekend and user.level == Level.LIMITED_LIVE:
        block_new_positions()
        allow_only_position_management()  # Can close, not open
        display_notice("Weekend trading restricted for your protection")
```

### 2.3 Post-Graduation Cooling-Off

**After Level Advancement**
```python
class GraduationCoolingOff:
    """Prevents immediate risk-taking after graduation"""
    
    # Just graduated to Level 2 (Limited Live)
    if days_since_level2_activation < 7:
        enforce_extra_caution_mode()
        reduce_suggested_position_sizes(factor=0.5)
        increase_monitoring_frequency()
        send_daily_check_in("How's live trading going?")
    
    # Just graduated to Level 3 (Full Live)
    if days_since_level3_activation < 14:
        start_with_level2_limits()  # Don't jump to full limits
        progressive_limit_increase_over_30_days()
        require_weekly_performance_review()
        assign_account_manager()
```

---

## 3. Position Size Limits with Progressive Unlocking

### 3.1 Dynamic Position Sizing

**Adaptive Based on Recent Performance**
```python
class AdaptivePositionSizing:
    """Adjusts position sizes based on recent results"""
    
    def calculate_max_position_size(user_id, base_limit):
        # Get recent performance
        win_rate_30d = get_win_rate_last_30_days(user_id)
        sharpe_30d = get_sharpe_ratio_30_days(user_id)
        drawdown_current = get_current_drawdown_pct(user_id)
        
        # Start with base limit
        max_size = base_limit
        
        # Adjust for performance
        if win_rate_30d < 0.45:  # Below 45% win rate
            max_size *= 0.5  # Reduce by 50%
            reason = "Low win rate: reduced limits"
        
        if sharpe_30d < 0.5:  # Poor risk-adjusted returns
            max_size *= 0.7  # Reduce by 30%
            reason = "Low Sharpe ratio: reduced limits"
        
        if drawdown_current > 0.10:  # Currently in 10%+ drawdown
            max_size *= 0.5  # Reduce by 50%
            reason = "Active drawdown: reduced limits"
        
        # Boost for excellent performance
        if win_rate_30d > 0.65 and sharpe_30d > 1.5:
            max_size *= 1.2  # Increase by 20%
            reason = "Strong performance: increased limits"
        
        return max_size, reason
```

**Market Condition Adjustments**
```python
class MarketBasedSizing:
    """Adjusts position sizes for market conditions"""
    
    def get_market_adjusted_size(base_size, symbol):
        # Get market metrics
        volatility = get_realized_volatility_24h(symbol)
        liquidity = get_avg_volume_24h(symbol)
        spread = get_avg_spread_1h(symbol)
        
        adjusted_size = base_size
        
        # High volatility = smaller positions
        if volatility > historical_avg_volatility * 2.0:
            adjusted_size *= 0.5
            reason = "High volatility: halved position size"
        
        # Low liquidity = smaller positions
        if liquidity < min_liquidity_threshold:
            adjusted_size *= 0.3
            reason = "Low liquidity: reduced to 30%"
        
        # Wide spread = smaller positions
        if spread > 0.005:  # 0.5% spread
            adjusted_size *= 0.6
            reason = "Wide spread: reduced to 60%"
        
        return adjusted_size, reason
```

### 3.2 Progressive Unlocking Schedule

**Level 3 Unlocking Calendar**
```python
class ProgressiveUnlocking:
    """Gradual increase in limits over time"""
    
    UNLOCK_SCHEDULE = {
        # Days at Level 3: (account_limit, position_limit, open_positions, leverage)
        0: (50000, 10000, 10, 1.5),      # Day 1
        30: (75000, 15000, 12, 1.75),     # Month 1
        60: (125000, 25000, 15, 2.0),     # Month 2
        90: (250000, 50000, 20, 2.5),     # Month 3 (major unlock)
        120: (375000, 75000, 25, 2.75),   # Month 4
        150: (500000, 100000, 30, 3.0),   # Month 5
        180: (750000, 150000, 40, 3.5),   # Month 6 (major unlock)
        270: (1000000, 200000, 50, 4.0),  # Month 9
        365: (2000000, 400000, 75, 5.0),  # Year 1 (institutional)
    }
    
    def get_current_limits(user_id):
        days_at_level3 = get_days_at_level(user_id, Level.FULL_LIVE)
        
        # Find applicable unlock level
        for days_threshold in sorted(UNLOCK_SCHEDULE.keys(), reverse=True):
            if days_at_level3 >= days_threshold:
                limits = UNLOCK_SCHEDULE[days_threshold]
                
                # But only if performance justifies it
                if meets_performance_criteria(user_id, days_threshold):
                    return limits
                else:
                    # Stay at previous level
                    return get_previous_level_limits(days_threshold)
        
        # Default to initial Level 3 limits
        return UNLOCK_SCHEDULE[0]
```

**Performance Gates for Unlocking**
```python
class PerformanceGates:
    """Must meet performance criteria to unlock next tier"""
    
    UNLOCK_CRITERIA = {
        90: {  # Month 3 unlock
            "min_win_rate": 0.53,
            "min_sharpe": 1.0,
            "max_drawdown": 0.12,
            "profitable_months": 2
        },
        180: {  # Month 6 unlock
            "min_win_rate": 0.55,
            "min_sharpe": 1.2,
            "max_drawdown": 0.10,
            "profitable_months": 5
        },
        365: {  # Year 1 unlock
            "min_win_rate": 0.57,
            "min_sharpe": 1.5,
            "max_drawdown": 0.08,
            "profitable_months": 10
        }
    }
    
    def meets_performance_criteria(user_id, days_threshold):
        if days_threshold not in UNLOCK_CRITERIA:
            return True  # No special criteria
        
        criteria = UNLOCK_CRITERIA[days_threshold]
        performance = get_performance_metrics(user_id, days_threshold)
        
        checks = {
            "win_rate": performance["win_rate"] >= criteria["min_win_rate"],
            "sharpe": performance["sharpe"] >= criteria["min_sharpe"],
            "drawdown": performance["max_drawdown"] <= criteria["max_drawdown"],
            "profitable": performance["profitable_months"] >= criteria["profitable_months"]
        }
        
        all_passed = all(checks.values())
        
        if not all_passed:
            notify_user(
                f"Unlock delayed: Performance criteria not yet met. "
                f"Missing: {[k for k, v in checks.items() if not v]}"
            )
        
        return all_passed
```

---

## 4. Real-Time Suitability Checks

### 4.1 Pre-Trade Suitability Validation

**Every Trade Checked**
```python
class PreTradeSuitability:
    """Validates suitability before each trade"""
    
    def check_trade_suitability(user_id, trade_params):
        user_profile = get_user_profile(user_id)
        
        # Check 1: Risk tolerance alignment
        if trade_params["risk_pct"] > user_profile["risk_tolerance"]:
            return reject_trade(
                "Trade risk exceeds your stated risk tolerance. "
                "Reduce position size or update your risk profile."
            )
        
        # Check 2: Investment objectives alignment
        if user_profile["objective"] == "capital_preservation":
            if trade_params["leverage"] > 1.0:
                return reject_trade(
                    "Leveraged trading conflicts with capital preservation objective."
                )
        
        # Check 3: Experience level
        if trade_params["complexity"] == "advanced":
            if user_profile["experience_level"] == "beginner":
                return reject_trade(
                    "This strategy is too advanced for your experience level. "
                    "Start with beginner-friendly strategies."
                )
        
        # Check 4: Financial capacity
        required_capital = trade_params["size"] * trade_params["price"]
        if required_capital > user_profile["investment_capacity"] * 0.20:
            return warn_user(
                "This trade represents >20% of your stated investment capacity. "
                "Confirm you can afford this exposure."
            )
        
        return approve_trade()
```

### 4.2 Ongoing Suitability Monitoring

**Continuous Profile Validation**
```python
class OngoingSuitabilityMonitoring:
    """Monitors if user's trading still matches their profile"""
    
    def weekly_suitability_check(user_id):
        profile = get_user_profile(user_id)
        actual_behavior = get_actual_trading_behavior_90d(user_id)
        
        misalignments = []
        
        # Check risk tolerance
        if profile["risk_tolerance"] == "conservative":
            if actual_behavior["avg_drawdown"] > 0.10:
                misalignments.append({
                    "issue": "Actual risk exceeds conservative profile",
                    "action": "Consider reducing position sizes"
                })
        
        # Check investment objectives
        if profile["objective"] == "income":
            if actual_behavior["profit_frequency"] < 0.60:
                misalignments.append({
                    "issue": "Win rate too low for income objective",
                    "action": "Consider switching to growth objective"
                })
        
        # Check time horizon
        if profile["time_horizon"] == "short_term":
            if actual_behavior["avg_hold_time_days"] > 30:
                misalignments.append({
                    "issue": "Holding positions longer than short-term horizon",
                    "action": "Reduce hold times or update profile"
                })
        
        if misalignments:
            notify_user_profile_mismatch(user_id, misalignments)
            suggest_profile_update()
        
        return len(misalignments) == 0
```

### 4.3 Triggered Re-Assessment

**When to Re-Assess Suitability**
```python
class TriggeredReassessment:
    """Forces suitability re-assessment on key events"""
    
    REASSESSMENT_TRIGGERS = {
        "large_loss": {
            "threshold": 0.25,  # 25% account loss
            "action": "mandatory_reassessment",
            "cooldown": 30  # days before can resume
        },
        "pattern_change": {
            "condition": "trading_style_shift_detected",
            "action": "suggested_reassessment",
            "examples": ["conservative → aggressive", "long-term → day-trading"]
        },
        "time_based": {
            "frequency": 365,  # days
            "action": "annual_review",
            "regulatory": True
        },
        "life_event": {
            "examples": ["job_loss", "major_expense", "inheritance"],
            "action": "update_financial_situation",
            "user_initiated": True
        }
    }
    
    def trigger_reassessment(user_id, trigger_type):
        if trigger_type == "large_loss":
            # Mandatory - can't trade until complete
            halt_trading(user_id)
            require_suitability_reassessment()
            offer_financial_counseling()
        
        elif trigger_type == "pattern_change":
            # Suggested but not mandatory
            suggest_reassessment()
            provide_education_on_detected_change()
        
        elif trigger_type == "time_based":
            # Regulatory compliance
            schedule_annual_review()
            send_questionnaire()
        
        elif trigger_type == "life_event":
            # User-initiated
            provide_update_form()
            offer_consultation()
```

---

## 5. Account Verification & KYC Integration

### 5.1 KYC Verification Levels

**Level-Appropriate KYC**
```python
class KYCVerification:
    """Multi-tier KYC based on trading level"""
    
    LEVEL_1_KYC = {
        "required": ["email_verification"],
        "optional": [],
        "max_account_value": 10000,  # Virtual only
        "real_money": False
    }
    
    LEVEL_2_KYC = {
        "required": [
            "email_verification",
            "phone_verification",
            "full_name",
            "date_of_birth",
            "country_of_residence",
            "government_id_number"  # Not full document
        ],
        "optional": ["address"],
        "max_account_value": 5000,
        "real_money": True,
        "aml_screening": "basic"
    }
    
    LEVEL_3_KYC = {
        "required": [
            "email_verification",
            "phone_verification",
            "full_name",
            "date_of_birth",
            "country_of_residence",
            "government_id_upload",  # Full document scan
            "proof_of_address",
            "source_of_funds",
            "video_verification",
            "tax_id_number"
        ],
        "optional": [
            "employment_verification",
            "income_documentation",
            "bank_account_verification"
        ],
        "max_account_value": float('inf'),
        "real_money": True,
        "aml_screening": "enhanced"
    }
```

**Progressive KYC Collection**
```python
class ProgressiveKYC:
    """Collect KYC progressively, not all at once"""
    
    def get_required_kyc_for_action(user_id, action, amount=None):
        current_kyc = get_user_kyc_status(user_id)
        
        # Depositing first $100
        if action == "deposit" and amount <= 100:
            return ["email", "phone", "name", "dob"]
        
        # Depositing $100-$1000
        elif action == "deposit" and 100 < amount <= 1000:
            return ["email", "phone", "name", "dob", "address", "id_number"]
        
        # Depositing >$1000
        elif action == "deposit" and amount > 1000:
            return ["full_level_3_kyc"]
        
        # Withdrawing
        elif action == "withdrawal":
            # Always need at least Level 2 KYC for withdrawals
            return ["level_2_kyc_minimum"]
        
        # Enabling leverage
        elif action == "enable_leverage":
            return ["full_level_3_kyc", "financial_sophistication_assessment"]
        
        return []
```

### 5.2 AML/Sanctions Screening

**Automated Screening**
```python
class AMLScreening:
    """Anti-money laundering and sanctions compliance"""
    
    def screen_user(user_id, kyc_data):
        results = {
            "sanctions_clear": False,
            "pep_check": False,
            "adverse_media": False,
            "risk_score": 0
        }
        
        # Check OFAC SDN list
        sanctions_hit = check_ofac_sdn_list(
            kyc_data["full_name"],
            kyc_data["dob"],
            kyc_data["country"]
        )
        results["sanctions_clear"] = not sanctions_hit
        
        # Check PEP database
        pep_hit = check_pep_database(
            kyc_data["full_name"],
            kyc_data["country"]
        )
        results["pep_check"] = not pep_hit
        
        # Adverse media screening
        adverse_hit = screen_adverse_media(
            kyc_data["full_name"]
        )
        results["adverse_media"] = not adverse_hit
        
        # Calculate risk score
        results["risk_score"] = calculate_risk_score(
            kyc_data,
            sanctions_hit,
            pep_hit,
            adverse_hit
        )
        
        # Decision
        if results["risk_score"] > 80:
            return "high_risk", "Manual review required"
        elif results["risk_score"] > 50:
            return "medium_risk", "Enhanced due diligence required"
        else:
            return "low_risk", "Approved"
```

**Transaction Monitoring**
```python
class TransactionMonitoring:
    """Ongoing monitoring for suspicious activity"""
    
    RED_FLAGS = {
        "structuring": {
            "pattern": "Multiple deposits just under $10K",
            "threshold": 3,  # deposits
            "timeframe": 24 * 3600,  # 24 hours
            "action": "file_SAR"
        },
        "rapid_movement": {
            "pattern": "Deposit and immediate withdrawal",
            "timeframe": 1 * 3600,  # 1 hour
            "action": "hold_funds_24h"
        },
        "unusual_volume": {
            "pattern": "Trading volume 10x historical average",
            "action": "enhanced_monitoring"
        },
        "geographic_risk": {
            "pattern": "Activity from high-risk jurisdiction",
            "action": "manual_review"
        }
    }
    
    def monitor_transaction(user_id, transaction):
        flags = []
        
        # Check each red flag pattern
        for flag_name, criteria in RED_FLAGS.items():
            if check_pattern_match(user_id, transaction, criteria):
                flags.append(flag_name)
                execute_action(criteria["action"], user_id, transaction)
        
        if flags:
            log_suspicious_activity(user_id, transaction, flags)
            notify_compliance_team(user_id, flags)
        
        return len(flags) == 0  # Transaction cleared if no flags
```

### 5.3 Document Verification

**Automated Document Checks**
```python
class DocumentVerification:
    """Verify uploaded KYC documents"""
    
    def verify_government_id(user_id, id_image):
        checks = {
            "readable": False,
            "not_expired": False,
            "face_match": False,
            "document_authentic": False
        }
        
        # OCR to extract data
        extracted_data = ocr_id_document(id_image)
        checks["readable"] = extracted_data is not None
        
        # Check expiration
        if extracted_data:
            expiry_date = extracted_data.get("expiry_date")
            checks["not_expired"] = expiry_date > datetime.now()
        
        # Face matching (compare to selfie)
        user_selfie = get_user_selfie(user_id)
        if user_selfie:
            match_score = compare_faces(id_image, user_selfie)
            checks["face_match"] = match_score > 0.85  # 85% confidence
        
        # Document authenticity (ML model or third-party service)
        authenticity_score = verify_document_authenticity(id_image)
        checks["document_authentic"] = authenticity_score > 0.90
        
        # All checks must pass
        if all(checks.values()):
            return "verified", checks
        else:
            failed_checks = [k for k, v in checks.items() if not v]
            return "failed", failed_checks
```

---

## 6. Additional Regulatory Safeguards

### 6.1 Best Execution Monitoring

**Order Quality Surveillance**
```python
class BestExecutionMonitoring:
    """Ensure users get best available execution"""
    
    def monitor_execution_quality(user_id, order, execution):
        # Compare executed price to market price at time of order
        market_price = get_market_price_at_time(
            order.symbol,
            order.timestamp
        )
        
        slippage = abs(execution.price - market_price) / market_price
        
        # Alert on excessive slippage
        if slippage > 0.01:  # 1% slippage
            log_execution_quality_issue(user_id, order, execution, slippage)
            notify_user(f"High slippage: {slippage*100:.2f}%")
        
        # Track fill rate
        fill_rate = execution.filled_quantity / order.quantity
        if fill_rate < 0.95:  # Less than 95% filled
            log_partial_fill(user_id, order, execution, fill_rate)
        
        # Compare to other brokers (if multi-broker)
        if is_multi_broker_user(user_id):
            compare_to_alternative_venues(order, execution)
```

### 6.2 Conflict of Interest Disclosures

**Transparency Requirements**
```python
class ConflictDisclosure:
    """Disclose any conflicts of interest"""
    
    DISCLOSURES = {
        "payment_for_order_flow": {
            "applicable": False,  # NIJA doesn't use PFOF
            "disclosure": "NIJA does not receive payment for order flow."
        },
        "principal_trading": {
            "applicable": False,  # NIJA doesn't trade against users
            "disclosure": "NIJA does not engage in principal trading."
        },
        "exchange_rebates": {
            "applicable": True,
            "disclosure": (
                "NIJA may receive rebates from exchanges for providing "
                "liquidity. These rebates are not passed to users."
            )
        },
        "affiliate_relationships": {
            "applicable": True,
            "disclosure": (
                "NIJA has affiliate relationships with some brokers. "
                "Broker selection is based on best execution, not referral fees."
            )
        }
    }
    
    def display_required_disclosures(user_id, context):
        applicable_disclosures = [
            d for d in DISCLOSURES.values() if d["applicable"]
        ]
        
        for disclosure in applicable_disclosures:
            show_disclosure_to_user(user_id, disclosure["disclosure"])
        
        require_acknowledgment(user_id, applicable_disclosures)
```

### 6.3 Advertising & Performance Claims Compliance

**Marketing Material Approval**
```python
class MarketingCompliance:
    """Ensure all marketing is compliant"""
    
    PROHIBITED_CLAIMS = [
        "guaranteed profits",
        "risk-free",
        "get rich quick",
        "never lose",
        "100% win rate",
        "beats the market every time"
    ]
    
    REQUIRED_DISCLAIMERS = [
        "Past performance is not indicative of future results",
        "Trading involves risk of loss",
        "You may lose your entire investment"
    ]
    
    def review_marketing_material(content):
        issues = []
        
        # Check for prohibited claims
        for prohibited in PROHIBITED_CLAIMS:
            if prohibited.lower() in content.lower():
                issues.append(f"Prohibited claim: {prohibited}")
        
        # Check for required disclaimers
        for required in REQUIRED_DISCLAIMERS:
            if required.lower() not in content.lower():
                issues.append(f"Missing disclaimer: {required}")
        
        # Check performance claims
        if "%" in content or "return" in content.lower():
            if not has_proper_performance_disclosure(content):
                issues.append("Performance claim missing proper disclosure")
        
        # Check testimonials
        if has_testimonial(content):
            if not has_testimonial_disclaimer(content):
                issues.append("Testimonial missing 'results not typical' disclaimer")
        
        if issues:
            return "rejected", issues
        else:
            return "approved", []
```

---

## 7. Implementation Checklist

### Phase 3 Definition of Done

**Enhanced Circuit Breakers**:
- [ ] Multi-layer circuit breaker system implemented (position, account, platform)
- [ ] Time-based volatility protection active
- [ ] Behavioral pattern detection deployed
- [ ] All circuit breakers tested with realistic scenarios

**Mandatory Cooling-Off Periods**:
- [ ] Loss-triggered cooling-off enforced
- [ ] Consecutive loss breaks implemented
- [ ] Weekend break reminders active
- [ ] Post-graduation cooling-off periods enforced

**Position Size Limits**:
- [ ] Dynamic position sizing based on performance
- [ ] Market condition adjustments implemented
- [ ] Progressive unlocking schedule active
- [ ] Performance gates validated

**Real-Time Suitability Checks**:
- [ ] Pre-trade suitability validation deployed
- [ ] Ongoing profile monitoring active
- [ ] Triggered re-assessment workflow implemented
- [ ] User education on suitability delivered

**KYC Integration**:
- [ ] Three-tier KYC system implemented
- [ ] Progressive KYC collection active
- [ ] AML/sanctions screening integrated
- [ ] Document verification automated (or manual process documented)

**Additional Safeguards**:
- [ ] Best execution monitoring deployed
- [ ] Conflict of interest disclosures displayed
- [ ] Marketing compliance review process active
- [ ] All regulatory disclosures implemented

---

**Last Updated**: January 31, 2026  
**Version**: 1.0  
**Owner**: Risk & Compliance Teams


"""
Profitability Verification Banner Component
Displays visual confirmation that trading configuration has passed profitability validation
"""

from typing import Dict, Optional
import logging

logger = logging.getLogger("nija.ui.profitability_banner")


class ProfitabilityVerificationBanner:
    """
    UI component that displays profitability verification status.
    
    Shows a green "Profitability Verified ✓" banner when configuration passes validation.
    Shows detailed profitability metrics when clicked/expanded.
    """
    
    def __init__(self):
        """Initialize profitability verification banner"""
        self.is_verified = False
        self.verification_details: Optional[Dict] = None
        self.exchange_name = "Unknown"
    
    def set_verified(self, verification_results: Dict, exchange: str = "coinbase"):
        """
        Mark configuration as verified with detailed results.
        
        Args:
            verification_results: Dict with validation results from profitability_assertion
            exchange: Exchange name (e.g., 'coinbase', 'kraken')
        """
        self.is_verified = True
        self.verification_details = verification_results
        self.exchange_name = exchange.upper()
        logger.info(f"✅ Profitability verification banner activated for {self.exchange_name}")
    
    def set_failed(self, error_message: str, exchange: str = "coinbase"):
        """
        Mark configuration as failed verification.
        
        Args:
            error_message: Error message from validation failure
            exchange: Exchange name
        """
        self.is_verified = False
        self.verification_details = {'error': error_message}
        self.exchange_name = exchange.upper()
        logger.warning(f"❌ Profitability verification failed for {self.exchange_name}")
    
    def get_banner_html(self) -> str:
        """
        Generate HTML for the banner component.
        
        Returns:
            HTML string for rendering the banner
        """
        if self.is_verified:
            return self._get_verified_banner_html()
        else:
            return self._get_failed_banner_html()
    
    def _get_verified_banner_html(self) -> str:
        """Generate HTML for verified state"""
        return """
<div class="profitability-banner verified" id="profitability-banner">
    <div class="banner-main">
        <span class="banner-icon">✓</span>
        <span class="banner-text">Profitability Verified</span>
        <span class="banner-exchange">{exchange}</span>
        <button class="banner-details-toggle" onclick="toggleProfitabilityDetails()">
            Details ▼
        </button>
    </div>
    <div class="banner-details" id="profitability-details" style="display: none;">
        {details_html}
    </div>
</div>

<style>
.profitability-banner {{
    position: fixed;
    top: 60px;
    right: 20px;
    z-index: 1000;
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    color: white;
    padding: 12px 20px;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    animation: slideInFromRight 0.5s ease-out;
}}

.profitability-banner.verified {{
    border-left: 4px solid #34d399;
}}

.banner-main {{
    display: flex;
    align-items: center;
    gap: 10px;
}}

.banner-icon {{
    font-size: 20px;
    font-weight: bold;
    background: rgba(255, 255, 255, 0.2);
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
}}

.banner-text {{
    font-weight: 600;
    font-size: 15px;
    letter-spacing: 0.3px;
}}

.banner-exchange {{
    background: rgba(255, 255, 255, 0.25);
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
}}

.banner-details-toggle {{
    background: rgba(255, 255, 255, 0.2);
    border: none;
    color: white;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: background 0.2s;
    margin-left: auto;
}}

.banner-details-toggle:hover {{
    background: rgba(255, 255, 255, 0.3);
}}

.banner-details {{
    margin-top: 15px;
    padding-top: 15px;
    border-top: 1px solid rgba(255, 255, 255, 0.3);
    font-size: 13px;
    line-height: 1.6;
}}

.detail-row {{
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    padding: 6px 0;
}}

.detail-label {{
    opacity: 0.9;
    font-weight: 500;
}}

.detail-value {{
    font-weight: 600;
    background: rgba(255, 255, 255, 0.15);
    padding: 2px 8px;
    border-radius: 4px;
}}

@keyframes slideInFromRight {{
    from {{
        transform: translateX(400px);
        opacity: 0;
    }}
    to {{
        transform: translateX(0);
        opacity: 1;
    }}
}}

/* Mobile responsive */
@media (max-width: 768px) {{
    .profitability-banner {{
        top: 50px;
        right: 10px;
        left: 10px;
        max-width: calc(100% - 20px);
    }}
}}
</style>

<script>
function toggleProfitabilityDetails() {{
    const details = document.getElementById('profitability-details');
    const button = document.querySelector('.banner-details-toggle');
    
    if (details.style.display === 'none') {{
        details.style.display = 'block';
        button.textContent = 'Details ▲';
    }} else {{
        details.style.display = 'none';
        button.textContent = 'Details ▼';
    }}
}}

// Auto-hide banner after 10 seconds (optional)
setTimeout(function() {{
    const banner = document.getElementById('profitability-banner');
    if (banner) {{
        banner.style.transition = 'opacity 0.5s ease-out';
        banner.style.opacity = '0.7';
    }}
}}, 10000);
</script>
        """.format(
            exchange=self.exchange_name,
            details_html=self._get_details_html()
        )
    
    def _get_failed_banner_html(self) -> str:
        """Generate HTML for failed state"""
        error_msg = ""
        if self.verification_details and 'error' in self.verification_details:
            error_msg = self.verification_details['error']
        
        return """
<div class="profitability-banner failed" id="profitability-banner">
    <div class="banner-main">
        <span class="banner-icon">⚠</span>
        <span class="banner-text">Profitability Check Failed</span>
        <span class="banner-exchange">{exchange}</span>
    </div>
    <div class="banner-error">
        {error_message}
    </div>
</div>

<style>
.profitability-banner.failed {{
    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
    border-left: 4px solid #f87171;
}}

.banner-error {{
    margin-top: 10px;
    padding: 10px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 6px;
    font-size: 13px;
    line-height: 1.5;
}}
</style>
        """.format(
            exchange=self.exchange_name,
            error_message=error_msg
        )
    
    def _get_details_html(self) -> str:
        """Generate HTML for details section"""
        if not self.verification_details:
            return "<p>No details available</p>"
        
        # Extract key metrics from verification results
        profit_targets = self.verification_details.get('profit_targets', {})
        risk_reward = self.verification_details.get('risk_reward', {})
        breakeven = self.verification_details.get('breakeven', {})
        
        details_html = ""
        
        # Profit targets
        if profit_targets:
            passing = profit_targets.get('passing_targets', [])
            if passing:
                details_html += "<div class='detail-section'>"
                details_html += "<div class='detail-row'><span class='detail-label'>Profitable Targets:</span><span class='detail-value'>{}</span></div>".format(
                    len(passing)
                )
                details_html += "</div>"
        
        # Risk/Reward ratio
        if risk_reward:
            rr_ratio = risk_reward.get('rr_ratio', 0)
            details_html += "<div class='detail-row'><span class='detail-label'>Risk/Reward Ratio:</span><span class='detail-value'>{:.2f}:1</span></div>".format(rr_ratio)
            
            net_profit = risk_reward.get('net_profit', 0)
            net_loss = risk_reward.get('net_loss', 0)
            details_html += "<div class='detail-row'><span class='detail-label'>Net Reward:</span><span class='detail-value'>+{:.2f}%</span></div>".format(net_profit)
            details_html += "<div class='detail-row'><span class='detail-label'>Net Risk:</span><span class='detail-value'>-{:.2f}%</span></div>".format(net_loss)
        
        # Breakeven win rate
        if breakeven:
            breakeven_wr = breakeven.get('breakeven_win_rate', 0)
            is_achievable = breakeven.get('is_achievable', False)
            achievable_text = "✓ Achievable" if is_achievable else "⚠ High"
            details_html += "<div class='detail-row'><span class='detail-label'>Breakeven Win Rate:</span><span class='detail-value'>{:.1f}% {}</span></div>".format(
                breakeven_wr, achievable_text
            )
        
        # Fees
        if profit_targets:
            fees = profit_targets.get('total_fee_pct', 0)
            details_html += "<div class='detail-row'><span class='detail-label'>Round-Trip Fees:</span><span class='detail-value'>{:.2f}%</span></div>".format(fees)
        
        return details_html or "<p>Validation passed</p>"
    
    def get_banner_react_jsx(self) -> str:
        """
        Generate React JSX for the banner component (for React apps).
        
        Returns:
            JSX string for React component
        """
        if self.is_verified:
            return """
import React, {{ useState }} from 'react';

export const ProfitabilityBanner = () => {{
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="profitability-banner verified">
      <div className="banner-main">
        <span className="banner-icon">✓</span>
        <span className="banner-text">Profitability Verified</span>
        <span className="banner-exchange">{exchange}</span>
        <button 
          className="banner-details-toggle"
          onClick={{() => setShowDetails(!showDetails)}}
        >
          {{showDetails ? 'Details ▲' : 'Details ▼'}}
        </button>
      </div>
      {{showDetails && (
        <div className="banner-details">
          {details_jsx}
        </div>
      )}}
    </div>
  );
}};
            """.format(
                exchange=self.exchange_name,
                details_jsx=self._get_details_jsx()
            )
        else:
            return """
import React from 'react';

export const ProfitabilityBanner = () => {{
  return (
    <div className="profitability-banner failed">
      <div className="banner-main">
        <span className="banner-icon">⚠</span>
        <span className="banner-text">Profitability Check Failed</span>
        <span className="banner-exchange">{exchange}</span>
      </div>
      <div className="banner-error">
        {error_message}
      </div>
    </div>
  );
}};
            """.format(
                exchange=self.exchange_name,
                error_message=self.verification_details.get('error', 'Unknown error') if self.verification_details else 'Unknown error'
            )
    
    def _get_details_jsx(self) -> str:
        """Generate JSX for details section"""
        if not self.verification_details:
            return "<p>No details available</p>"
        
        risk_reward = self.verification_details.get('risk_reward', {})
        rr_ratio = risk_reward.get('rr_ratio', 0)
        
        return """
          <div className="detail-row">
            <span className="detail-label">Risk/Reward Ratio:</span>
            <span className="detail-value">{:.2f}:1</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">Status:</span>
            <span className="detail-value">All targets profitable ✓</span>
          </div>
        """.format(rr_ratio)


# Singleton instance
_profitability_banner = None

def get_profitability_banner() -> ProfitabilityVerificationBanner:
    """Get singleton profitability banner instance"""
    global _profitability_banner
    if _profitability_banner is None:
        _profitability_banner = ProfitabilityVerificationBanner()
    return _profitability_banner


# Integration example for Flask/FastAPI
def add_profitability_banner_to_response(verification_results: Dict, exchange: str = "coinbase"):
    """
    Add profitability banner to HTTP response.
    
    Usage in Flask:
        @app.route('/dashboard')
        def dashboard():
            banner_html = add_profitability_banner_to_response(results, 'coinbase')
            return render_template('dashboard.html', banner=banner_html)
    
    Usage in FastAPI:
        @app.get("/dashboard")
        async def dashboard():
            banner_html = add_profitability_banner_to_response(results, 'coinbase')
            return {"banner": banner_html}
    """
    banner = get_profitability_banner()
    banner.set_verified(verification_results, exchange)
    return banner.get_banner_html()

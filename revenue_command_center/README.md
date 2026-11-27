# NIJA Revenue Command Center — owner-only deployment candidate

This review branch is isolated from the existing billing and trading services. The dashboard is a **manual reporting interface**, not an automatically synchronized financial ledger. No verified live numbers should be inferred from placeholders.

**Access:** Only dante.harrell@nijaaitrading.com and dantelrharrell@gmail.com are recognized. Both distinct secrets must be provisioned as Render secret environment variables NIJA_OWNER_BUSINESS_PASSWORD and NIJA_OWNER_PERSONAL_PASSWORD (minimum 20 characters each); otherwise the application returns HTTP 503. Never commit passwords. HTTPS required. HTTP Basic is an interim authentication mechanism and does **not** provide MFA, session revocation, or account-level Render administration controls. Do not import sensitive customer records until managed MFA and server-side storage are installed.

**Render configuration:** separate Python web service, build command `pip install -r revenue_command_center/requirements.txt`, start command `gunicorn --bind 0.0.0.0:$PORT revenue_command_center.app:app`, auto-deploy disabled. No changes to billing, Stripe payment configuration, trading, or existing production services.

**Verification:** check missing-secret 503, unauthenticated 401, unauthorized 401, both authorized logins 200, HTTPS and security headers. Stripe, GA4, lead and marketing data sources remain pending separate read-only integration and reconciliation.
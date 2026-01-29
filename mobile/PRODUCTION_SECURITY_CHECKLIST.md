# NIJA Mobile App - Production Security Checklist

This document outlines the security measures that MUST be implemented before deploying the mobile app to production.

## ⚠️ CRITICAL - Must Complete Before Production

### 1. API Authentication & Authorization

**Current State**: Mobile API endpoints accept user_id as a parameter without authentication.

**Required Actions**:

- [ ] Import `require_auth` decorator from `api_server.py`
- [ ] Add `@require_auth` decorator to ALL mobile API endpoints
- [ ] Verify `request.user_id` matches the requested `user_id` parameter
- [ ] Return 403 Forbidden for unauthorized access attempts
- [ ] Test authentication with valid and invalid JWT tokens

**Affected Endpoints**:
```python
# mobile_api.py - Add @require_auth to these endpoints:
- /api/mobile/device/register
- /api/mobile/device/unregister
- /api/mobile/device/list
- /api/mobile/dashboard/summary
- /api/mobile/trading/quick-toggle
- /api/mobile/positions/lightweight
- /api/mobile/trades/recent
```

**Example Fix**:
```python
from api_server import require_auth

@mobile_api.route('/device/register', methods=['POST'])
@require_auth
def register_device():
    data = request.get_json()
    user_id = data['user_id']

    # Verify authenticated user matches requested user
    if request.user_id != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    # ... rest of implementation
```

### 2. Admin-Only Endpoints

**Current State**: `/api/mobile/notifications/send` allows anyone to send notifications.

**Required Actions**:

- [ ] Create `require_admin_auth` decorator in `api_server.py`
- [ ] Add admin role/permission to user model
- [ ] Protect `/api/mobile/notifications/send` with admin auth
- [ ] OR remove endpoint if not needed for internal use
- [ ] Log all notification send attempts for audit trail

**Example Fix**:
```python
def require_admin_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is admin
        if not request.user_is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

@mobile_api.route('/notifications/send', methods=['POST'])
@require_auth
@require_admin_auth
def send_notification():
    # ... implementation
```

### 3. Push Notification Implementation

**Current State**: `send_push_notification()` is a placeholder that logs but doesn't send.

**Required Actions**:

**For Android (Firebase Cloud Messaging)**:
- [ ] Create Firebase project at https://console.firebase.google.com/
- [ ] Add Android app to Firebase project
- [ ] Download `google-services.json`
- [ ] Add to `android/app/google-services.json` (DO NOT commit to git)
- [ ] Install Firebase Admin SDK: `pip install firebase-admin`
- [ ] Initialize Firebase in `mobile_api.py`:
  ```python
  import firebase_admin
  from firebase_admin import credentials, messaging

  cred = credentials.Certificate("path/to/serviceAccountKey.json")
  firebase_admin.initialize_app(cred)
  ```
- [ ] Implement FCM message sending
- [ ] Handle notification delivery status
- [ ] Implement retry logic for failed sends

**For iOS (Apple Push Notification Service)**:
- [ ] Obtain APNs certificate from Apple Developer account
- [ ] Convert certificate to .pem format
- [ ] Store certificate securely (DO NOT commit to git)
- [ ] Use pyapns2 or similar library: `pip install pyapns2`
- [ ] Implement APNs connection and message sending
- [ ] Handle certificate expiration and renewal

**Common**:
- [ ] Update `send_push_notification()` to actually send notifications
- [ ] Return actual success/failure status
- [ ] Log notification delivery status
- [ ] Implement rate limiting to prevent notification spam
- [ ] Test on physical devices (simulators don't support push)

### 4. Persistent Storage for Push Tokens

**Current State**: Push tokens stored in-memory dictionary, lost on restart.

**Required Actions**:

- [ ] Create database table for push tokens
  ```sql
  CREATE TABLE push_tokens (
      id SERIAL PRIMARY KEY,
      user_id VARCHAR(255) NOT NULL,
      push_token TEXT NOT NULL,
      platform VARCHAR(20) NOT NULL,
      device_id VARCHAR(255) NOT NULL,
      device_info JSONB,
      registered_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW(),
      UNIQUE(user_id, device_id)
  );
  ```
- [ ] Replace in-memory `push_tokens` dictionary with database queries
- [ ] Add database migration script
- [ ] Test token persistence across server restarts
- [ ] Implement token cleanup for unregistered devices

**Example Fix**:
```python
# Replace global push_tokens dict with database calls
def register_device_token(user_id, push_token, platform, device_id, device_info):
    # Use SQLAlchemy or similar to insert/update in database
    session.execute(
        "INSERT INTO push_tokens (user_id, push_token, platform, device_id, device_info) "
        "VALUES (:user_id, :push_token, :platform, :device_id, :device_info) "
        "ON CONFLICT (user_id, device_id) DO UPDATE SET "
        "push_token = :push_token, updated_at = NOW()",
        params={...}
    )
    session.commit()
```

### 5. Network Security Configuration

**For Android**:

**Current State**: Allows cleartext (HTTP) traffic to localhost for development.

**Required Actions**:
- [ ] Remove localhost cleartext permission from `network_security_config.xml`
- [ ] Use build flavors to separate dev/prod configs:
  ```gradle
  android {
      buildTypes {
          debug {
              // Use debug network config (allows localhost)
          }
          release {
              // Use production network config (HTTPS only)
          }
      }
  }
  ```
- [ ] Verify production builds enforce HTTPS
- [ ] Update API base URL to production HTTPS endpoint
- [ ] Test that HTTP requests are blocked in production

**For iOS**:

**Current State**: Info.plist allows HTTP to localhost for development.

**Required Actions**:
- [ ] Remove localhost exception from App Transport Security
- [ ] Use build configurations (Debug/Release) to manage ATS settings
- [ ] Verify production builds enforce HTTPS
- [ ] Update API base URL to production HTTPS endpoint
- [ ] Test that HTTP requests are blocked in production

### 6. API Endpoint Configuration

**Required Actions**:
- [ ] Update `frontend/static/js/app.js` with production API URL
- [ ] Use environment variables for API endpoint:
  ```javascript
  const API_BASE_URL = window.ENV?.API_URL || 'https://api.nija.app';
  ```
- [ ] Configure different URLs for dev/staging/production
- [ ] Remove or protect any development-only endpoints
- [ ] Verify SSL/TLS certificate is valid for production domain

### 7. Secrets Management

**Required Actions**:
- [ ] Ensure `.gitignore` excludes all sensitive files:
  - `android/release.keystore`
  - `android/key.properties`
  - `android/app/google-services.json`
  - `ios/App/GoogleService-Info.plist`
  - `*.pem` files
  - `.env` files with secrets
- [ ] Use environment variables for secrets
- [ ] Store Firebase/APNs credentials in secure vault (not in code)
- [ ] Rotate secrets regularly
- [ ] Implement secret scanning in CI/CD pipeline

## 🔒 Recommended - Enhance Security

### 8. Rate Limiting

**Recommended Actions**:
- [ ] Implement rate limiting on all API endpoints
- [ ] Use Flask-Limiter or similar: `pip install Flask-Limiter`
- [ ] Limit device registration attempts (prevent spam)
- [ ] Limit notification sending (prevent abuse)
- [ ] Monitor and log rate limit violations

### 9. Input Validation

**Recommended Actions**:
- [ ] Validate all input parameters (user_id, device_id, etc.)
- [ ] Sanitize inputs to prevent injection attacks
- [ ] Use Pydantic or similar for request validation
- [ ] Implement request size limits
- [ ] Add content-type validation

### 10. Logging & Monitoring

**Recommended Actions**:
- [ ] Log all authentication attempts
- [ ] Log all trading toggle actions
- [ ] Log all push notification sends
- [ ] Set up alerting for suspicious activity
- [ ] Use structured logging (JSON format)
- [ ] Send logs to centralized logging service

### 11. SSL Certificate Pinning

**Recommended Actions**:
- [ ] Implement certificate pinning in mobile app
- [ ] Pin to production API domain certificate
- [ ] Handle certificate rotation
- [ ] Test certificate expiration scenarios

**iOS Implementation**:
```swift
// In AppDelegate or Capacitor plugin
func urlSession(_ session: URLSession,
                didReceive challenge: URLAuthenticationChallenge,
                completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
    // Implement certificate pinning
}
```

**Android Implementation**:
```xml
<!-- In network_security_config.xml -->
<domain-config>
    <domain includeSubdomains="true">api.nija.app</domain>
    <pin-set expiration="2027-01-01">
        <pin digest="SHA-256">HASH_OF_YOUR_CERTIFICATE</pin>
        <pin digest="SHA-256">BACKUP_HASH</pin>
    </pin-set>
</domain-config>
```

### 12. Biometric Authentication

**Recommended Actions**:
- [ ] Implement secure token storage in keychain/keystore
- [ ] Require biometric auth for sensitive actions
- [ ] Implement timeout for biometric sessions
- [ ] Fallback to password if biometric fails
- [ ] Test on devices with/without biometric hardware

### 13. Data Encryption

**Recommended Actions**:
- [ ] Encrypt sensitive data at rest on device
- [ ] Use iOS Keychain / Android Keystore for credentials
- [ ] Encrypt local database (if used)
- [ ] Implement secure data wipe on logout
- [ ] Test data persistence across app updates

## 📋 Pre-Launch Checklist

Before submitting to App Stores:

### Code Security
- [ ] All authentication implemented
- [ ] All authorization checks in place
- [ ] Push notifications working
- [ ] Persistent storage implemented
- [ ] Production network config applied
- [ ] Secrets properly managed
- [ ] Rate limiting implemented
- [ ] Input validation complete
- [ ] Logging and monitoring set up

### Configuration
- [ ] Production API URL configured
- [ ] HTTPS enforced (no HTTP allowed)
- [ ] SSL certificate valid
- [ ] Environment variables set
- [ ] Firebase/APNs configured
- [ ] Database migrations run

### Testing
- [ ] Security penetration testing completed
- [ ] Authentication tests passed
- [ ] Authorization tests passed
- [ ] Push notification tests passed
- [ ] Network security tests passed
- [ ] Physical device testing completed

### Documentation
- [ ] Security measures documented
- [ ] API documentation updated
- [ ] Deployment runbook created
- [ ] Incident response plan documented

### Compliance
- [ ] Privacy policy reviewed by legal
- [ ] Terms of service reviewed by legal
- [ ] GDPR compliance verified
- [ ] CCPA compliance verified
- [ ] App Store guidelines reviewed
- [ ] Financial app requirements met

## 🚨 Security Incident Response

If a security vulnerability is discovered:

1. **Immediate Actions**:
   - Disable affected endpoints
   - Revoke compromised tokens
   - Notify affected users
   - Document the incident

2. **Investigation**:
   - Review access logs
   - Identify scope of breach
   - Determine root cause
   - Assess data exposure

3. **Remediation**:
   - Patch vulnerability
   - Deploy fix to production
   - Force password/token reset if needed
   - Update security measures

4. **Communication**:
   - Notify users as required by law
   - Report to authorities if required
   - Update privacy policy if needed
   - Publish post-mortem (if appropriate)

## 📞 Security Contacts

- **Security Team**: security@nija.app
- **Development Team**: dev@nija.app
- **Legal Team**: legal@nija.app

## 📚 Resources

- [OWASP Mobile Security](https://owasp.org/www-project-mobile-security/)
- [iOS Security Guide](https://support.apple.com/guide/security/welcome/web)
- [Android Security Best Practices](https://developer.android.com/topic/security/best-practices)
- [Firebase Security Rules](https://firebase.google.com/docs/rules)
- [APNs Documentation](https://developer.apple.com/documentation/usernotifications)

---

**Remember**: Security is not a one-time task. Continuously monitor, update, and improve security measures throughout the app's lifecycle.

**Last Updated**: January 27, 2026

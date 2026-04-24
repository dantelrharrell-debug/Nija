# Secure API Vault System Architecture

## Executive Summary

The Secure API Vault System is a critical component of NIJA's multi-user platform that manages cryptocurrency exchange API credentials for all users. This system ensures that sensitive API keys, secrets, and other credentials are stored, accessed, and rotated securely using industry best practices.

## Design Goals

1. **Zero Knowledge Architecture**: Platform operators cannot access user credentials
2. **Encryption at Rest**: All secrets encrypted using AES-256-GCM
3. **Encryption in Transit**: TLS 1.3 for all communications
4. **Automatic Key Rotation**: Support for periodic credential rotation
5. **Audit Logging**: Complete audit trail of all credential access
6. **High Availability**: 99.99% uptime for credential access
7. **Disaster Recovery**: Encrypted backups with point-in-time recovery

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  User Application Layer                      │
│  Mobile App / Web Dashboard / Trading Service                │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTPS/TLS 1.3
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    Vault Gateway API                         │
│  - JWT authentication                                        │
│  - Request validation                                        │
│  - Rate limiting                                            │
│  - Audit logging                                            │
└───────────────────────┬─────────────────────────────────────┘
                        │
         ┌──────────────┼──────────────┬──────────────┐
         │              │              │              │
         ▼              ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐
│   Store      │ │  Retrieve│ │   Rotate   │ │   Revoke     │
│   Service    │ │  Service │ │  Service   │ │   Service    │
└──────┬───────┘ └────┬─────┘ └──────┬─────┘ └──────┬───────┘
       │              │              │              │
       └──────────────┴──────────────┴──────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              HashiCorp Vault Core Engine                     │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  KV Secrets  │  │   Transit    │  │   AppRole    │     │
│  │   Engine     │  │   Engine     │  │     Auth     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Policies   │  │  Audit Log   │  │   Leasing    │     │
│  │   Engine     │  │   Engine     │  │   System     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────┬───────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         │                │                │
         ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Encrypted   │  │  Unseal Keys │  │  Audit Logs  │
│  Storage     │  │  (HSM/Cloud) │  │   (S3/GCS)   │
│  (PostgreSQL)│  │              │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
```

## Core Components

### 1. HashiCorp Vault

**Why Vault?**
- Industry-standard secrets management
- Built-in encryption, auditing, and access control
- Proven at scale (used by thousands of companies)
- Open source with enterprise support
- Rich ecosystem and integrations

**Vault Configuration:**

```hcl
# vault-config.hcl
storage "postgresql" {
  connection_url = "postgres://vault:password@postgres:5432/vault?sslmode=require"
  ha_enabled     = true
  max_parallel   = 128
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/vault/tls/vault.crt"
  tls_key_file  = "/vault/tls/vault.key"
}

seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unseal-key"
}

ui = true
api_addr = "https://vault.nija.io"
cluster_addr = "https://vault.nija.io:8201"
```

**Secrets Engines:**

1. **KV Secrets Engine v2** (versioned secrets)
   - Path: `secret/users/{user_id}/{broker}`
   - Stores encrypted API credentials
   - Maintains version history (last 10 versions)
   - Supports rollback to previous versions

2. **Transit Engine** (encryption as a service)
   - Path: `transit/keys/user-credentials`
   - Provides encryption/decryption without storing keys
   - Used for additional sensitive data encryption
   - Supports key rotation

### 2. Vault Gateway API

Python-based FastAPI service that provides a simplified, secure interface to Vault.

**Implementation:**

```python
# vault_gateway.py
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import hvac
from pydantic import BaseModel
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="NIJA Vault Gateway API")
security = HTTPBearer()

# Vault client
vault_client = hvac.Client(
    url='https://vault.nija.io:8200',
    token=os.getenv('VAULT_TOKEN')  # AppRole auth in production
)

class CredentialStore(BaseModel):
    """Request to store user credentials."""
    user_id: str
    broker: str
    api_key: str
    api_secret: str
    additional_params: Optional[Dict[str, str]] = None

class CredentialRetrieve(BaseModel):
    """Request to retrieve user credentials."""
    user_id: str
    broker: str

class CredentialRotate(BaseModel):
    """Request to rotate user credentials."""
    user_id: str
    broker: str
    new_api_key: str
    new_api_secret: str

# Authentication
async def verify_jwt(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Verify JWT token and extract user info."""
    token = credentials.credentials
    # Implement JWT verification here
    # Return user_id from token
    return {"user_id": "user_from_token"}

# Store credentials
@app.post("/v1/credentials/store")
async def store_credentials(
    request: CredentialStore,
    user: dict = Depends(verify_jwt)
):
    """
    Store user credentials in Vault.

    Security:
    - User can only store their own credentials
    - Credentials encrypted at rest by Vault
    - Audit log entry created
    """
    # Verify user can only store their own credentials
    if request.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Cannot store credentials for other users")

    try:
        # Build secret path
        secret_path = f"secret/users/{request.user_id}/{request.broker}"

        # Prepare secret data
        secret_data = {
            "api_key": request.api_key,
            "api_secret": request.api_secret,
            "broker": request.broker,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": user["user_id"]
        }

        if request.additional_params:
            secret_data["additional_params"] = request.additional_params

        # Store in Vault KV v2
        vault_client.secrets.kv.v2.create_or_update_secret(
            path=secret_path,
            secret=secret_data
        )

        logger.info(f"Stored credentials for user {request.user_id} on {request.broker}")

        return {
            "status": "success",
            "message": "Credentials stored successfully",
            "user_id": request.user_id,
            "broker": request.broker
        }

    except Exception as e:
        logger.error(f"Failed to store credentials: {e}")
        raise HTTPException(status_code=500, detail="Failed to store credentials")

# Retrieve credentials
@app.post("/v1/credentials/retrieve")
async def retrieve_credentials(
    request: CredentialRetrieve,
    user: dict = Depends(verify_jwt)
):
    """
    Retrieve user credentials from Vault.

    Security:
    - User can only retrieve their own credentials
    - Audit log entry created
    - Credentials decrypted by Vault
    """
    # Verify user can only retrieve their own credentials
    if request.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Cannot retrieve credentials for other users")

    try:
        # Build secret path
        secret_path = f"secret/users/{request.user_id}/{request.broker}"

        # Retrieve from Vault
        response = vault_client.secrets.kv.v2.read_secret_version(
            path=secret_path
        )

        secret_data = response['data']['data']

        logger.info(f"Retrieved credentials for user {request.user_id} on {request.broker}")

        return {
            "status": "success",
            "credentials": {
                "api_key": secret_data["api_key"],
                "api_secret": secret_data["api_secret"],
                "broker": secret_data["broker"],
                "additional_params": secret_data.get("additional_params")
            }
        }

    except hvac.exceptions.InvalidPath:
        raise HTTPException(status_code=404, detail="Credentials not found")
    except Exception as e:
        logger.error(f"Failed to retrieve credentials: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve credentials")

# Rotate credentials
@app.post("/v1/credentials/rotate")
async def rotate_credentials(
    request: CredentialRotate,
    user: dict = Depends(verify_jwt)
):
    """
    Rotate user credentials (update to new keys).

    Security:
    - User can only rotate their own credentials
    - Old version retained (can rollback)
    - Audit log entry created
    """
    # Verify user can only rotate their own credentials
    if request.user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Cannot rotate credentials for other users")

    try:
        # Build secret path
        secret_path = f"secret/users/{request.user_id}/{request.broker}"

        # Prepare new secret data
        secret_data = {
            "api_key": request.new_api_key,
            "api_secret": request.new_api_secret,
            "broker": request.broker,
            "rotated_at": datetime.utcnow().isoformat(),
            "rotated_by": user["user_id"]
        }

        # Update in Vault (creates new version)
        vault_client.secrets.kv.v2.create_or_update_secret(
            path=secret_path,
            secret=secret_data
        )

        logger.info(f"Rotated credentials for user {request.user_id} on {request.broker}")

        return {
            "status": "success",
            "message": "Credentials rotated successfully"
        }

    except Exception as e:
        logger.error(f"Failed to rotate credentials: {e}")
        raise HTTPException(status_code=500, detail="Failed to rotate credentials")

# Revoke credentials
@app.delete("/v1/credentials/revoke")
async def revoke_credentials(
    user_id: str,
    broker: str,
    user: dict = Depends(verify_jwt)
):
    """
    Revoke (delete) user credentials.

    Security:
    - User can only revoke their own credentials
    - Soft delete (can be recovered from versions)
    - Audit log entry created
    """
    # Verify user can only revoke their own credentials
    if user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Cannot revoke credentials for other users")

    try:
        # Build secret path
        secret_path = f"secret/users/{user_id}/{broker}"

        # Delete from Vault (soft delete - versions retained)
        vault_client.secrets.kv.v2.delete_latest_version_of_secret(
            path=secret_path
        )

        logger.info(f"Revoked credentials for user {user_id} on {broker}")

        return {
            "status": "success",
            "message": "Credentials revoked successfully"
        }

    except Exception as e:
        logger.error(f"Failed to revoke credentials: {e}")
        raise HTTPException(status_code=500, detail="Failed to revoke credentials")

# List user's brokers
@app.get("/v1/credentials/list")
async def list_user_brokers(
    user_id: str,
    user: dict = Depends(verify_jwt)
):
    """
    List all brokers configured for a user.

    Security:
    - User can only list their own brokers
    - Returns broker names only (no credentials)
    """
    # Verify user can only list their own brokers
    if user_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="Cannot list brokers for other users")

    try:
        # List secrets under user path
        secret_path = f"secret/users/{user_id}"

        response = vault_client.secrets.kv.v2.list_secrets(
            path=secret_path
        )

        brokers = response['data']['keys']

        return {
            "status": "success",
            "user_id": user_id,
            "brokers": brokers
        }

    except hvac.exceptions.InvalidPath:
        return {
            "status": "success",
            "user_id": user_id,
            "brokers": []
        }
    except Exception as e:
        logger.error(f"Failed to list brokers: {e}")
        raise HTTPException(status_code=500, detail="Failed to list brokers")
```

### 3. Vault Policies

**User Policy** (read/write own credentials only):

```hcl
# user-policy.hcl
path "secret/data/users/{{identity.entity.aliases.auth_jwt_nija.metadata.user_id}}/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "secret/metadata/users/{{identity.entity.aliases.auth_jwt_nija.metadata.user_id}}/*" {
  capabilities = ["list", "read", "delete"]
}

# Deny access to other users' secrets
path "secret/data/users/*" {
  capabilities = ["deny"]
}
```

**Service Policy** (for trading engine):

```hcl
# service-policy.hcl
path "secret/data/users/+/+" {
  capabilities = ["read"]
}

path "transit/encrypt/user-credentials" {
  capabilities = ["update"]
}

path "transit/decrypt/user-credentials" {
  capabilities = ["update"]
}
```

**Admin Policy** (for platform administration):

```hcl
# admin-policy.hcl
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "sys/policies/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "sys/mounts/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "auth/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
```

### 4. Authentication & Authorization

**AppRole Authentication** (for services):

```python
# Service authenticates with AppRole
import hvac

client = hvac.Client(url='https://vault.nija.io:8200')

# Login with AppRole
role_id = os.getenv('VAULT_ROLE_ID')
secret_id = os.getenv('VAULT_SECRET_ID')

response = client.auth.approle.login(
    role_id=role_id,
    secret_id=secret_id
)

client.token = response['auth']['client_token']
```

**JWT Authentication** (for users):

```python
# User authenticates with JWT
jwt_token = "user_jwt_token_here"

response = client.auth.jwt.login(
    role='user-role',
    jwt=jwt_token
)

client.token = response['auth']['client_token']
```

### 5. Audit Logging

**Audit Backend Configuration:**

```hcl
# Enable file audit backend
vault audit enable file file_path=/vault/logs/audit.log

# Enable syslog audit backend (optional)
vault audit enable syslog tag="vault" facility="AUTH"
```

**Audit Log Format:**

```json
{
  "time": "2026-01-27T19:48:59.123456Z",
  "type": "request",
  "auth": {
    "client_token": "hmac-sha256:...",
    "accessor": "hmac-sha256:...",
    "display_name": "user123",
    "policies": ["user-policy"],
    "token_policies": ["user-policy"],
    "metadata": {
      "user_id": "user123"
    }
  },
  "request": {
    "id": "abc-123-def-456",
    "operation": "read",
    "client_token": "hmac-sha256:...",
    "client_token_accessor": "hmac-sha256:...",
    "namespace": {
      "id": "root"
    },
    "path": "secret/data/users/user123/coinbase",
    "data": null,
    "remote_address": "203.0.113.1"
  },
  "response": {
    "mount_type": "kv"
  }
}
```

### 6. High Availability Setup

**Multi-Node Vault Cluster:**

```yaml
# docker-compose.yml for HA Vault
version: '3.8'

services:
  vault-1:
    image: vault:1.15
    environment:
      VAULT_ADDR: http://0.0.0.0:8200
      VAULT_API_ADDR: https://vault-1.nija.io:8200
      VAULT_CLUSTER_ADDR: https://vault-1.nija.io:8201
    volumes:
      - ./vault-config.hcl:/vault/config/vault.hcl
      - vault-1-data:/vault/data
    ports:
      - "8200:8200"
      - "8201:8201"
    command: server

  vault-2:
    image: vault:1.15
    environment:
      VAULT_ADDR: http://0.0.0.0:8200
      VAULT_API_ADDR: https://vault-2.nija.io:8200
      VAULT_CLUSTER_ADDR: https://vault-2.nija.io:8201
    volumes:
      - ./vault-config.hcl:/vault/config/vault.hcl
      - vault-2-data:/vault/data
    ports:
      - "8210:8200"
      - "8211:8201"
    command: server

  vault-3:
    image: vault:1.15
    environment:
      VAULT_ADDR: http://0.0.0.0:8200
      VAULT_API_ADDR: https://vault-3.nija.io:8200
      VAULT_CLUSTER_ADDR: https://vault-3.nija.io:8201
    volumes:
      - ./vault-config.hcl:/vault/config/vault.hcl
      - vault-3-data:/vault/data
    ports:
      - "8220:8200"
      - "8221:8201"
    command: server

volumes:
  vault-1-data:
  vault-2-data:
  vault-3-data:
```

### 7. Backup & Disaster Recovery

**Automated Backup Script:**

```bash
#!/bin/bash
# vault-backup.sh

VAULT_ADDR="https://vault.nija.io:8200"
VAULT_TOKEN="$VAULT_ROOT_TOKEN"
BACKUP_DIR="/vault/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Create snapshot
vault operator raft snapshot save "${BACKUP_DIR}/vault-snapshot-${DATE}.snap"

# Encrypt snapshot
openssl enc -aes-256-cbc -salt -in "${BACKUP_DIR}/vault-snapshot-${DATE}.snap" \
  -out "${BACKUP_DIR}/vault-snapshot-${DATE}.snap.enc" -k "$BACKUP_ENCRYPTION_KEY"

# Upload to S3
aws s3 cp "${BACKUP_DIR}/vault-snapshot-${DATE}.snap.enc" \
  "s3://nija-vault-backups/snapshots/" \
  --sse AES256

# Cleanup old local snapshots (keep last 7 days)
find "${BACKUP_DIR}" -name "vault-snapshot-*.snap*" -mtime +7 -delete

echo "Backup completed: vault-snapshot-${DATE}.snap.enc"
```

**Recovery Procedure:**

```bash
#!/bin/bash
# vault-restore.sh

BACKUP_FILE="$1"
VAULT_ADDR="https://vault.nija.io:8200"

# Download from S3
aws s3 cp "s3://nija-vault-backups/snapshots/${BACKUP_FILE}" .

# Decrypt
openssl enc -aes-256-cbc -d -in "${BACKUP_FILE}" \
  -out "vault-snapshot.snap" -k "$BACKUP_ENCRYPTION_KEY"

# Restore snapshot
vault operator raft snapshot restore vault-snapshot.snap

echo "Restore completed from: ${BACKUP_FILE}"
```

## Security Best Practices

### 1. Unseal Key Management

**Use Auto-Unseal with Cloud KMS:**

```hcl
# AWS KMS Auto-Unseal
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unseal-key"
}

# GCP Cloud KMS Auto-Unseal
seal "gcpckms" {
  project     = "nija-platform"
  region      = "us-east1"
  key_ring    = "vault"
  crypto_key  = "vault-unseal-key"
}
```

**Shamir Secret Sharing (manual unseal):**
- 5 key shares
- 3 required to unseal
- Distributed to different team members
- Stored in separate secure locations

### 2. Root Token Management

**Revoke root token after initialization:**

```bash
# Revoke root token
vault token revoke <root_token>

# Generate new root token only when needed (emergency)
vault operator generate-root -init
```

**Use short-lived tokens for admin tasks:**

```bash
# Create admin token with 1-hour TTL
vault token create -policy=admin-policy -ttl=1h
```

### 3. Network Security

**TLS Configuration:**

```hcl
listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/vault/tls/vault.crt"
  tls_key_file  = "/vault/tls/vault.key"
  tls_min_version = "tls13"
  tls_cipher_suites = [
    "TLS_AES_256_GCM_SHA384",
    "TLS_AES_128_GCM_SHA256",
    "TLS_CHACHA20_POLY1305_SHA256"
  ]
}
```

**Firewall Rules:**
- Allow port 8200 (HTTPS) from API Gateway only
- Allow port 8201 (cluster) from Vault nodes only
- Block all other inbound traffic
- Use VPN for admin access

### 4. Access Control

**Principle of Least Privilege:**
- Users: Read/write own credentials only
- Services: Read-only access to user credentials
- Admins: Full access with audit logging
- Emergency: Break-glass procedure documented

**Token Renewal:**

```python
# Auto-renew tokens before expiry
def renew_token(client):
    while True:
        # Renew token
        client.auth.token.renew_self()

        # Sleep for 80% of TTL
        lookup = client.auth.token.lookup_self()
        ttl = lookup['data']['ttl']
        sleep_time = int(ttl * 0.8)

        time.sleep(sleep_time)
```

### 5. Monitoring & Alerting

**Prometheus Metrics:**

```yaml
# vault-exporter config
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'vault'
    metrics_path: /v1/sys/metrics
    params:
      format: ['prometheus']
    static_configs:
      - targets: ['vault.nija.io:8200']
```

**Critical Alerts:**
- Vault unsealed status
- Failed authentication attempts
- Unusual access patterns
- High error rate
- Backup failures

## Performance Optimization

### 1. Connection Pooling

```python
# Connection pool for Vault client
from hvac import Client
from hvac.adapters import HTTPAdapter
from requests.adapters import HTTPAdapter as RequestsHTTPAdapter

class VaultConnectionPool:
    def __init__(self, url, max_connections=100):
        adapter = RequestsHTTPAdapter(
            pool_connections=max_connections,
            pool_maxsize=max_connections,
            max_retries=3
        )
        self.client = Client(url=url)
        self.client.session.mount('https://', adapter)

    def get_client(self):
        return self.client

# Global pool
vault_pool = VaultConnectionPool('https://vault.nija.io:8200')
```

### 2. Caching Strategy

**Cache Credentials in Redis:**

```python
import redis
import json
from datetime import timedelta

# Redis client
redis_client = redis.Redis(host='localhost', port=6379, db=0)

def get_credentials_cached(user_id: str, broker: str):
    """
    Get credentials with Redis caching.
    TTL: 5 minutes (reduce Vault load)
    """
    # Check cache first
    cache_key = f"creds:{user_id}:{broker}"
    cached = redis_client.get(cache_key)

    if cached:
        return json.loads(cached)

    # Fetch from Vault
    creds = retrieve_credentials(user_id, broker)

    # Cache for 5 minutes
    redis_client.setex(
        cache_key,
        timedelta(minutes=5),
        json.dumps(creds)
    )

    return creds
```

**Cache Invalidation:**
- Invalidate on credential rotation
- Invalidate on credential revocation
- TTL: 5 minutes (balance freshness vs load)

### 3. Batch Operations

```python
async def retrieve_multiple_credentials(requests: List[CredentialRetrieve]):
    """Retrieve multiple credentials in parallel."""
    tasks = [
        retrieve_credentials_async(req.user_id, req.broker)
        for req in requests
    ]
    return await asyncio.gather(*tasks)
```

## Integration with Existing NIJA Code

### 1. Update auth/__init__.py

```python
# Replace in-memory storage with Vault
class APIKeyManager:
    def __init__(self, vault_client=None):
        if vault_client is None:
            # Initialize Vault client
            self.vault = hvac.Client(
                url=os.getenv('VAULT_ADDR', 'http://localhost:8200'),
                token=os.getenv('VAULT_TOKEN')
            )
        else:
            self.vault = vault_client

        logger.info("API key manager initialized with Vault backend")

    def store_user_api_key(self, user_id, broker, api_key, api_secret, additional_params=None):
        """Store credentials in Vault instead of memory."""
        secret_path = f"secret/users/{user_id}/{broker}"

        secret_data = {
            'api_key': api_key,
            'api_secret': api_secret,
            'broker': broker,
            'created_at': datetime.now().isoformat()
        }

        if additional_params:
            secret_data['additional_params'] = additional_params

        self.vault.secrets.kv.v2.create_or_update_secret(
            path=secret_path,
            secret=secret_data
        )

        logger.info(f"Stored credentials in Vault for user {user_id} on {broker}")

    def get_user_api_key(self, user_id, broker):
        """Retrieve credentials from Vault."""
        secret_path = f"secret/users/{user_id}/{broker}"

        try:
            response = self.vault.secrets.kv.v2.read_secret_version(
                path=secret_path
            )
            return response['data']['data']
        except hvac.exceptions.InvalidPath:
            logger.warning(f"No credentials found for user {user_id} on {broker}")
            return None
```

### 2. Environment Variables

```bash
# .env additions
VAULT_ADDR=https://vault.nija.io:8200
VAULT_TOKEN=<vault-token>  # For development only
VAULT_ROLE_ID=<approle-id>  # For production
VAULT_SECRET_ID=<approle-secret>  # For production
VAULT_NAMESPACE=nija  # Optional for Vault Enterprise
```

### 3. Docker Deployment

```yaml
# docker-compose.yml
services:
  vault:
    image: vault:1.15
    ports:
      - "8200:8200"
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: root  # Dev only
    cap_add:
      - IPC_LOCK

  nija-api:
    build: .
    depends_on:
      - vault
    environment:
      VAULT_ADDR: http://vault:8200
      VAULT_TOKEN: root  # Dev only
```

## Cost Estimation

### Self-Hosted Vault (Recommended for production)
- **Infrastructure**: $100-200/month (3-node cluster)
- **Storage**: $20-50/month (PostgreSQL backend)
- **Monitoring**: $30-50/month (logs, metrics)
- **Total**: $150-300/month

### HashiCorp Cloud Platform (HCP) Vault
- **Starter**: $0.50/hour (~$360/month)
- **Standard**: $1.50/hour (~$1,080/month)
- **Plus**: $3.00/hour (~$2,160/month)

**Recommendation**: Start with self-hosted for cost efficiency.

## Migration Timeline

### Week 1: Setup & Configuration
- Day 1-2: Deploy Vault cluster
- Day 3-4: Configure policies and auth
- Day 5-7: Setup backup and monitoring

### Week 2: Integration
- Day 1-3: Update auth layer to use Vault
- Day 4-5: Migrate existing credentials
- Day 6-7: Testing and validation

### Week 3: Deployment
- Day 1-3: Staging deployment
- Day 4-5: User testing
- Day 6-7: Production rollout

## Success Criteria

- ✅ All user credentials stored in Vault
- ✅ Zero credentials in code or environment files
- ✅ 100% audit log coverage
- ✅ < 100ms p99 latency for credential retrieval
- ✅ 99.99% availability
- ✅ Successful disaster recovery test
- ✅ Zero security incidents

## Related Documentation

- [Multi-User Platform Architecture](./MULTI_USER_PLATFORM_ARCHITECTURE.md)
- [Execution Routing Model](./EXECUTION_ROUTING_ARCHITECTURE.md)
- [Current Architecture](./ARCHITECTURE.md)
- [Security Guidelines](./SECURITY.md)

---

**Document Version**: 1.0
**Last Updated**: January 27, 2026
**Status**: ✅ Ready for Implementation
**Owner**: Security Team

# NIJA Multi-User Platform Architecture

## Executive Summary

This document outlines the complete architecture for transforming NIJA from a single-user trading bot into a scalable, secure multi-user platform. The architecture includes three core components:

1. **Secure API Vault System** - Enterprise-grade credential management
2. **Execution Routing Model** - Intelligent trade routing and isolation
3. **Mobile App UX Flow** - Seamless user experience across devices

## Design Principles

### Security First
- Zero-trust architecture
- Encrypted credential storage
- Per-user authentication and authorization
- Audit logging for all critical operations
- Rate limiting and abuse prevention

### Scalability
- Support 1,000+ concurrent users
- Horizontal scaling capability
- Database sharding for performance
- Microservices-ready architecture

### Reliability
- 99.9% uptime target
- Graceful degradation
- Circuit breakers and failovers
- Comprehensive monitoring and alerting

### User Experience
- Sub-second API response times
- Real-time trade notifications
- Intuitive mobile-first interface
- Minimal latency for trade execution

## Current State Analysis

### Existing Components (✅ Implemented)

NIJA already has a strong foundation with the following components:

#### Layer 1: Core Brain (PRIVATE)
- Location: `/core/`
- Purpose: Proprietary trading strategy
- Status: ✅ Implemented and locked
- Components:
  - Trading strategy logic
  - Risk management engine
  - Technical indicators (RSI_9, RSI_14)
  - Entry/exit decision system

#### Layer 2: Execution Engine (LIMITED)
- Location: `/execution/`
- Status: ✅ Partially implemented
- Components:
  - User permissions system (`UserPermissions`)
  - Permission validator (`PermissionValidator`)
  - Broker adapter framework
  - Basic execution controls

#### Layer 3: User Interface (PUBLIC)
- Location: `/ui/`
- Status: ⚠️ Skeleton only
- Components:
  - Dashboard API structure
  - Basic user stats retrieval

#### Authentication & User Management
- Location: `/auth/`
- Status: ✅ Core implemented
- Components:
  - Encrypted API key manager (`APIKeyManager`)
  - User account manager (`UserManager`)
  - Fernet-based encryption

#### Hard Controls
- Location: `/controls/`
- Status: ✅ Implemented
- Components:
  - Position size limits (2-10%)
  - Daily loss tracking
  - Global and per-user kill switches
  - Live capital verification
  - Error tracking and auto-disable

#### Configuration Management
- Location: `/config/`
- Status: ✅ Implemented
- Components:
  - User config loader
  - YAML-based user profiles
  - Per-broker configurations

### Gaps to Address

1. **API Vault System**: Need production-grade secrets management
2. **Execution Routing**: Need intelligent routing and isolation
3. **Mobile App**: Need complete mobile UX design
4. **Database Layer**: Need persistent storage for users, trades, and analytics
5. **API Gateway**: Need rate limiting, authentication, and routing
6. **Monitoring**: Need comprehensive observability
7. **Deployment**: Need multi-tenant deployment strategy

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Mobile App (React Native)                 │
│  - iOS & Android native apps                                │
│  - Real-time WebSocket updates                              │
│  - Biometric authentication                                 │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTPS/WSS
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  API Gateway (Kong/Nginx)                    │
│  - Authentication (JWT)                                      │
│  - Rate limiting (per user/tier)                            │
│  - Request routing                                          │
│  - SSL termination                                          │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴──────────┬─────────────────────┐
         ▼                      ▼                     ▼
┌─────────────────┐   ┌──────────────────┐   ┌─────────────────┐
│  Dashboard API  │   │  Trading API     │   │  Admin API      │
│  (FastAPI)      │   │  (FastAPI)       │   │  (FastAPI)      │
│                 │   │                  │   │                 │
│  - User stats   │   │  - Trade exec    │   │  - User mgmt    │
│  - Settings     │   │  - Positions     │   │  - Monitoring   │
│  - Analytics    │   │  - Orders        │   │  - Controls     │
└────────┬────────┘   └─────────┬────────┘   └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
         ┌──────────────────────┴──────────────────────┐
         │                                             │
         ▼                                             ▼
┌─────────────────────┐                    ┌─────────────────────┐
│   API Vault         │                    │  Execution Router   │
│   (HashiCorp Vault) │                    │  (Core Service)     │
│                     │                    │                     │
│  - Encrypted keys   │                    │  - Route trades     │
│  - Key rotation     │                    │  - Isolate users    │
│  - Audit logging    │                    │  - Load balance     │
│  - Policy control   │                    │  - Circuit breaker  │
└─────────────────────┘                    └──────────┬──────────┘
                                                      │
                  ┌───────────────┬──────────────────┼──────────────┐
                  │               │                  │              │
                  ▼               ▼                  ▼              ▼
         ┌──────────────┐  ┌──────────┐    ┌──────────────┐  ┌─────────┐
         │  Coinbase    │  │  Kraken  │    │   Binance    │  │  Alpaca │
         │  Executor    │  │ Executor │    │   Executor   │  │ Executor│
         └──────────────┘  └──────────┘    └──────────────┘  └─────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Data Layer (PostgreSQL)                  │
│                                                              │
│  - Users & accounts          - Audit logs                   │
│  - Trades & positions        - Analytics data               │
│  - Permissions & configs     - System events                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 Monitoring & Observability                   │
│                                                              │
│  - Prometheus (metrics)      - Grafana (dashboards)         │
│  - ELK Stack (logs)          - Sentry (error tracking)      │
│  - PagerDuty (alerts)        - Datadog (APM)                │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Mobile App Layer
- **Technology**: React Native (iOS + Android)
- **Features**:
  - Biometric authentication (Face ID, Touch ID)
  - Real-time position tracking
  - Push notifications for trades
  - Interactive charts and analytics
  - Settings management
- **Communication**: REST API + WebSockets for real-time data
- **Offline Mode**: View-only cached data

### 2. API Gateway Layer
- **Technology**: Kong or Nginx with Lua
- **Responsibilities**:
  - JWT authentication validation
  - Rate limiting by user tier
  - Request logging and metrics
  - SSL/TLS termination
  - DDoS protection
- **Rate Limits**:
  - Basic tier: 60 req/min
  - Pro tier: 300 req/min
  - Enterprise tier: 1000 req/min

### 3. API Services Layer
- **Technology**: FastAPI (Python)
- **Services**:
  - **Dashboard API**: User-facing stats and settings
  - **Trading API**: Trade execution and position management
  - **Admin API**: Platform administration and monitoring
- **Features**:
  - Async/await for performance
  - Pydantic validation
  - OpenAPI documentation
  - Dependency injection

### 4. API Vault System
- See dedicated section below

### 5. Execution Router
- See dedicated section below

### 6. Data Layer
- **Technology**: PostgreSQL with TimescaleDB extension
- **Schema Design**:
  - User accounts and profiles
  - Trading history and positions
  - Permissions and configurations
  - Audit logs
  - Analytics aggregations
- **Performance**:
  - Read replicas for analytics
  - Connection pooling
  - Indexed queries
  - Partitioning for large tables

### 7. Monitoring Layer
- **Metrics**: Prometheus + Grafana
- **Logs**: ELK Stack (Elasticsearch, Logstash, Kibana)
- **Errors**: Sentry for exception tracking
- **APM**: Datadog for application performance
- **Alerts**: PagerDuty for critical incidents

## Technology Stack

### Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Database**: PostgreSQL 14+ with TimescaleDB
- **Cache**: Redis 7+
- **Message Queue**: RabbitMQ or Kafka
- **Secrets**: HashiCorp Vault

### Frontend (Mobile)
- **Framework**: React Native 0.72+
- **State Management**: Redux Toolkit
- **Navigation**: React Navigation
- **Charts**: Recharts / Victory Native
- **Real-time**: Socket.io client

### Infrastructure
- **Orchestration**: Kubernetes (K8s)
- **CI/CD**: GitHub Actions
- **Cloud**: AWS / GCP / Railway
- **Monitoring**: Prometheus, Grafana, ELK
- **Load Balancer**: Nginx / Kong

### Security
- **Encryption**: AES-256-GCM
- **Secrets**: HashiCorp Vault
- **Auth**: JWT with refresh tokens
- **API Security**: OAuth2 / API keys
- **Network**: TLS 1.3, VPN for admin access

## Deployment Strategy

### Development Environment
- Docker Compose for local development
- Mock API vault for testing
- In-memory Redis and PostgreSQL
- Hot reload for rapid iteration

### Staging Environment
- Kubernetes cluster (3 nodes)
- Real integrations with test accounts
- Production-like configuration
- Load testing and QA

### Production Environment
- Kubernetes cluster (5+ nodes)
- Multi-AZ deployment
- Auto-scaling (HPA)
- Blue-green deployment
- 99.9% uptime SLA

## Security Considerations

### Data Protection
- **At Rest**: AES-256 encryption for all sensitive data
- **In Transit**: TLS 1.3 for all communications
- **Secrets**: HashiCorp Vault with auto-rotation
- **PII**: GDPR-compliant data handling

### Authentication & Authorization
- **Multi-factor**: SMS/Email OTP, TOTP (Authenticator apps)
- **Session Management**: JWT with short expiry (15 min)
- **Refresh Tokens**: Secure, HTTP-only cookies
- **Password Policy**: Minimum 12 chars, complexity requirements
- **Brute Force**: Rate limiting + account lockout

### API Security
- **Rate Limiting**: Per-user and per-IP limits
- **Input Validation**: Strict schema validation
- **SQL Injection**: Parameterized queries only
- **XSS Protection**: Content Security Policy
- **CSRF Protection**: Token-based validation

### Compliance
- **SOC 2**: Compliance-ready architecture
- **GDPR**: Data privacy and right to deletion
- **PCI DSS**: If handling payment data
- **Audit Logs**: Immutable audit trail

## Scalability Plan

### Horizontal Scaling
- **API Services**: Auto-scale based on CPU/memory
- **Execution Workers**: Scale based on queue depth
- **Database**: Read replicas for queries
- **Cache**: Redis cluster for high throughput

### Database Optimization
- **Partitioning**: Time-series data by date
- **Indexing**: Strategic indexes on query patterns
- **Connection Pooling**: PgBouncer for connection reuse
- **Query Optimization**: EXPLAIN ANALYZE for slow queries

### Caching Strategy
- **Redis**: User sessions, permissions, rate limits
- **CDN**: Static assets for mobile app
- **Application Cache**: In-memory cache for hot data
- **Cache Invalidation**: Event-driven updates

## Monitoring & Alerting

### Key Metrics
- **System**: CPU, memory, disk, network
- **Application**: Request rate, latency, error rate
- **Business**: Trades executed, active users, PnL
- **Security**: Failed logins, API abuse, anomalies

### Alert Thresholds
- **Critical**: System down, data loss, security breach
- **High**: High error rate, performance degradation
- **Medium**: Unusual patterns, approaching limits
- **Low**: Informational, trends

### SLA Targets
- **API Availability**: 99.9% (8.76 hours/year downtime)
- **API Latency**: p50 < 100ms, p99 < 500ms
- **Trade Execution**: 95% within 5 seconds
- **Data Accuracy**: 100% (zero tolerance)

## Disaster Recovery

### Backup Strategy
- **Database**: Daily full backup, hourly incrementals
- **Secrets**: Vault snapshots to encrypted S3
- **Code**: Git with protected branches
- **Configuration**: Infrastructure as Code (Terraform)

### Recovery Procedures
- **RTO**: Recovery Time Objective = 1 hour
- **RPO**: Recovery Point Objective = 15 minutes
- **Runbooks**: Documented recovery procedures
- **Drills**: Quarterly DR testing

## Cost Optimization

### Infrastructure Costs (Monthly Estimates)
- **Kubernetes Cluster**: $200-500
- **Database (PostgreSQL)**: $100-300
- **Redis Cache**: $50-100
- **Vault**: $100 (self-hosted) or $300 (cloud)
- **Monitoring**: $100-200
- **Total**: $550-1,500/month for 100-1000 users

### Cost Reduction Strategies
- Auto-scaling to reduce idle capacity
- Spot instances for non-critical workloads
- Reserved instances for predictable load
- Object storage for cold data
- Optimize database queries

## Migration Path

### Phase 1: Foundation (Weeks 1-2)
- Set up PostgreSQL database
- Deploy HashiCorp Vault
- Implement API gateway
- Create basic FastAPI services

### Phase 2: API Development (Weeks 3-4)
- Dashboard API endpoints
- Trading API endpoints
- Admin API endpoints
- User migration scripts

### Phase 3: Mobile App (Weeks 5-8)
- React Native app setup
- Authentication flow
- Dashboard screens
- Trading screens
- Settings screens

### Phase 4: Integration (Weeks 9-10)
- Connect mobile app to APIs
- Implement WebSocket updates
- End-to-end testing
- Performance optimization

### Phase 5: Launch (Weeks 11-12)
- Beta testing with select users
- Fix bugs and issues
- Production deployment
- Gradual rollout

## Success Metrics

### Technical KPIs
- API uptime: 99.9%
- API latency: p99 < 500ms
- Error rate: < 0.1%
- Trade execution success: > 99%

### Business KPIs
- User acquisition: 100 users in month 1
- User retention: > 80% month-over-month
- Daily active users: > 60% of total
- User satisfaction: NPS > 50

### Security KPIs
- Zero security breaches
- Zero data leaks
- 100% audit log coverage
- < 1 hour incident response time

## Next Steps

1. **Review this architecture** with stakeholders
2. **Approve technology choices** and vendors
3. **Set up development environment** (Week 1)
4. **Begin implementation** following migration path
5. **Iterate and refine** based on feedback

## Related Documentation

- [Secure API Vault System](./SECURE_API_VAULT_ARCHITECTURE.md)
- [Execution Routing Model](./EXECUTION_ROUTING_ARCHITECTURE.md)
- [Mobile App UX Flow](./MOBILE_APP_UX_ARCHITECTURE.md)
- [Current Architecture](./ARCHITECTURE.md)
- [User Management](./USER_MANAGEMENT.md)
- [Security Guidelines](./SECURITY.md)

---

**Document Version**: 1.0  
**Last Updated**: January 27, 2026  
**Status**: ✅ Comprehensive Design Complete  
**Next Review**: Before Phase 1 implementation

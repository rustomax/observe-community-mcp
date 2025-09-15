# ChatGPT OAuth Integration Design

## Overview

This document outlines the design for enabling ChatGPT to connect to our Observe Community MCP server through OAuth authentication using Stytch Connected Apps.

## Current State

- ✅ Existing JWT authentication infrastructure (`src/auth/`)
- ✅ FastMCP integration with scope-based access control (`@requires_scopes`)
- ✅ SSE transport running on port 8000
- ✅ Bearer token system for programmatic access
- ❌ No OAuth endpoints for ChatGPT integration
- ❌ No Dynamic Client Registration (DCR) support

## Goals

1. Enable ChatGPT users to connect our MCP server as a remote connector
2. Maintain existing authentication system for other clients
3. Minimize implementation complexity and maintenance overhead
4. Ensure security compliance with OAuth 2.1 and MCP specifications

## Chosen Solution: Stytch Connected Apps

### Why Stytch

- **Purpose-built for MCP servers** with dedicated documentation and examples
- **Fastest implementation** (under 1 hour vs weeks for custom OAuth)
- **Reasonable pricing** ($50/month for 10k MAUs vs $23/user/month for Auth0)
- **Working GitHub example** we can adapt: `mcp-stytch-consumer-todo-list`
- **Pre-built OAuth consent UI** with React components

### Rejected Alternatives

- **Custom OAuth**: Too complex, security risks, weeks of development
- **Auth0**: Overcomplicated, expensive ($23/month per user), 2-3 days setup
- **Clerk**: No MCP documentation, Next.js focused
- **WorkOS**: Enterprise SSO focused ($125/month), overkill for our needs

## Architecture Design

### Current Architecture
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   MCP Client    │    │  Observe MCP    │    │   Database      │
│   (Claude Code) │────│     Server      │────│                 │
│                 │    │  (Port 8000)    │    │  PostgreSQL     │
│  Bearer Token   │    │  FastMCP + JWT  │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Target Architecture
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    ChatGPT      │    │  OAuth Server   │    │  Observe MCP    │    │   Database      │
│                 │    │  (Port 8001)    │    │     Server      │    │                 │
│ 1. Register     │───▶│  Stytch Auth    │    │  (Port 8000)    │────│  PostgreSQL     │
│ 2. Authorize    │◄──▶│  Endpoints      │────│  FastMCP + JWT  │    │                 │
│ 3. Get Token    │    │                 │    │                 │    │                 │
│ 4. Call MCP     │────────────────────────────▶│  Tools with     │    │                 │
│                 │                             │  @requires_scopes│    │                 │
└─────────────────┘                             └─────────────────┘    └─────────────────┘

┌─────────────────┐                             ┌─────────────────┐
│  Other Clients  │                             │  Observe MCP    │
│  (Claude Code)  │─────────────────────────────│     Server      │
│  Bearer Token   │                             │  (Port 8000)    │
└─────────────────┘                             └─────────────────┘
```

## Technical Implementation Plan

### 1. Dependencies

Add to `requirements.txt`:
```txt
stytch>=5.0.0           # Stytch OAuth provider
fastapi>=0.95.0         # Already have, but ensure OAuth endpoints
```

### 2. Environment Configuration

Add to `.env`:
```bash
# Stytch OAuth Configuration
STYTCH_PROJECT_ID=project_test_xxx
STYTCH_SECRET=secret_test_xxx
STYTCH_PUBLIC_TOKEN=public_test_xxx
STYTCH_ENVIRONMENT=test

# OAuth Server Configuration
OAUTH_BASE_URL=https://your-domain.com
OAUTH_PORT=8001
```

### 3. OAuth Server Structure

Create new OAuth server alongside existing MCP server:

```
src/
├── oauth/
│   ├── __init__.py
│   ├── server.py          # FastAPI OAuth endpoints
│   ├── stytch_client.py   # Stytch client wrapper
│   └── models.py          # OAuth request/response models
├── auth/                  # Existing auth system (unchanged)
├── observe/               # Existing Observe integration (unchanged)
└── ...
```

### 4. OAuth Endpoints

Required OAuth 2.1 + MCP endpoints:

```python
# OAuth Discovery
GET /.well-known/oauth-authorization-server
GET /.well-known/mcp-resources

# OAuth Flow
POST /oauth/register        # Dynamic Client Registration (DCR)
GET  /oauth/authorize       # Authorization Code flow
POST /oauth/token          # Token exchange

# MCP Protection
GET  /mcp/                 # Protected MCP endpoint with token validation
```

### 5. User Experience Flow

1. **User adds server to ChatGPT**: `https://your-domain.com`
2. **ChatGPT discovers OAuth**: Calls `/.well-known/oauth-authorization-server`
3. **Dynamic registration**: ChatGPT registers as OAuth client via `/oauth/register`
4. **Authorization redirect**: ChatGPT sends user to `/oauth/authorize`
5. **Stytch handles auth**: User sees Stytch-hosted login/consent page
6. **Token exchange**: ChatGPT exchanges auth code for access token
7. **MCP access**: ChatGPT calls `/mcp/` with Bearer token

### 6. Security Model

- **OAuth 2.1 compliance** with PKCE mandatory
- **Stytch-managed security** (no custom crypto/token handling)
- **Existing scope system** (`admin`, `write`, `read`) maps to OAuth scopes
- **Token validation** reuses existing JWT infrastructure
- **HTTPS required** for all OAuth endpoints

### 7. Integration Points

#### With Existing Auth System
```python
# Keep existing FastMCP auth decorators
@requires_scopes(['admin', 'write', 'read'])
async def execute_opal_query(ctx: Context, ...):
    # Existing implementation unchanged
```

#### With Stytch
```python
# New OAuth token validation
async def validate_oauth_token(token: str) -> TokenData:
    result = await stytch_client.sessions.authenticate(token)
    return TokenData(
        client_id=result.session.user_id,
        scopes=result.session.custom_claims.get('scopes', ['read'])
    )
```

## Deployment Considerations

### Development
- Run OAuth server on localhost:8001
- Use Stytch test environment
- Self-signed certificates OK for testing

### Production
- **HTTPS required** (OAuth spec requirement)
- Domain name needed (e.g., `mcp.yourcompany.com`)
- Stytch production environment
- Consider rate limiting on OAuth endpoints

### Scaling
- OAuth server can be separate service/container
- Stytch handles OAuth complexity (no database scaling concerns)
- MCP server scales independently

## Rollout Plan

### Phase 1: Basic OAuth (Week 1)
- Set up Stytch account and configuration
- Implement core OAuth endpoints
- Basic token validation
- Test with ChatGPT locally

### Phase 2: Production Deployment (Week 2)
- HTTPS setup and domain configuration
- Production Stytch environment
- Rate limiting and monitoring
- Documentation for users

### Phase 3: Enhancement (Optional)
- User management UI
- Advanced scope mapping
- Audit logging
- Custom branding (if needed)

## Success Metrics

- **Technical**: ChatGPT successfully connects and calls MCP tools
- **Security**: No security vulnerabilities in OAuth implementation
- **Performance**: OAuth flow completes in <30 seconds
- **Maintenance**: No ongoing OAuth-related issues or complexity

## Risk Mitigation

### Security Risks
- **Mitigation**: Use Stytch (audited OAuth provider) vs custom implementation
- **Backup**: Existing bearer token system continues working

### Implementation Complexity
- **Mitigation**: Follow Stytch's working MCP example closely
- **Backup**: Phased rollout allows early validation

### Vendor Lock-in
- **Mitigation**: OAuth 2.1 is standard, can migrate providers if needed
- **Cost**: Stytch pricing reasonable for expected usage

## Open Questions

1. **User account provisioning**: How do we create/manage users who will authenticate?
2. **Scope mapping**: Should we create more granular scopes for different tool access?
3. **Multi-tenancy**: Do we need to isolate data by organization/team?
4. **Monitoring**: What OAuth-specific metrics do we need to track?

---

**Decision**: Proceed with Stytch Connected Apps implementation
**Timeline**: 1-2 weeks for full implementation
**Next Steps**: Set up Stytch account and development environment
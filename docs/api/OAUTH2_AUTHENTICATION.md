# OAuth2 and OIDC Authentication

This document describes the OAuth2 and OpenID Connect (OIDC) authentication implementation for Docling Pipelines.

## Overview

The authentication system supports:
- **OAuth2 Authorization Code Flow** with PKCE support
- **OpenID Connect (OIDC)** for identity verification
- **JWT token validation** with JWKS
- **Multiple providers**: Google, Azure AD, and generic OIDC providers
- **Flexible authentication**: Support for both Bearer tokens and OAuth2 tokens

## Features

### Supported Providers

1. **Google OAuth2**
   - Pre-configured endpoints
   - Automatic OIDC discovery
   - ID token validation

2. **Azure AD (Microsoft)**
   - Multi-tenant support
   - Azure AD v2.0 endpoints
   - Microsoft Graph integration

3. **Generic OIDC**
   - Works with any OIDC-compliant provider
   - Manual endpoint configuration
   - Supports Okta, Auth0, Keycloak, GitLab, etc.

### Security Features

- **State parameter** for CSRF protection
- **JWT signature verification** using JWKS
- **Token expiration validation**
- **Issuer and audience validation**
- **Session cookie**: the callback sets an `HttpOnly`, `SameSite=Lax` cookie; the token is never placed in a URL
- **Browser-bound login**: a short-lived nonce cookie is tied to `state`, so a login cannot be completed in another browser
- **Per-process state store** (in-memory; see [Authentication and Authorization Guide](../guides/AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md))

For roles, group mapping, redirect URIs per topology and startup validation, see the
[Authentication and Authorization Guide](../guides/AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md).

## Installation

### Required Dependencies

The following packages are already included in `requirements.txt`:
- `httpx>=0.28.1` - HTTP client for OAuth2 requests
- `pyjwt` - JWT token handling
- `pydantic-settings>=2.12.0` - Configuration management
- `fastapi>=0.128.8` - Web framework

## Configuration

### 1. Environment Variables

Copy `.env.oauth2.example` to `.env` and configure:

```bash
cp .env.oauth2.example .env
```

### 2. Google OAuth2 Setup

```env
OAUTH2_ENABLED=true
OAUTH2_PROVIDER=google
OAUTH2_CLIENT_ID=your-client-id.apps.googleusercontent.com
OAUTH2_CLIENT_SECRET=your-client-secret
OAUTH2_REDIRECT_URI=http://localhost:8080/auth/oauth2/callback
JWT_SECRET_KEY=<generated-secret-of-at-least-32-characters>
```

**Setup Steps:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials
5. Add authorized redirect URI: `http://localhost:8080/auth/oauth2/callback`
6. Copy Client ID and Client Secret

### 3. Azure AD Setup

```env
OAUTH2_ENABLED=true
OAUTH2_PROVIDER=azure
AZURE_TENANT_ID=your-tenant-id
OAUTH2_CLIENT_ID=your-application-id
OAUTH2_CLIENT_SECRET=your-client-secret
OAUTH2_REDIRECT_URI=http://localhost:8080/auth/oauth2/callback
JWT_SECRET_KEY=<generated-secret-of-at-least-32-characters>
```

**Setup Steps:**
1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to Azure Active Directory > App registrations
3. Create new registration
4. Add redirect URI: `http://localhost:8080/auth/oauth2/callback`
5. Create client secret under Certificates & secrets
6. Copy Application (client) ID, Directory (tenant) ID, and client secret

### 4. Generic OIDC Provider

```env
OAUTH2_ENABLED=true
OAUTH2_PROVIDER=generic
OAUTH2_DISCOVERY_URL=https://your-provider.com/.well-known/openid-configuration
OAUTH2_CLIENT_ID=your-client-id
OAUTH2_CLIENT_SECRET=your-client-secret
OAUTH2_REDIRECT_URI=http://localhost:8080/auth/oauth2/callback
OIDC_ISSUER=https://your-provider.com
OIDC_AUDIENCE=your-client-id
JWT_SECRET_KEY=<generated-secret-of-at-least-32-characters>
```

## API Endpoints

### OAuth2 Endpoints

#### 1. Initiate Authorization

```http
GET /auth/oauth2/authorize?provider=google
```

Redirects to OAuth2 provider's authorization page.

**Query Parameters:**
- `provider` (optional): Provider name (google, azure, generic)
- `return_to` (optional): relative path to open after a successful login. A path that does not start with `/ui` gets the
  `/ui` prefix, and the default is `/ui/projects`. An absolute, protocol-relative or backslash value is ignored.
- `redirect_after` (optional): deprecated alias of `return_to`

The response also sets a short-lived `HttpOnly` nonce cookie (`docpipe_oauth2_nonce`) that the callback requires.

#### 2. OAuth2 Callback

```http
GET /auth/oauth2/callback?code=xxx&state=xxx&provider=google
```

Handles the OAuth2 callback, exchanges the code for a token and signs the user in.

**Response:** a `302` redirect to the validated `return_to` path (default `/ui/projects`) with a `Set-Cookie` header for the
session cookie (`docpipe_access_token`). The token is no longer returned in the URL fragment (`#access_token=`) or in the
response body. A missing or mismatched nonce cookie, or an unknown or expired `state`, returns `400`.

#### 3. List Available Providers

```http
GET /auth/oauth2/providers
```

Returns list of configured OAuth2 providers.

#### 4. OIDC Discovery

```http
GET /auth/oauth2/discovery/{provider}
```

Returns OIDC discovery document for a provider.

### Existing Endpoints

#### Get Current User

```http
GET /auth/me
Authorization: Bearer <token>
```

Returns the current authenticated user, including `roles`. A browser sends the session cookie instead of the header.
Scripts can obtain a Bearer token from `POST /auth/login`.

Any route under `/api/v1/` is a protected route when `DOCPIPE_AUTH_ENABLED=true`, for example
`GET /api/v1/flows`.

## Usage Examples

### 1. Web Application Flow

```python
import httpx

# Step 1: Redirect user to authorization URL
auth_url = "http://localhost:8080/auth/oauth2/authorize?provider=google"

# Step 2: User completes OAuth2 flow in browser
# User is redirected to /auth/oauth2/callback with code and state

# Step 3: The callback sets the session cookie and redirects to /ui/projects.
# Scripts cannot use this flow; they obtain a Bearer token from POST /auth/login instead.
token = "eyJ..."

# Step 4: Make authenticated requests
async with httpx.AsyncClient() as client:
    response = await client.get(
        "http://localhost:8080/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    user = response.json()
    print(f"Logged in as: {user['username']}")
```

### 2. Testing with cURL

```bash
# Step 1: Get authorization URL (open in browser)
curl http://localhost:8080/auth/oauth2/authorize?provider=google

# Step 2: After the OAuth2 flow the browser holds the session cookie.
# For scripts, obtain a Bearer token from POST /auth/login instead.
TOKEN="your-access-token-here"

# Step 3: Use the token to access protected endpoints
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/auth/me

curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/v1/flows
```

## Architecture

### Components

1. **OAuth2Config** (`oauth2_config.py`)
   - Configuration management for OAuth2 providers
   - Provider-specific settings (Google, Azure, Generic)
   - Environment variable loading

2. **OAuth2Provider** (`oauth2_provider.py`)
   - Base provider class with common OAuth2 logic
   - OIDC discovery and JWKS fetching
   - Token validation and user extraction
   - Provider implementations: GoogleOAuth2Provider, AzureADOAuth2Provider, GenericOIDCProvider

3. **OAuth2Routes** (`oauth2_routes.py`)
   - FastAPI router with OAuth2 endpoints
   - Authorization flow handling
   - Callback processing
   - State management

4. **Dependencies** (`dependencies.py`)
   - FastAPI dependencies for authentication
   - Token validation
   - User extraction from tokens
   - Flexible authentication (Bearer + OAuth2)

### Authentication Flow

```
1. User → GET /auth/oauth2/authorize
2. Server → Redirect to OAuth2 Provider
3. User → Authenticates with Provider
4. Provider → Redirect to /auth/oauth2/callback?code=xxx&state=xxx
5. Server → Exchange code for tokens
6. Server → Validate ID token
7. Server → Extract user info
8. Server → Create JWT token
9. Server → Set session cookie and redirect (302) to return_to
10. Browser → Send the cookie on API requests
```

## Security Considerations

### Production Deployment

1. **Use HTTPS**: Always use HTTPS in production
   ```env
   OAUTH2_REDIRECT_URI=https://your-domain.com/auth/oauth2/callback
   ```

2. **Secure JWT Secret**: Use a strong, random secret key
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

3. **State Storage**: The state store is per process. Use sticky routing for `/auth/oauth2/` when running several workers or replicas

4. **Token Expiration**: Configure appropriate token expiration
   ```env
   JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
   OAUTH2_SESSION_EXPIRE_MINUTES=60
   ```

5. **CORS Configuration**: Restrict allowed origins
   ```env
   CORS_ORIGINS=https://your-frontend.com
   ```

### Best Practices

- Always validate state parameter
- Use PKCE for public clients
- Implement token refresh mechanism
- Store tokens securely (HttpOnly cookies for web apps)
- Implement rate limiting on auth endpoints
- Log authentication events
- Monitor for suspicious activity

## Troubleshooting

### Common Issues

1. **Invalid redirect URI**
   - Ensure redirect URI matches exactly in provider settings
   - Include protocol (http/https) and port

2. **Token validation fails**
   - Check OIDC_ISSUER matches provider's issuer
   - Verify OIDC_AUDIENCE is set correctly
   - Ensure system time is synchronized

3. **State parameter invalid**
   - State expires after use
   - Don't reuse authorization URLs
   - Check state storage implementation

4. **JWKS fetch fails**
   - Verify OAUTH2_JWKS_URI is accessible
   - Check network connectivity
   - Ensure provider's JWKS endpoint is available

## Additional Resources

- [OAuth 2.0 RFC](https://tools.ietf.org/html/rfc6749)
- [OpenID Connect Specification](https://openid.net/specs/openid-connect-core-1_0.html)
- [Google OAuth2 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Azure AD OAuth2 Documentation](https://docs.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-auth-code-flow)
- [FastAPI Security Documentation](https://fastapi.tiangolo.com/tutorial/security/)

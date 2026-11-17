# LDAP Server Setup Guide

## Overview

This guide provides instructions for setting up a local LDAP server for Docling Pipelines authentication and OAuth2 integration. The setup uses OpenLDAP with phpLDAPAdmin for easy management through a web interface.

The LDAP server is configured with:
- Organization: ABC Inc
- Domain: abc.com
- Base DN: `dc=abc,dc=com`
- Pre-configured test users for authentication testing

## Prerequisites

- **Docker** or **Podman** installed on your system
- **docker compose** or **podman-compose** available
- **ldap-utils** package (for command-line verification)
  - Ubuntu/Debian: `sudo apt-get install ldap-utils`
  - macOS: `brew install openldap`
  - RHEL/Fedora: `sudo dnf install openldap-clients`

## Quick Start

### 1. Configure Environment Variables

Copy the example environment file and customize if needed:

```bash
cd examples/LDAP
cp .env.example .env
```

Edit `.env` to set the organization, domain and admin password:
```bash
LDAP_ORGANIZATION=ABCInc
LDAP_DOMAIN=abc.com
LDAP_ADMIN_PASSWORD=changeme
```

`docker-compose.yml` reads `LDAP_ORGANIZATION` and `LDAP_DOMAIN` without fallback values, so all three variables must be set. Compose reads `.env` from the directory that holds the compose file.

**Security Note**: The `.env` file is gitignored to prevent committing sensitive credentials.

### 2. Start the LDAP Server

Navigate to the LDAP directory and start the services:

```bash
cd examples/LDAP

# Using Docker
docker compose up -d

# Using Podman
podman-compose up -d
```

This will start two containers:
- `local-ldap`: OpenLDAP server (ports 1389, 1636)
- `local-ldap-admin`: phpLDAPAdmin web interface (port 8085)

### 3. Load User Data

After the containers are running, load the test users into LDAP:

Use whichever option matches your tooling. All three run from `examples/LDAP`.

```bash
# Option 1: ldapadd from the host (needs the ldap-utils package)
ldapadd -x -H ldap://localhost:1389 -D "cn=admin,dc=abc,dc=com" -w changeme -f abc_users.ldif

# Option 2: Podman, using the client tools inside the container
podman exec -i local-ldap ldapadd -x -H ldap://localhost:389 -D "cn=admin,dc=abc,dc=com" -w changeme < abc_users.ldif

# Option 3: Docker, using the client tools inside the container
docker exec -i local-ldap ldapadd -x -H ldap://localhost:389 -D "cn=admin,dc=abc,dc=com" -w changeme < abc_users.ldif
```

**Note:**
- Replace `changeme` with your `LDAP_ADMIN_PASSWORD` from `.env` if you changed it
- If you see "Already exists" errors, the users are already loaded. This is normal if you've run these commands before.

### 4. Verify Setup

Check that users are loaded correctly:

```bash
ldapsearch -x -H ldap://localhost:1389 -D "cn=admin,dc=abc,dc=com" -w changeme -b "ou=People,dc=abc,dc=com"
```

You should see entries for both `alice` and `charlie`.

## LDIF Files

### abc_users.ldif

Creates the organizational structure and test users:
- **Organizational Unit**: `ou=People,dc=abc,dc=com`
- **User**: Alice Baker (`uid: alice`, `ou: editors`)
  - Email: alice@abc.com
  - Password: `Password123!` <!-- pragma: allowlist secret -->
  - UID: 1003
- **User**: Charlie Brown (`uid: charlie`, `ou: viewers`)
  - Email: charlie@abc.com
  - Password: `Password123!` <!-- pragma: allowlist secret -->
  - UID: 1002

The `ou` attribute of each user is the value Docling Pipelines reads as the user's group (`LDAP_GROUP_ATTRIBUTE=ou`), so `alice` signs in as an editor and `charlie` as a viewer. The passwords are local development credentials only.

Both users have the following object classes:
- `inetOrgPerson`: Standard person entry
- `posixAccount`: UNIX account attributes
- `shadowAccount`: Password aging attributes

## Accessing phpLDAPAdmin

### Web Interface

1. Open your browser and navigate to: **http://localhost:8085**
2. Click "login" on the left sidebar
3. Enter admin credentials:
   - **Login DN**: `cn=admin,dc=abc,dc=com`
   - **Password**: `changeme` (or your custom password from `.env`)

### Browsing Users

After logging in:
1. Expand the tree: `dc=abc,dc=com`
2. Click on `ou=People`
3. You'll see entries for `alice` and `charlie`

### Managing Users

Through phpLDAPAdmin you can:
- View user attributes
- Modify user properties
- Add new users
- Delete users
- Change passwords

## Default Credentials

### LDAP Admin

- **DN**: `cn=admin,dc=abc,dc=com`
- **Password**: `changeme` (default, customize in `.env`)
- **Server**: `localhost:1389`
- **Base DN**: `dc=abc,dc=com`

### Test Users

#### Alice Baker (editor)
- **Username**: `alice`
- **Password**: `Password123!`
- **Group (`ou`)**: `editors`
- **Email**: `alice@abc.com`
- **DN**: `cn=Alice Baker,ou=People,dc=abc,dc=com`

#### Charlie Brown (viewer)
- **Username**: `charlie`
- **Password**: `Password123!`
- **Group (`ou`)**: `viewers`
- **Email**: `charlie@abc.com`
- **DN**: `cn=Charlie Brown,ou=People,dc=abc,dc=com`

## Verifying Setup

### Check Container Status

```bash
# Docker
docker ps | grep ldap

# Podman
podman ps | grep ldap
```

You should see both `local-ldap` and `local-ldap-admin` containers running.

### Test LDAP Connection

```bash
# Test admin bind
ldapwhoami -x -H ldap://localhost:1389 -D "cn=admin,dc=abc,dc=com" -w changeme

# Expected output: dn:cn=admin,dc=abc,dc=com
```

### Test User Authentication

```bash
# Test Alice Baker authentication
ldapwhoami -x -H ldap://localhost:1389 -D "cn=Alice Baker,ou=People,dc=abc,dc=com" -w 'Password123!'

# Test Charlie Brown authentication
ldapwhoami -x -H ldap://localhost:1389 -D "cn=Charlie Brown,ou=People,dc=abc,dc=com" -w 'Password123!'
```

### Search for All Users

```bash
ldapsearch -x -H ldap://localhost:1389 -D "cn=admin,dc=abc,dc=com" -w changeme \
  -b "ou=People,dc=abc,dc=com" "(objectClass=inetOrgPerson)" cn mail uid ou
```

## Troubleshooting

### Containers Won't Start

**Issue**: Port conflicts (8085, 1389, or 1636 already in use)

**Solution**:
- Check what's using the ports: `lsof -i :8085` or `netstat -an | grep 8085`
- Stop conflicting services or modify ports in `docker-compose.yml`

### Cannot Connect to LDAP

**Issue**: Connection refused to localhost:1389

**Solution**:
1. Verify containers are running: `docker ps` or `podman ps`
2. Check container logs: `docker logs local-ldap` or `podman logs local-ldap`
3. Ensure firewall isn't blocking ports
4. Try restarting containers: `docker compose restart` or `podman-compose restart`

### Users Not Found

**Issue**: ldapsearch returns no results

**Solution**:
1. Verify users were loaded: Check for "Already exists" or success messages when running ldapadd
2. Re-run the ldapadd commands with the LDIF files
3. Check phpLDAPAdmin to see if users exist
4. Verify Base DN is correct: `dc=abc,dc=com`

### Authentication Fails

**Issue**: User authentication returns "Invalid credentials"

**Solution**:
1. Verify the test user password is `Password123!`
2. Check DN format is correct: `cn=Alice Baker,ou=People,dc=abc,dc=com`
3. Use phpLDAPAdmin to verify user exists and check attributes
4. Try resetting password through phpLDAPAdmin

### phpLDAPAdmin Not Accessible

**Issue**: Cannot access http://localhost:8085

**Solution**:
1. Verify `local-ldap-admin` container is running
2. Check container logs: `docker logs local-ldap-admin`
3. Try accessing via container IP instead of localhost
4. Clear browser cache or try incognito mode

### LDIF Import Errors

**Issue**: "No such object" error when running ldapadd

**Solution**:
1. Ensure OpenLDAP container is fully started (wait 10-15 seconds after `up -d`)
2. Verify Base DN exists: `ldapsearch -x -H ldap://localhost:1389 -D "cn=admin,dc=abc,dc=com" -w changeme -b "dc=abc,dc=com"`
3. Load `abc_users.ldif` (creates `ou=People`, `alice` and `charlie`)

## Stopping the LDAP Server

To stop the LDAP services:

```bash
# Docker
docker compose down

# Podman
podman-compose down
```

To stop and remove all data (reset to clean state):

```bash
# Docker
docker compose down -v

# Podman
podman-compose down -v
```

## Integration with Docling Pipelines

Authentication is enabled by default. Once LDAP is running, configure Docling Pipelines to use it:

1. Generate a signing secret of at least 32 characters. The API refuses to start without `JWT_SECRET_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Set the environment variables in your docpipe `.env` (project root) or export them before starting the API:
   ```bash
   JWT_SECRET_KEY=<64-hex-character-secret-from-step-1>
   LDAP_SERVER=ldap://localhost:1389
   LDAP_BASE_DN=dc=abc,dc=com
   LDAP_USER_DN=ou=People,dc=abc,dc=com
   LDAP_BIND_DN=cn=admin,dc=abc,dc=com
   LDAP_BIND_PASSWORD=changeme
   # Read each user's group from the "ou" attribute (default: memberOf)
   LDAP_GROUP_ATTRIBUTE=ou
   # Map the "ou" values to roles; separate several groups with ";"
   DOCPIPE_AUTH_ROLE_MAPPING_EDITOR=editors
   DOCPIPE_AUTH_ROLE_MAPPING_VIEWER=viewers
   # DOCPIPE_AUTH_ROLE_MAPPING_ADMIN=<groups that grant admin>
   ```

   Plain OpenLDAP has no `memberOf` overlay, which is why this setup reads `ou` instead. A user that matches no mapped group receives the default role (`viewer`). To skip authentication on a local, trusted machine, set `DOCPIPE_AUTH_ENABLED=false` instead. See the [Authentication and Authorization Guide](../../docs/guides/AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md) for all settings.

3. Start the API and test authentication:
   ```bash
   uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080
   ```
   ```bash
   curl -X POST http://localhost:8080/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username": "alice", "password": "Password123!"}' # pragma: allowlist secret
   ```
   A successful response returns a JWT token. `alice` receives the `editor` role and `charlie` receives `viewer`:
   ```json
   {"access_token": "<jwt-token>", "token_type": "bearer"}
   ```
   Use the token in subsequent requests:
   ```bash
   curl -H "Authorization: Bearer <jwt-token>" http://localhost:8080/api/v1/flows
   ```

4. For OAuth2 integration, refer to [OAuth2 Authentication Guide](../../docs/api/OAUTH2_AUTHENTICATION.md)

## Additional Resources

- [OpenLDAP Documentation](https://www.openldap.org/doc/)
- [phpLDAPAdmin Documentation](http://phpldapadmin.sourceforge.net/wiki/index.php/Main_Page)
- [LDIF Format Specification](https://tools.ietf.org/html/rfc2849)

# Nginx Reverse Proxy Deployment Guide

Complete guide for deploying the Observe MCP Server behind an nginx reverse proxy with SSL/TLS.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Deployment](#detailed-deployment)
- [Client Configuration](#client-configuration)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)
- [Technical Details](#technical-details)

## Overview

The MCP server uses the **streamable-http** protocol, which works with standard HTTP reverse proxy configurations. This guide covers:

- SSL/TLS termination with Let's Encrypt
- HTTP to HTTPS redirection
- JWT authentication pass-through
- Health check endpoints
- Security headers and best practices

### Architecture

```
Client (Claude/MCP)
    ↓ HTTPS (port 443)
Nginx (SSL termination)
    ↓ HTTP (localhost:8000)
Docker MCP Server
    ↓ OPAL queries
Observe Platform
```

### Key Features

- ✅ Standard HTTP reverse proxy (no special streaming config needed)
- ✅ Automatic SSL certificate renewal via Let's Encrypt
- ✅ Security headers (HSTS, X-Frame-Options, etc.)
- ✅ JWT authentication pass-through
- ✅ Optional rate limiting and custom logging

## Prerequisites

- Root/sudo access to your server
- Nginx installed (`sudo apt install nginx`)
- Docker with MCP server running on port 8000
- DNS A record pointing your domain to the server IP
- Ports 80 and 443 open in firewall

### Verify Prerequisites

```bash
# Check nginx is installed
nginx -v

# Check MCP server is running
docker ps | grep observe-mcp
curl http://localhost:8000/health

# Check DNS
dig your-domain.example.com +short

# Check firewall
sudo ufw status | grep -E '80|443'
```

## Quick Start

### Two-Stage Deployment Process

You must deploy in two stages because SSL certificates don't exist initially:

**Stage 1: Get SSL Certificates**
```bash
# Install certbot
sudo apt update && sudo apt install -y certbot python3-certbot-nginx

# Deploy bootstrap config (HTTP only)
sudo cp nginx-mcp-bootstrap.conf /etc/nginx/sites-available/your-domain.example.com
sudo ln -s /etc/nginx/sites-available/your-domain.example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Obtain SSL certificate
sudo certbot certonly --nginx -d your-domain.example.com
```

**Stage 2: Enable HTTPS**
```bash
# Deploy production config
sudo cp nginx-mcp-final.conf /etc/nginx/sites-available/your-domain.example.com
sudo nginx -t && sudo systemctl reload nginx

# Test HTTPS
curl https://your-domain.example.com/health
```

## Detailed Deployment

### Step 1: Prepare Configuration Files

Edit the nginx configuration files before deploying:

1. Open `nginx-mcp-bootstrap.conf`
2. Replace `your-domain.example.com` with your actual domain
3. Save the file

4. Open `nginx-mcp-final.conf`
5. Replace all instances of `your-domain.example.com` with your actual domain
6. Save the file

### Step 2: DNS Configuration

Ensure your DNS A record points to your server:

```bash
# Verify DNS
dig your-domain.example.com +short

# Should return your server's public IP address
```

If DNS isn't set up, configure it with your DNS provider before proceeding.

### Step 3: Firewall Configuration

Allow HTTP and HTTPS traffic:

**Using UFW (Ubuntu/Debian):**
```bash
sudo ufw allow 'Nginx Full'
# Or manually:
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
```

**Using firewalld (CentOS/RHEL):**
```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### Step 4: Deploy Bootstrap Configuration

```bash
# Copy bootstrap config (HTTP only, allows certbot to work)
sudo cp nginx-mcp-bootstrap.conf /etc/nginx/sites-available/your-domain.example.com

# Enable site
sudo ln -s /etc/nginx/sites-available/your-domain.example.com /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Expected output:
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test successful

# Reload nginx
sudo systemctl reload nginx
```

### Step 5: Obtain SSL Certificate

```bash
# Install certbot if not already installed
sudo apt update
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot certonly --nginx -d your-domain.example.com

# Follow prompts:
# - Enter email address for urgent renewal notices
# - Agree to Terms of Service
# - Choose whether to share email with EFF (optional)
```

**Expected Success Output:**
```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/your-domain.example.com/fullchain.pem
Key is saved at:         /etc/letsencrypt/live/your-domain.example.com/privkey.pem
```

**Verify Certificates:**
```bash
sudo ls -l /etc/letsencrypt/live/your-domain.example.com/

# Should show:
# fullchain.pem
# privkey.pem
# chain.pem
# cert.pem
```

### Step 6: Deploy Production Configuration

```bash
# Replace bootstrap config with production config (includes HTTPS)
sudo cp nginx-mcp-final.conf /etc/nginx/sites-available/your-domain.example.com

# Test configuration (should pass now that certificates exist)
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### Step 7: Verify Deployment

```bash
# Test HTTPS connection
curl -I https://your-domain.example.com/health
# Should return: HTTP/2 200

# Test HTTP redirect
curl -I http://your-domain.example.com/health
# Should return: HTTP/1.1 301 Moved Permanently
# Location: https://your-domain.example.com/health

# Check SSL certificate
openssl s_client -connect your-domain.example.com:443 -servername your-domain.example.com </dev/null 2>/dev/null | openssl x509 -noout -dates
```

### Step 8: Monitor Logs

```bash
# Watch access logs
sudo tail -f /var/log/nginx/your-domain.example.com.access.log

# Watch error logs
sudo tail -f /var/log/nginx/your-domain.example.com.error.log

# Watch MCP server logs
docker logs -f observe-mcp-server
```

## Client Configuration

### Update Your MCP Client

After successful deployment, update your MCP client configuration to use the remote server.

**Before (Local):**
```json
{
  "mcpServers": {
    "observe": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_JWT_TOKEN"
      }
    }
  }
}
```

**After (Remote):**
```json
{
  "mcpServers": {
    "observe": {
      "type": "http",
      "url": "https://your-domain.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_JWT_TOKEN"
      }
    }
  }
}
```

### What Changes

- **Protocol**: `http://` → `https://` (SSL encryption)
- **Hostname**: `localhost:8000` → `your-domain.example.com`
- **Port**: Implicit `:443` (HTTPS default)
- **Endpoint**: `/mcp` (unchanged)
- **Token**: Same JWT token (unchanged)

### Client Configuration Files

**Claude Desktop:**

| OS | Configuration Path |
|----|-------------------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

**Testing:**
```bash
# Test health endpoint (no authentication required)
curl https://your-domain.example.com/health

# Test MCP endpoint (authentication required)
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     https://your-domain.example.com/mcp
```

## Troubleshooting

### Common Issues

#### 502 Bad Gateway

**Symptom:** Nginx returns 502 error

**Causes & Solutions:**

```bash
# Cause: MCP server not running
docker ps | grep observe-mcp
docker-compose up -d observe-mcp

# Cause: MCP server crashed
docker logs observe-mcp-server

# Cause: Port 8000 not accessible
netstat -tlnp | grep 8000
```

#### SSL Certificate Errors

**Symptom:** Browser shows SSL warning or certbot fails

**Solutions:**

```bash
# Check certificate status
sudo certbot certificates

# Renew certificate manually
sudo certbot renew --force-renewal

# Check certificate files
sudo ls -l /etc/letsencrypt/live/your-domain.example.com/
```

#### Certbot Fails: "Connection Refused"

**Cause:** Port 80 blocked by firewall

**Solution:**
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload
```

#### Certbot Fails: "Invalid Response"

**Cause:** DNS not pointing to server

**Solution:**
```bash
# Verify DNS is correct
dig your-domain.example.com +short

# Wait for DNS propagation (up to 48 hours)
# Or update DNS A record at your provider
```

#### 403 Forbidden

**Cause:** Invalid or expired JWT token

**Solution:**
```bash
# Generate new token on server
cd /path/to/observe-community-mcp/scripts
./generate_mcp_token.sh 'user@example.com' 'admin,read,write' '720H'

# Update client configuration with new token
```

#### Connection Timeout

**Cause:** Firewall blocking HTTPS

**Solution:**
```bash
# Check firewall rules
sudo ufw status

# Allow HTTPS
sudo ufw allow 443/tcp
sudo ufw reload
```

#### Nginx Configuration Test Fails

**Error:** `nginx: configuration file /etc/nginx/nginx.conf test failed`

**Solutions:**

```bash
# Check syntax errors in config
sudo nginx -t

# View detailed error
sudo nginx -t 2>&1 | grep error

# Common fix: Ensure certificates exist before using production config
sudo ls /etc/letsencrypt/live/your-domain.example.com/
```

### Monitoring and Logs

**Nginx Logs:**
```bash
# Access logs
sudo tail -f /var/log/nginx/your-domain.example.com.access.log

# Error logs
sudo tail -f /var/log/nginx/your-domain.example.com.error.log

# All nginx errors
sudo tail -f /var/log/nginx/error.log
```

**MCP Server Logs:**
```bash
# Follow logs in real-time
docker logs -f observe-mcp-server

# View recent logs
docker logs --tail 100 observe-mcp-server

# Check for errors
docker logs observe-mcp-server 2>&1 | grep -i error
```

**System Logs:**
```bash
# Nginx service status
sudo systemctl status nginx

# System journal for nginx
sudo journalctl -u nginx -f
```

## Advanced Configuration

### Optional: Enable Rate Limiting

Add to `/etc/nginx/nginx.conf` in the `http {}` block:

```nginx
http {
    # ... existing configuration ...

    # Rate limiting for MCP server (100 requests/second)
    limit_req_zone $binary_remote_addr zone=mcp_limit:10m rate=100r/s;

    # ... rest of configuration ...
}
```

Then uncomment in `nginx-mcp-final.conf`:
```nginx
location /mcp {
    limit_req zone=mcp_limit burst=200 nodelay;
    # ... rest of location config
}
```

### Optional: Enable Custom Logging

Add to `/etc/nginx/nginx.conf` in the `http {}` block:

```nginx
http {
    # ... existing configuration ...

    # Custom log format with response times
    log_format mcp_access '$remote_addr - $remote_user [$time_local] '
                          '"$request" $status $body_bytes_sent '
                          '"$http_referer" "$http_user_agent" '
                          'rt=$request_time uct=$upstream_connect_time '
                          'uht=$upstream_header_time urt=$upstream_response_time';

    # ... rest of configuration ...
}
```

Then update in `nginx-mcp-final.conf`:
```nginx
access_log /var/log/nginx/your-domain.example.com.access.log mcp_access;
```

### Optional: IP Whitelisting

Restrict access to specific IP addresses:

```nginx
location /mcp {
    # Allow specific IPs
    allow 203.0.113.0/24;  # Your office network
    allow 198.51.100.10;   # Specific trusted IP
    deny all;

    # ... rest of location config
}
```

### Optional: Basic Authentication

Add an extra layer of authentication:

```bash
# Install apache2-utils
sudo apt install apache2-utils

# Create password file
sudo htpasswd -c /etc/nginx/.htpasswd mcp_user

# Add to location block in nginx config
location /mcp {
    auth_basic "MCP Server";
    auth_basic_user_file /etc/nginx/.htpasswd;
    # ... rest of location config
}
```

### Certificate Auto-Renewal

Certbot automatically sets up a systemd timer for renewal. Verify:

```bash
# Check certbot timer status
sudo systemctl status certbot.timer

# Test renewal process (dry run)
sudo certbot renew --dry-run

# Manual renewal if needed
sudo certbot renew
```

Certificates renew automatically when within 30 days of expiration.

## Technical Details

### MCP Protocol: Streamable-HTTP

The server uses **streamable-http** protocol (not SSE). Key characteristics:

- Standard HTTP POST/GET requests
- Works with HTTP/1.1 and HTTP/2
- No long-lived connections required
- Standard buffering acceptable
- Reasonable timeouts (5 minutes) sufficient

### Nginx Configuration Details

**Key Settings:**

```nginx
# HTTP version - both 1.1 and 2 work
proxy_http_version 1.1;

# Keepalive for performance
proxy_set_header Connection "";

# Standard buffering (unlike SSE)
proxy_buffering on;

# Reasonable timeouts (not 24h like SSE)
proxy_read_timeout 300s;  # 5 minutes

# Pass authentication headers
proxy_pass_request_headers on;
```

### Endpoints

| Endpoint | Purpose | Authentication |
|----------|---------|----------------|
| `/mcp` | MCP protocol interface | Required (JWT) |
| `/health` | Health check | Not required |
| `/` | Info message | Not required |

### Security Features

- SSL/TLS 1.2+ only
- Modern cipher suites
- HSTS header (prevents downgrade attacks)
- X-Frame-Options (prevents clickjacking)
- X-Content-Type-Options (prevents MIME sniffing)
- X-XSS-Protection enabled

### File Locations

| File | Location |
|------|----------|
| Nginx config | `/etc/nginx/sites-available/your-domain.example.com` |
| Symlink | `/etc/nginx/sites-enabled/your-domain.example.com` |
| SSL certificates | `/etc/letsencrypt/live/your-domain.example.com/` |
| Access logs | `/var/log/nginx/your-domain.example.com.access.log` |
| Error logs | `/var/log/nginx/your-domain.example.com.error.log` |

### Performance Considerations

**Upstream with Keepalive:**
The configuration uses persistent connections to the backend for better performance:

```nginx
upstream mcp_backend {
    server localhost:8000;
    keepalive 32;  # Maintains 32 idle connections
}
```

Benefits:
- Reduces TCP connection overhead
- Lower latency for subsequent requests
- Better resource utilization

## Maintenance

### Update Nginx Configuration

```bash
# Edit configuration
sudo nano /etc/nginx/sites-available/your-domain.example.com

# Test changes
sudo nginx -t

# Apply changes
sudo systemctl reload nginx
```

### Force Certificate Renewal

```bash
# Force renewal before 30-day window
sudo certbot renew --force-renewal

# Reload nginx to use new certificate
sudo systemctl reload nginx
```

### Remove Site

```bash
# Remove symlink
sudo rm /etc/nginx/sites-enabled/your-domain.example.com

# Remove configuration
sudo rm /etc/nginx/sites-available/your-domain.example.com

# Revoke certificate
sudo certbot revoke --cert-name your-domain.example.com
sudo certbot delete --cert-name your-domain.example.com

# Reload nginx
sudo systemctl reload nginx
```

### Security Best Practices

1. **Token Rotation**
   - Rotate JWT tokens regularly (every 30-90 days)
   - Use different tokens for dev/prod environments
   - Never commit tokens to git

2. **Certificate Monitoring**
   - Monitor certificate expiration
   - Set up alerts for renewal failures
   - Test auto-renewal process quarterly

3. **Access Logging**
   - Review access logs regularly
   - Monitor for unusual patterns
   - Set up alerting for repeated failures

4. **Updates**
   - Keep nginx updated: `sudo apt update && sudo apt upgrade nginx`
   - Update certbot: `sudo apt upgrade certbot`
   - Monitor security advisories

## Configuration Files Reference

### nginx-mcp-bootstrap.conf

Use this for **Stage 1** (before obtaining SSL certificates):
- HTTP only (port 80)
- Allows Let's Encrypt validation
- Temporary placeholder until certificates exist

### nginx-mcp-final.conf

Use this for **Stage 2** (after obtaining SSL certificates):
- HTTPS with SSL termination
- HTTP to HTTPS redirect
- Full security headers
- Production-ready configuration

Remember to replace `your-domain.example.com` with your actual domain in both files before deploying!

## Support

For issues:
- **Nginx**: Check logs in `/var/log/nginx/`
- **SSL/Certbot**: Run `sudo certbot certificates` and check `/var/log/letsencrypt/`
- **MCP Server**: Check `docker logs observe-mcp-server`
- **Docker**: Run `docker ps` and `docker-compose logs`

## Additional Resources

- [Nginx Documentation](https://nginx.org/en/docs/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [MCP Specification](https://modelcontextprotocol.io/)

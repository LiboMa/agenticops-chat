# SSH Operations Reference

## SSH Connection Troubleshooting

### Connection Failure Decision Tree

```
SSH connection fails
  |
  +-- "Connection refused"
  |     +-- Is sshd running? `systemctl status sshd`
  |     +-- Correct port? `ss -tuln | grep :22` (or custom port)
  |     +-- Firewall blocking? `iptables -L -n | grep 22`
  |     +-- AWS Security Group? Check inbound rules for port 22/custom
  |
  +-- "Connection timed out"
  |     +-- Host reachable? `ping -c 3 HOST`
  |     +-- Route exists? `traceroute HOST`
  |     +-- NACLs blocking? Check VPC Network ACLs for ephemeral ports
  |     +-- Internet Gateway / NAT? Check VPC route table for 0.0.0.0/0
  |
  +-- "Permission denied (publickey)"
  |     +-- Correct user? ec2-user / ubuntu / admin / root
  |     +-- Key permissions? `chmod 600 ~/.ssh/id_rsa`
  |     +-- Key loaded? `ssh-add -l`
  |     +-- Server allows key? Check `/etc/ssh/sshd_config` AuthorizedKeysFile
  |     +-- Correct key for instance? Check EC2 key pair name
  |
  +-- "Host key verification failed"
  |     +-- IP reused? `ssh-keygen -R HOST`
  |     +-- Man-in-the-middle? Verify fingerprint via console/SSM
  |
  +-- "Too many authentication failures"
  |     +-- Too many keys loaded? `ssh-add -D` then add specific key
  |     +-- Specify key explicitly: `ssh -i /path/to/key user@host`
  |
  +-- "Connection reset by peer"
        +-- MaxStartups exceeded? Server under brute-force
        +-- TCP wrapper? Check `/etc/hosts.allow`, `/etc/hosts.deny`
        +-- DenyUsers/AllowUsers in sshd_config?
```

### Verbose Connection Debugging

```bash
# Level 1 — shows auth methods tried
ssh -v user@host

# Level 2 — shows key exchange details
ssh -vv user@host

# Level 3 — full packet-level debug (very noisy)
ssh -vvv user@host

# Common patterns in -v output:
#   "Offering public key:" — which keys client is trying
#   "Server accepts key:" — which key worked
#   "No more authentication methods to try" — all keys rejected
#   "Connection established" — TCP connected, SSH negotiation starts
#   "kex_exchange_identification: Connection closed" — server rejected early
```

### Key Patterns in -v Output

| Pattern | Meaning | Action |
|---------|---------|--------|
| `Connection established` then hang | Firewall allows TCP but blocks SSH | Check stateful firewall / SG |
| `Offering public key: /path/key` | Client trying this key | Verify it matches server's authorized_keys |
| `Server accepts key` | Authentication succeeded | Check if later step fails (shell, PAM) |
| `Permission denied (publickey,gssapi)` | All methods exhausted | Verify key, user, and sshd_config |
| `kex_exchange_identification: read: Connection reset` | Server drops before handshake | MaxStartups, TCP wrappers, or firewall |

## SSH Key Management

### Key Types and Recommendations

| Type | Command | Recommendation |
|------|---------|----------------|
| Ed25519 | `ssh-keygen -t ed25519 -C "comment"` | **Preferred** — fast, small, secure |
| RSA 4096 | `ssh-keygen -t rsa -b 4096 -C "comment"` | Compatible with legacy systems |
| ECDSA | `ssh-keygen -t ecdsa -b 521` | Adequate but Ed25519 preferred |

### SSH Agent Operations

```bash
# Start agent (if not running)
eval "$(ssh-agent -s)"

# Add key (default location)
ssh-add

# Add specific key
ssh-add ~/.ssh/my-key.pem

# List loaded keys
ssh-add -l

# Remove all keys (clean slate)
ssh-add -D

# Add key with timeout (auto-remove after 1 hour)
ssh-add -t 3600 ~/.ssh/my-key.pem

# Forward agent to remote host (for multi-hop)
ssh -A user@bastion
```

### File Permissions (Critical)

```bash
# These permissions are ENFORCED — wrong permissions = key rejected
chmod 700 ~/.ssh
chmod 600 ~/.ssh/id_rsa           # private key
chmod 600 ~/.ssh/id_ed25519       # private key
chmod 644 ~/.ssh/id_rsa.pub       # public key
chmod 644 ~/.ssh/authorized_keys  # server-side
chmod 644 ~/.ssh/config           # client config
chmod 644 ~/.ssh/known_hosts      # known hosts

# AWS .pem key files
chmod 400 ~/keys/my-instance.pem

# Quick fix for "Permissions too open" error
chmod 600 ~/.ssh/*
chmod 644 ~/.ssh/*.pub ~/.ssh/config ~/.ssh/known_hosts ~/.ssh/authorized_keys
```

## SSH Config for Operations

### Multi-Host Configuration

```
# ~/.ssh/config

# Defaults for all hosts
Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
    AddKeysToAgent yes
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new

# Bastion / jump host
Host bastion
    HostName bastion.example.com
    User ec2-user
    IdentityFile ~/.ssh/bastion-key.pem
    ForwardAgent yes

# Production EC2 via bastion (ProxyJump)
Host prod-*
    User ec2-user
    IdentityFile ~/.ssh/prod-key.pem
    ProxyJump bastion

Host prod-web-1
    HostName 10.0.1.10

Host prod-web-2
    HostName 10.0.1.11

Host prod-db-1
    HostName 10.0.2.20

# Staging — direct access
Host staging-*
    User ubuntu
    IdentityFile ~/.ssh/staging-key.pem

Host staging-app
    HostName staging-app.example.com

# Wildcard for dynamic EC2 instances
Host i-*
    User ec2-user
    IdentityFile ~/.ssh/default-key.pem
    ProxyJump bastion
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
```

### Key Config Directives

| Directive | Purpose | Typical Value |
|-----------|---------|---------------|
| `ProxyJump` | Multi-hop via bastion | `bastion` or `user@host:port` |
| `ProxyCommand` | Custom tunnel command | `ssh -W %h:%p bastion` |
| `IdentityFile` | Specific key for host | `~/.ssh/prod-key.pem` |
| `IdentitiesOnly` | Only use specified key | `yes` (prevents agent key spam) |
| `ForwardAgent` | Allow agent forwarding | `yes` (only on trusted bastions) |
| `ServerAliveInterval` | Keepalive interval (sec) | `60` (prevents NAT timeout) |
| `ServerAliveCountMax` | Missed keepalives before disconnect | `3` |
| `ConnectTimeout` | TCP connect timeout (sec) | `10` |
| `StrictHostKeyChecking` | Host key verification | `accept-new` (trust first, verify changes) |
| `ControlMaster` | Connection multiplexing | `auto` (reuse TCP connections) |
| `ControlPath` | Multiplex socket path | `~/.ssh/sockets/%r@%h-%p` |
| `ControlPersist` | Keep master alive (sec) | `600` (10 min after last session) |

## SSH Tunneling for Incident Response

### Local Port Forwarding

Access remote services through SSH tunnel — essential when services aren't publicly exposed.

```bash
# Access remote PostgreSQL (port 5432) via bastion
ssh -L 15432:rds-endpoint.us-east-1.rds.amazonaws.com:5432 ec2-user@bastion
# Then connect locally: psql -h localhost -p 15432 -U admin mydb

# Access remote Redis (port 6379) via bastion
ssh -L 16379:redis-cluster.cache.amazonaws.com:6379 ec2-user@bastion
# Then: redis-cli -h localhost -p 16379

# Access Kubernetes dashboard / Grafana / internal web UI
ssh -L 18080:internal-grafana.svc.cluster.local:3000 ec2-user@bastion
# Then: http://localhost:18080

# Access Elasticsearch (port 9200) on private subnet
ssh -L 19200:vpc-my-domain.us-east-1.es.amazonaws.com:443 ec2-user@bastion
# Then: curl https://localhost:19200 -k

# Multiple forwards in one command
ssh -L 15432:rds:5432 -L 16379:redis:6379 -L 19200:es:443 ec2-user@bastion
```

### Remote Port Forwarding

Expose local service to remote host — useful for debugging with local tools.

```bash
# Expose local debugger (port 5005) to remote host
ssh -R 5005:localhost:5005 ec2-user@remote-host

# Expose local Prometheus/metric endpoint for remote scraping
ssh -R 9090:localhost:9090 ec2-user@remote-host
```

### Dynamic SOCKS Proxy

Route all traffic through SSH tunnel — access entire private network.

```bash
# Create SOCKS5 proxy via bastion
ssh -D 1080 -f -N ec2-user@bastion

# Configure browser or CLI to use proxy:
# curl --socks5 localhost:1080 http://internal-service:8080
# Or set environment: export ALL_PROXY=socks5://localhost:1080

# Useful for accessing internal dashboards, wikis, admin UIs
```

### Tunnel Management

```bash
# Background tunnel (no shell, stays alive)
ssh -f -N -L 15432:rds:5432 ec2-user@bastion

# Tunnel with auto-reconnect (keep-alive + autossh)
autossh -M 0 -f -N -L 15432:rds:5432 \
    -o "ServerAliveInterval=30" -o "ServerAliveCountMax=3" \
    ec2-user@bastion

# Find and kill background tunnels
ps aux | grep "ssh -f -N"
# Or use control sockets:
ssh -O check bastion       # check if master connection alive
ssh -O exit bastion        # close master connection + all tunnels
```

## SCP and File Transfer

### SCP Operations

```bash
# Copy file to remote host
scp /local/file.log ec2-user@host:/remote/path/

# Copy from remote to local
scp ec2-user@host:/var/log/app.log /local/path/

# Copy directory recursively
scp -r ec2-user@host:/var/log/app/ /local/logs/

# Copy via bastion (ProxyJump)
scp -o ProxyJump=bastion /local/fix.sh ec2-user@10.0.1.10:/tmp/

# Bandwidth limit (KB/s) — don't saturate production links
scp -l 1024 largefile.tar.gz ec2-user@host:/tmp/

# Preserve timestamps and permissions
scp -p ec2-user@host:/etc/nginx/nginx.conf ./backup/
```

### rsync Over SSH (Preferred for Large Transfers)

```bash
# Sync directory (incremental, compressed)
rsync -avz -e ssh /local/dir/ ec2-user@host:/remote/dir/

# Sync via bastion
rsync -avz -e "ssh -o ProxyJump=bastion" /local/ ec2-user@10.0.1.10:/remote/

# Dry run (show what would change, don't transfer)
rsync -avzn /local/dir/ ec2-user@host:/remote/dir/

# Bandwidth limit (KB/s)
rsync -avz --bwlimit=1024 -e ssh /local/ ec2-user@host:/remote/

# Sync logs with exclude patterns
rsync -avz --exclude='*.gz' --exclude='*.old' \
    ec2-user@host:/var/log/app/ ./incident-logs/
```

## sshd Server-Side Troubleshooting

### Configuration Verification

```bash
# Test sshd config syntax without restarting
sshd -t

# Test with verbose output (shows effective config)
sshd -T

# Show effective config for a specific user/host match
sshd -T -C user=ubuntu,host=10.0.1.5,addr=10.0.1.5

# Check which config file is active
sshd -T | grep -i "^authorizedkeysfile"

# Key sshd_config directives to check
grep -v "^#\|^$" /etc/ssh/sshd_config
```

### Common sshd_config Issues

| Setting | Issue | Fix |
|---------|-------|-----|
| `PermitRootLogin no` | Cannot SSH as root | Use non-root user, then `sudo` |
| `PasswordAuthentication no` | Password login disabled | Use key-based auth (correct for EC2) |
| `AuthorizedKeysFile` | Custom path set | Ensure keys are in the configured path |
| `AllowUsers` / `AllowGroups` | User not in allow list | Add user or adjust config |
| `MaxSessions 10` | Multiplexed session limit | Increase or close idle sessions |
| `MaxStartups 10:30:60` | Connection rate limit | Increase if under legitimate load |
| `UsePAM yes` | PAM module rejecting | Check `/var/log/secure` or `auth.log` |
| `ChrootDirectory` | Chroot breaking features | Ensure chroot has required dirs/libs |

### Authentication Logging

```bash
# Where SSH auth logs live:
# RHEL/CentOS/Amazon Linux: /var/log/secure
# Ubuntu/Debian: /var/log/auth.log
# Systemd: journalctl -u sshd

# Failed login attempts
grep "Failed password\|Failed publickey" /var/log/secure | tail -20

# Successful logins
grep "Accepted" /var/log/secure | tail -20

# Brute force detection (many failures from same IP)
grep "Failed" /var/log/secure | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn | head -10

# Session open/close tracking
grep "session opened\|session closed" /var/log/secure | tail -20

# Using journalctl
journalctl -u sshd --since "1 hour ago" --no-pager | grep -i "fail\|error\|denied"
```

## Multi-Hop / Jump Host Patterns

### ProxyJump (Recommended — OpenSSH 7.3+)

```bash
# Single hop
ssh -J bastion user@target

# Multi-hop chain
ssh -J bastion1,bastion2 user@target

# With explicit users and ports
ssh -J admin@bastion:2222 ec2-user@10.0.1.10

# Equivalent in config:
# Host target
#     ProxyJump bastion
```

### ProxyCommand (Legacy / Custom)

```bash
# Equivalent to ProxyJump but for older SSH
ssh -o ProxyCommand="ssh -W %h:%p bastion" user@target

# Via AWS SSM (hybrid — SSH through SSM tunnel)
ssh -o ProxyCommand="aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'" ec2-user@i-0123456789abcdef0

# In config:
# Host i-*
#     ProxyCommand aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'
#     User ec2-user
```

### SSH over SSM (No Inbound Port Required)

```bash
# Start SSH session through SSM — no port 22 needed, no bastion needed
aws ssm start-session --target i-0123456789abcdef0

# SSH through SSM tunnel (requires SSM agent + IAM role on instance)
# In ~/.ssh/config:
# Host i-*
#     ProxyCommand sh -c "aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
#     User ec2-user
#     IdentityFile ~/.ssh/my-key.pem

# Then: ssh i-0123456789abcdef0
# This combines SSH key auth security with SSM's IAM-based access
```

## Connection Multiplexing

Reuse SSH connections for faster subsequent logins and transfers.

```bash
# Enable in ~/.ssh/config:
# Host *
#     ControlMaster auto
#     ControlPath ~/.ssh/sockets/%r@%h-%p
#     ControlPersist 600

# Create socket directory
mkdir -p ~/.ssh/sockets

# First connection establishes master
ssh user@host    # opens master connection

# Subsequent connections reuse the master — instant login
ssh user@host    # no handshake, no auth, instant
scp file user@host:/path/  # also reuses master

# Check master connection
ssh -O check user@host

# Close master (and all multiplexed sessions)
ssh -O exit user@host

# Forward new port on existing master connection
ssh -O forward -L 15432:rds:5432 user@host
```

## Security Hardening Quick Reference

### Recommended sshd_config for Production

```
# /etc/ssh/sshd_config — production hardening
Protocol 2
PermitRootLogin no
PasswordAuthentication no
ChallengeResponseAuthentication no
UsePAM yes
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys

# Restrict to specific users/groups
AllowGroups ssh-users ops-team

# Session limits
MaxAuthTries 3
MaxSessions 10
MaxStartups 10:30:60
LoginGraceTime 30

# Timeouts (server-side keepalive)
ClientAliveInterval 300
ClientAliveCountMax 2

# Disable unused features
X11Forwarding no
AllowTcpForwarding yes
GatewayPorts no
PermitTunnel no

# Logging
LogLevel VERBOSE
SyslogFacility AUTH

# Strong crypto (OpenSSH 8.0+)
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com
HostKeyAlgorithms ssh-ed25519,rsa-sha2-512,rsa-sha2-256
```

### Audit Checklist

```bash
# 1. Check SSH version
ssh -V

# 2. Review effective server config
sshd -T | grep -E "^(permitrootlogin|passwordauthentication|pubkeyauthentication|allowusers|allowgroups|maxauthtries|x11forwarding|loglevel)"

# 3. Check authorized_keys for unexpected entries
for user_home in /home/*/; do
    user=$(basename "$user_home")
    ak="$user_home/.ssh/authorized_keys"
    if [ -f "$ak" ]; then
        echo "=== $user ==="
        wc -l "$ak"
        grep -c "command=" "$ak" && echo "  ^ forced commands present"
    fi
done

# 4. Check for SSH keys with no passphrase (risky)
# (cannot determine remotely, but check file permissions)
find /home -name "id_*" -not -name "*.pub" -exec ls -la {} \;

# 5. Check SSH host keys
ls -la /etc/ssh/ssh_host_*

# 6. Check for port forwarding abuse
ss -tuln | grep -v ":22 " | grep "127.0.0.1:"

# 7. Active SSH sessions
who | grep pts
ss -tnp | grep ":22 "
```

## AWS EC2 SSH Patterns

### Default Users by AMI

| AMI | Default User |
|-----|-------------|
| Amazon Linux 2 / 2023 | `ec2-user` |
| Ubuntu | `ubuntu` |
| Debian | `admin` |
| RHEL | `ec2-user` |
| CentOS | `centos` |
| SUSE | `ec2-user` |
| Fedora | `fedora` |
| Bitnami | `bitnami` |

### EC2 Instance Connect (Alternative to Key Pairs)

```bash
# Push temporary key (60 seconds) — no permanent key needed
aws ec2-instance-connect send-ssh-public-key \
    --instance-id i-0123456789abcdef0 \
    --instance-os-user ec2-user \
    --ssh-public-key file://~/.ssh/id_ed25519.pub

# Then SSH normally (within 60 seconds)
ssh ec2-user@i-0123456789abcdef0

# Or use the mssh wrapper (installs temp key + connects)
mssh ec2-user@i-0123456789abcdef0
```

### Lost Key Recovery

```bash
# Option 1: Use SSM (if SSM agent is running + IAM role attached)
aws ssm start-session --target i-0123456789abcdef0
# Then from inside: add new key to ~/.ssh/authorized_keys

# Option 2: Stop instance → detach root volume → attach to helper →
#           mount → edit authorized_keys → reattach → start

# Option 3: EC2 Serial Console (if enabled)
aws ec2-instance-connect send-serial-console-ssh-public-key \
    --instance-id i-0123456789abcdef0 \
    --serial-port 0 \
    --ssh-public-key file://~/.ssh/id_ed25519.pub

# Option 4: User data script (requires stop/start)
# Set user data to inject new key, stop + start instance
```

## Diagnostic Command Reference

| Command | Purpose | Classification |
|---------|---------|----------------|
| `ssh -v user@host` | Debug connection | readonly |
| `ssh-add -l` | List loaded keys | readonly |
| `ssh-keygen -R host` | Remove known_hosts entry | write |
| `ssh-keygen -lf key.pub` | Show key fingerprint | readonly |
| `ssh-keyscan host` | Fetch host public key | readonly |
| `sshd -t` | Test server config | readonly |
| `sshd -T` | Show effective config | readonly |
| `ssh -O check host` | Check multiplex master | readonly |
| `ssh -O exit host` | Close multiplex master | write |
| `ssh -L port:host:port` | Local tunnel | readonly (network) |
| `ssh -R port:host:port` | Remote tunnel | write (exposes port) |
| `ssh -D port` | SOCKS proxy | readonly (network) |

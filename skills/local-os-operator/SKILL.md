---
name: local-os-operator
description: "Local filesystem operations — read configs, tail logs, search files, list directories, inspect file metadata, and write files. Provides secure access to local operational artifacts (Terraform, CloudFormation, Kubernetes manifests, systemd units, nginx configs, application properties, log files). Includes security blocklists for sensitive files."
metadata:
  author: agenticops
  version: "1.1"
  domain: infrastructure
tools:
  - agenticops.tools.file_tools.read_local_file
  - agenticops.tools.file_tools.tail_local_file
  - agenticops.tools.file_tools.search_local_file
  - agenticops.tools.file_tools.list_local_directory
  - agenticops.tools.file_tools.file_stat
  - agenticops.tools.file_tools.write_local_file
---

# Local OS Operator Skill

## Overview

Provides secure access to local files for operational investigation and output.
When this skill is activated, 6 file tools are dynamically registered on the agent:

| Tool | Purpose | Key Args |
|------|---------|----------|
| `read_local_file` | Read file with line numbers | `path`, `offset`, `limit` |
| `tail_local_file` | Read last N lines (logs) | `path`, `lines` |
| `search_local_file` | Case-insensitive grep | `path`, `pattern`, `max_matches` |
| `list_local_directory` | List files with sizes | `path`, `pattern`, `recursive` |
| `file_stat` | File metadata (size, perms, mtime) | `path` |
| `write_local_file` | Write/append text to file | `path`, `content`, `mode` |

## Security Model

Two tiers of protection:

### Always blocked (system-level secrets)
- GnuPG: `~/.gnupg/`
- Docker: `~/.docker/config.json`
- System: `/etc/shadow`, `/etc/gshadow`, `/etc/sudoers`
- Crypto: `.p12`, `.pfx`, `.jks`, `.keystore`, `.gpg`, `.asc`
- App secrets: `.env`, `credentials`, `secrets.yaml`, `service-account.json`, `token`, `master.key`

### Admin paths (unlocked by `AIOPS_FILE_TOOLS_ADMIN_MODE=true`)
- SSH: `~/.ssh/` directory, `id_rsa`, `id_ed25519`, `.pem`, `.key`
- AWS: `~/.aws/credentials`, `~/.aws/config`
- Kubernetes: `~/.kube/config`

Set `AIOPS_FILE_TOOLS_ADMIN_MODE=true` for cluster management use cases
where admins need to inspect SSH configs, AWS profiles, and kubeconfig.

Output is truncated to 4000 chars (single file) or 6000 chars (directory listings)
to prevent agent context overflow.

## Quick Decision Trees

### Finding Configuration Files

```
Need to read a config file
  |
  +-- Know the exact path?
  |     +-- read_local_file(path="/etc/nginx/nginx.conf")
  |
  +-- Know the directory but not the file?
  |     +-- list_local_directory(path="/etc/nginx", pattern="*.conf", recursive=True)
  |     +-- Then read_local_file on the result
  |
  +-- Don't know where configs live?
        +-- Common locations:
        |     /etc/              — system configs
        |     /opt/              — application installs
        |     /var/lib/          — application state
        |     ~/.config/         — user configs
        |     /home/*/           — user home directories
        +-- list_local_directory(path="/etc", pattern="*.conf", recursive=True)
```

### Investigating Log Files

```
Need to check logs
  |
  +-- Recent entries (last 100 lines)?
  |     +-- tail_local_file(path="/var/log/syslog", lines=100)
  |
  +-- Search for specific error?
  |     +-- search_local_file(path="/var/log/syslog", pattern="error")
  |     +-- search_local_file(path="/var/log/nginx/error.log", pattern="502")
  |
  +-- Full log file (first 200 lines)?
  |     +-- read_local_file(path="/var/log/app.log")
  |
  +-- Large log file (specific section)?
        +-- read_local_file(path="/var/log/app.log", offset=1000, limit=50)
```

### Infrastructure-as-Code Inspection

```
Need to check IaC templates
  |
  +-- Terraform?
  |     +-- list_local_directory(path=".", pattern="*.tf", recursive=True)
  |     +-- search_local_file(path="main.tf", pattern="resource")
  |
  +-- CloudFormation?
  |     +-- list_local_directory(path=".", pattern="*.yaml", recursive=True)
  |     +-- search_local_file(path="template.yaml", pattern="Type: AWS::")
  |
  +-- Kubernetes manifests?
  |     +-- list_local_directory(path="./k8s", pattern="*.yaml", recursive=True)
  |     +-- search_local_file(path="deployment.yaml", pattern="replicas")
  |
  +-- Docker?
        +-- read_local_file(path="Dockerfile")
        +-- read_local_file(path="docker-compose.yml")
```

### File Metadata Check

```
Need file info (not content)
  |
  +-- file_stat(path="/var/log/syslog")
  |     → Size, modification time, permissions, owner
  |
  +-- Use cases:
        - Check if log file is growing (compare mtime)
        - Verify permissions on config files
        - Check file size before reading large files
```

## Common Patterns

### Config File Locations by Service

| Service | Config Path | Log Path |
|---------|------------|----------|
| nginx | `/etc/nginx/nginx.conf`, `/etc/nginx/conf.d/*.conf` | `/var/log/nginx/` |
| Apache | `/etc/httpd/conf/httpd.conf`, `/etc/apache2/` | `/var/log/httpd/`, `/var/log/apache2/` |
| systemd | `/etc/systemd/system/*.service` | `journalctl -u service` |
| Docker | `/etc/docker/daemon.json` | `/var/log/docker.log` |
| MySQL | `/etc/my.cnf`, `/etc/mysql/` | `/var/log/mysql/` |
| PostgreSQL | `/etc/postgresql/*/main/` | `/var/log/postgresql/` |
| Redis | `/etc/redis/redis.conf` | `/var/log/redis/` |
| SSH | `/etc/ssh/sshd_config` | `/var/log/auth.log` |
| cron | `/etc/crontab`, `/var/spool/cron/` | `/var/log/cron` |

### Workflow: Verify Config Before Fix

```
1. list_local_directory — discover config files
2. read_local_file — read current config
3. search_local_file — verify specific settings
4. file_stat — check permissions and ownership
5. Include findings in fix plan pre-checks
```

### Workflow: Post-Fix Log Verification

```
1. tail_local_file — check recent log entries after fix
2. search_local_file — search for error patterns
3. Compare with pre-fix state from investigation phase
```

## Tool Reference Quick Card

| Tool | Example | Output |
|------|---------|--------|
| `read_local_file` | `read_local_file(path="/etc/nginx/nginx.conf")` | File content with line numbers |
| `read_local_file` | `read_local_file(path="/var/log/app.log", offset=500, limit=50)` | Lines 501-550 |
| `tail_local_file` | `tail_local_file(path="/var/log/syslog", lines=50)` | Last 50 lines |
| `search_local_file` | `search_local_file(path="/var/log/app.log", pattern="ERROR")` | Matching lines with line numbers |
| `list_local_directory` | `list_local_directory(path="/etc/nginx", pattern="*.conf", recursive=True)` | Files with sizes |
| `file_stat` | `file_stat(path="/etc/nginx/nginx.conf")` | Size, mtime, perms, owner |

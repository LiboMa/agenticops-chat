# Credential Store — Enterprise Multi-Account Authentication

## Problem

AgenticOps stores cloud account credentials as plaintext JSON in the DB `credentials` column. This is insecure for production and doesn't handle cross-partition/cross-cloud scenarios where AssumeRole is unavailable (e.g., AWS Global ↔ AWS China, multi-cloud).

## Goals

1. **Encrypted at rest** — credentials stored encrypted in DB, decrypted only in memory at runtime
2. **Credential source abstraction** — unified model for assume_role, profile, static_keys, environment
3. **Deployment auto-detect** — resolve base credentials from environment (ECS Task Role, IRSA, IMDSv2, profile)
4. **SessionFactory** — single entry point for all AWS/cloud session creation with caching
5. **Available profiles API** — Web UI can show server-side AWS profiles when available

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Application Layer (Agents, Tools, Services)         │
│  Uses: SessionFactory.get_session(account_name)      │
├─────────────────────────────────────────────────────┤
│  SessionFactory (singleton, ~100 lines)              │
│  ├── get_session(account_name, region) → Session     │
│  ├── get_bedrock_session() → Session                 │
│  ├── get_env_for_subprocess(account_name) → dict     │
│  └── detect_environment() → EnvironmentType          │
├─────────────────────────────────────────────────────┤
│  CredentialStore (~80 lines)                         │
│  ├── encrypt(plaintext_dict) → encrypted_bytes       │
│  ├── decrypt(encrypted_bytes) → plaintext_dict       │
│  └── Backend: KMS | LocalKey | Plaintext             │
├─────────────────────────────────────────────────────┤
│  Storage: CloudAccount.credentials (encrypted JSON)  │
│  + CloudAccount.credential_source_type (enum field)  │
└─────────────────────────────────────────────────────┘
```

## Credential Source Types

| Type | Stored Data | Runtime Behavior |
|------|------------|-----------------|
| `environment` | None | Use boto3 default chain |
| `assume_role` | role_arn, external_id, [base_profile] | base session → STS AssumeRole |
| `profile` | profile_name | boto3.Session(profile_name=x) |
| `static_keys` | AK/SK (encrypted) | Decrypt → boto3.Session(ak, sk) |

## Encryption Backends

| Backend | Master Key Source | When Used |
|---------|------------------|-----------|
| `kms` | AWS KMS key ARN | Running in AWS (auto-detect) |
| `local_key` | `AIOPS_MASTER_KEY` env var (Fernet) | Docker / on-prem |
| `plaintext` | None | Local dev (opt-in, `AIOPS_CREDENTIAL_BACKEND=plaintext`) |

Auto-detection priority: KMS (if `AIOPS_KMS_KEY_ID` set) → local_key (if `AIOPS_MASTER_KEY` set) → plaintext (with warning).

## DB Schema Change

Add `credential_source_type` column to `cloud_accounts`:
```sql
ALTER TABLE cloud_accounts ADD COLUMN credential_source_type VARCHAR(20) DEFAULT 'environment';
```

The existing `credentials` JSON column stores:
- For `environment`: `{}` (empty)
- For `assume_role`: `{"role_arn": "...", "external_id": "...", "base_profile": "..."}`
- For `profile`: `{"profile_name": "..."}`
- For `static_keys`: `{"_encrypted": "base64-encoded-ciphertext"}`

## API Endpoints

- `GET /api/settings/available-profiles` — list server-side AWS profiles
- `POST /api/accounts/{id}/test-connection` — validate credentials work
- Existing account CRUD continues to work; `credentials` field is encrypted on write, masked on read

## Files Modified

| File | Change |
|------|--------|
| `src/agenticops/credentials/__init__.py` | NEW — exports |
| `src/agenticops/credentials/store.py` | NEW — CredentialStore + backends |
| `src/agenticops/credentials/session_factory.py` | NEW — SessionFactory |
| `src/agenticops/providers/aws.py` | Use CredentialStore.decrypt() |
| `src/agenticops/providers/base.py` | Import SessionFactory for env detection |
| `src/agenticops/models.py` | Add credential_source_type column |
| `src/agenticops/web/app.py` | Add available-profiles + test-connection endpoints |
| `src/agenticops/tools/account_tools.py` | Encrypt on save, decrypt+mask on read |
| `tests/test_credential_store.py` | NEW — unit tests |

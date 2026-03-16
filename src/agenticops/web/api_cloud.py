"""Multi-cloud account and resource API routes.

New endpoints that work with CloudAccount/CloudResource models.
Coexist with legacy /api/accounts endpoints (AWSAccount).
Legacy endpoints will be deprecated in Chunk 7.
"""

import json
import logging
from datetime import UTC, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

cloud_router = APIRouter(prefix="/api/cloud", tags=["cloud"])


# ── Schemas ───────────────────────────────────────────────────


class CloudAccountCreate(BaseModel):
    """Schema for creating a cloud account."""
    name: str = Field(..., max_length=100)
    provider: str = Field(..., pattern="^(aws|azure|gcp|alicloud)$")
    credentials: dict = Field(default_factory=dict)
    regions: List[str] = Field(default_factory=list)
    labels: dict = Field(default_factory=dict)
    is_enabled: bool = True


class CloudAccountUpdate(BaseModel):
    """Schema for updating a cloud account."""
    name: Optional[str] = Field(None, max_length=100)
    credentials: Optional[dict] = None
    regions: Optional[List[str]] = None
    labels: Optional[dict] = None
    is_enabled: Optional[bool] = None


class CloudAccountResponse(BaseModel):
    """Schema for cloud account response. Never exposes credentials."""
    id: int
    name: str
    provider: str
    is_enabled: bool
    regions: list
    labels: dict
    created_at: Optional[datetime] = None
    last_scanned_at: Optional[datetime] = None
    has_credentials: bool = False  # True if credentials are set, never the actual values

    model_config = {"from_attributes": True}


class CloudResourceResponse(BaseModel):
    """Schema for cloud resource response."""
    id: int
    account_id: int
    provider: str
    region: str
    resource_type: str
    resource_id: str
    name: Optional[str] = ""
    status: str = "unknown"
    managed: bool = True
    tags: dict = {}
    scanned_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ValidateResponse(BaseModel):
    """Schema for credential validation response."""
    valid: bool
    message: str


# ── Account CRUD ──────────────────────────────────────────────


@cloud_router.get("/accounts", response_model=List[CloudAccountResponse])
async def list_cloud_accounts(
    provider: Optional[str] = Query(None, description="Filter by provider"),
    enabled_only: bool = Query(False, description="Only return enabled accounts"),
):
    """List all cloud accounts."""
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        query = session.query(CloudAccount)
        if provider:
            query = query.filter_by(provider=provider.lower())
        if enabled_only:
            query = query.filter_by(is_enabled=True)

        accounts = query.all()
        return [
            CloudAccountResponse(
                id=a.id, name=a.name, provider=a.provider,
                is_enabled=a.is_enabled, regions=a.regions or [],
                labels=a.labels or {}, created_at=a.created_at,
                last_scanned_at=a.last_scanned_at,
                has_credentials=a.credentials_encrypted is not None,
            )
            for a in accounts
        ]


@cloud_router.get("/accounts/{account_id}", response_model=CloudAccountResponse)
async def get_cloud_account(account_id: int):
    """Get a cloud account by ID."""
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Cloud account not found")
        return CloudAccountResponse(
            id=account.id, name=account.name, provider=account.provider,
            is_enabled=account.is_enabled, regions=account.regions or [],
            labels=account.labels or {}, created_at=account.created_at,
            last_scanned_at=account.last_scanned_at,
            has_credentials=account.credentials_encrypted is not None,
        )


@cloud_router.post("/accounts", response_model=CloudAccountResponse, status_code=201)
async def create_cloud_account(account: CloudAccountCreate):
    """Create a new cloud account with encrypted credentials."""
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        existing = session.query(CloudAccount).filter_by(name=account.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Account name already exists")

        db_account = CloudAccount(
            name=account.name,
            provider=account.provider,
            is_enabled=account.is_enabled,
            regions=account.regions,
            labels=account.labels,
        )
        if account.credentials:
            db_account.credentials = account.credentials

        session.add(db_account)
        session.flush()
        return CloudAccountResponse(
            id=db_account.id, name=db_account.name, provider=db_account.provider,
            is_enabled=db_account.is_enabled, regions=db_account.regions or [],
            labels=db_account.labels or {}, created_at=db_account.created_at,
            last_scanned_at=db_account.last_scanned_at,
            has_credentials=db_account.credentials_encrypted is not None,
        )


@cloud_router.put("/accounts/{account_id}", response_model=CloudAccountResponse)
async def update_cloud_account(account_id: int, account: CloudAccountUpdate):
    """Update a cloud account."""
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        db_account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Cloud account not found")

        if account.name is not None:
            db_account.name = account.name
        if account.regions is not None:
            db_account.regions = account.regions
        if account.labels is not None:
            db_account.labels = account.labels
        if account.is_enabled is not None:
            db_account.is_enabled = account.is_enabled
        if account.credentials is not None:
            db_account.credentials = account.credentials

        session.flush()
        return CloudAccountResponse(
            id=db_account.id, name=db_account.name, provider=db_account.provider,
            is_enabled=db_account.is_enabled, regions=db_account.regions or [],
            labels=db_account.labels or {}, created_at=db_account.created_at,
            last_scanned_at=db_account.last_scanned_at,
            has_credentials=db_account.credentials_encrypted is not None,
        )


@cloud_router.delete("/accounts/{account_id}", status_code=204)
async def delete_cloud_account(account_id: int):
    """Delete a cloud account."""
    from agenticops.models import CloudAccount, get_db_session

    with get_db_session() as session:
        db_account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Cloud account not found")
        session.delete(db_account)


@cloud_router.post("/accounts/{account_id}/validate", response_model=ValidateResponse)
async def validate_cloud_account(account_id: int):
    """Validate credentials for a cloud account."""
    from agenticops.models import CloudAccount, get_db_session
    from agenticops.providers.base import get_provider_class

    with get_db_session() as session:
        db_account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Cloud account not found")

        provider_cls = get_provider_class(db_account.provider)
        if not provider_cls:
            raise HTTPException(
                status_code=400,
                detail=f"Provider '{db_account.provider}' not registered. SDK may not be installed.",
            )

        creds = db_account.credentials
        if not creds:
            return ValidateResponse(valid=False, message="No credentials configured")

        try:
            provider = provider_cls(
                account_id=db_account.id,
                credentials=creds,
                regions=db_account.regions or [],
            )
            is_valid = provider.validate_credentials()
            return ValidateResponse(
                valid=is_valid,
                message="Credentials are valid" if is_valid else "Credential validation failed",
            )
        except ImportError as e:
            return ValidateResponse(valid=False, message=f"SDK not installed: {e}")
        except Exception as e:
            return ValidateResponse(valid=False, message=f"Validation error: {e}")


# ── Resources ─────────────────────────────────────────────────


@cloud_router.get("/resources", response_model=List[CloudResourceResponse])
async def list_cloud_resources(
    provider: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    account_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """List cloud resources with filters."""
    from agenticops.models import CloudResource, get_db_session

    with get_db_session() as session:
        query = session.query(CloudResource)
        if provider:
            query = query.filter_by(provider=provider.lower())
        if resource_type:
            query = query.filter(CloudResource.resource_type.ilike(f"%{resource_type}%"))
        if region:
            query = query.filter_by(region=region)
        if account_id:
            query = query.filter_by(account_id=account_id)

        resources = query.limit(limit).all()
        return [CloudResourceResponse.model_validate(r) for r in resources]

"""Cloud account CRUD + connection-test API endpoints — extracted from app.py."""

from typing import List

from fastapi import APIRouter, HTTPException

from agenticops.models import CloudAccount, get_db_session
from agenticops.web.schemas import AccountCreate, AccountResponse, AccountUpdate

router = APIRouter()


@router.get("/api/accounts", response_model=List[AccountResponse])
async def api_list_accounts(provider: str | None = None):
    """List cloud accounts, optionally filtered by provider."""
    with get_db_session() as session:
        q = session.query(CloudAccount)
        if provider:
            q = q.filter(CloudAccount.provider == provider)
        return [AccountResponse.model_validate(a) for a in q.all()]


@router.get("/api/accounts/{account_id}", response_model=AccountResponse)
async def api_get_account(account_id: int):
    """Get account by ID."""
    with get_db_session() as session:
        account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return AccountResponse.model_validate(account)


@router.post("/api/accounts", response_model=AccountResponse, status_code=201)
async def api_create_account(account: AccountCreate):
    """Create a new cloud account. Credentials are encrypted at rest."""
    from sqlalchemy.exc import IntegrityError
    from agenticops.credentials.store import get_credential_store

    # Encrypt sensitive credentials before storage
    store = get_credential_store()
    encrypted_creds = store.encrypt_credentials(account.credentials)

    with get_db_session() as session:
        existing = session.query(CloudAccount).filter(
            CloudAccount.name == account.name
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Account name '{account.name}' already exists")

        db_account = CloudAccount(
            name=account.name,
            provider=account.provider,
            credential_source_type=account.credential_source_type,
            is_enabled=account.is_enabled,
            credentials=encrypted_creds,
            regions=account.regions,
            labels=account.labels,
        )
        session.add(db_account)
        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail=f"Account name '{account.name}' already exists")
        return AccountResponse.model_validate(db_account)


@router.put("/api/accounts/{account_id}", response_model=AccountResponse)
async def api_update_account(account_id: int, account: AccountUpdate):
    """Update an existing cloud account. Credentials re-encrypted on change."""
    from sqlalchemy.exc import IntegrityError
    from agenticops.credentials.store import get_credential_store
    from agenticops.credentials.session_factory import get_session_factory

    with get_db_session() as session:
        db_account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Account not found")

        update_data = account.model_dump(exclude_unset=True)

        # Check name uniqueness before applying
        new_name = update_data.get("name")
        if new_name and new_name != db_account.name:
            conflict = session.query(CloudAccount).filter(
                CloudAccount.name == new_name, CloudAccount.id != account_id
            ).first()
            if conflict:
                raise HTTPException(status_code=409, detail=f"Account name '{new_name}' already exists")

        # Encrypt credentials if being updated
        if "credentials" in update_data and update_data["credentials"]:
            store = get_credential_store()
            update_data["credentials"] = store.encrypt_credentials(update_data["credentials"])

        for key, value in update_data.items():
            setattr(db_account, key, value)

        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail=f"Account name '{new_name or db_account.name}' already exists")

        # Invalidate session cache
        get_session_factory().invalidate(db_account.name)
        return AccountResponse.model_validate(db_account)


@router.delete("/api/accounts/{account_id}", status_code=204)
async def api_delete_account(account_id: int):
    """Delete a cloud account and its associated resources."""
    from sqlalchemy.exc import IntegrityError

    with get_db_session() as session:
        db_account = session.query(CloudAccount).filter_by(id=account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="Account not found")
        try:
            session.delete(db_account)
            session.flush()
        except IntegrityError as e:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete account: it is still referenced by other records ({e.orig})",
            )


@router.post("/api/accounts/{account_id}/test")
async def api_test_account_connection(account_id: int):
    """Test credential chain for an account. Returns success/failure with identity."""
    from agenticops.credentials.session_factory import get_session_factory
    with get_db_session() as session:
        acct = session.query(CloudAccount).filter_by(id=account_id).first()
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
        factory = get_session_factory()
        result = factory.test_connection(acct.name)
        result["provider"] = acct.provider
        result["name"] = acct.name
        return result

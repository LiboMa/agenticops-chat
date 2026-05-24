#!/usr/bin/env python3
"""
Register AWS CLI profiles as AgenticOps cloud accounts.
Accounts:
  - default  → aws-global  (us-west-2, us-east-1)
  - cn-bj    → aws-china   (cn-north-1, cn-northwest-1)
"""
import sys
import json
from datetime import datetime, timezone# Add project to path
sys.path.insert(0, "/home/ubuntu/agenticops-chat/src")

from sqlalchemy import create_engine, text
from agenticops.models import Base, CloudAccount

DB_PATH = "/home/ubuntu/agenticops-chat/data/agenticops.db"
engine = create_engine(f"sqlite:///{DB_PATH}")

# Ensure tables exist
Base.metadata.create_all(engine)

ACCOUNTS = [
    {
        "name": "aws-global",
        "provider": "aws",
        "is_enabled": True,
        "credentials": {"aws_profile": "default"},
        "regions": ["us-west-2", "us-east-1"],
        "labels": {"account_id": "533267047935", "partition": "aws", "iam_user": "sa-malibo"},
    },
    {
        "name": "aws-china",
        "provider": "aws",
        "is_enabled": True,
        "credentials": {"aws_profile": "cn-bj"},
        "regions": ["cn-north-1", "cn-northwest-1"],
        "labels": {"account_id": "113506788061", "partition": "aws-cn", "iam_user": "sa-malibo"},
    },
]

from sqlalchemy.orm import Session

with Session(engine) as session:
    for acct_data in ACCOUNTS:
        # Check if already exists
        existing = session.query(CloudAccount).filter_by(name=acct_data["name"]).first()
        if existing:
            print(f"[SKIP] Account '{acct_data['name']}' already exists (id={existing.id})")
            continue

        acct = CloudAccount(
            name=acct_data["name"],
            provider=acct_data["provider"],
            is_enabled=acct_data["is_enabled"],
            credentials=acct_data["credentials"],
            regions=acct_data["regions"],
            labels=acct_data["labels"],
            created_at=datetime.now(timezone.utc),
        )
        session.add(acct)
        session.flush()
        print(f"[OK] Registered account '{acct.name}' with id={acct.id}")

    session.commit()
    print("\nAll done! Registered accounts:")
    for a in session.query(CloudAccount).all():
        print(f"  id={a.id}  name={a.name}  provider={a.provider}  regions={a.regions}  enabled={a.is_enabled}  labels={a.labels}")

"""
plaid_client.py

Plaid sandbox helper for BudgetMind AI.

- Environment: SANDBOX ONLY
- Countries: US & CA (for real use; sandbox institution is US)
- Products: transactions (includes balances)

Provides:
- exchange_public_token(public_token)
- get_current_balances(access_token)
- get_recent_transactions(access_token, days=30)
- create_sandbox_access_token()  -> {"access_token": ..., "item_id": ...}
"""

import os
import datetime
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv

import plaid
from plaid.api import plaid_api
from plaid.configuration import Configuration
from plaid.api_client import ApiClient
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import (
    TransactionsGetRequestOptions,
)
from plaid.model.sandbox_public_token_create_request import (
    SandboxPublicTokenCreateRequest,
)

# ---------------------------------------------------------------------------
# ENV CONFIG (sandbox only)
# ---------------------------------------------------------------------------

load_dotenv()

PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = os.getenv("PLAID_SECRET")

if not PLAID_CLIENT_ID or not PLAID_SECRET:
    raise RuntimeError("PLAID_CLIENT_ID and PLAID_SECRET must be set in .env")

# We only need TRANSACTIONS (balances come along with it via accounts)
PLAID_PRODUCTS = ["transactions"]
# Only US + CA (for when you add Link; sandbox helper uses US institution)
PLAID_COUNTRY_CODES = ["US", "CA"]

# Default sandbox institution (First Platypus Bank)
PLAID_SANDBOX_INSTITUTION_ID = "ins_109508"


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def get_plaid_client() -> plaid_api.PlaidApi:
    """
    Build and return a PlaidApi client pointed at the Sandbox environment.

    NOTE: We hard-code the sandbox host URL instead of using plaid.Environment
    because some installs don't expose plaid.Environment.
    """
    configuration = Configuration(
        host="https://sandbox.plaid.com",
        api_key={
            "clientId": PLAID_CLIENT_ID,
            "secret": PLAID_SECRET,
            # Explicit API version; optional but fine to keep
            "plaidVersion": "2020-09-14",
        },
    )
    api_client = ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


def _parse_products(products: List[str]):
    return [Products(p.strip()) for p in products if p.strip()]


def _parse_country_codes(codes: List[str]):
    return [CountryCode(c.strip().upper()) for c in codes if c.strip()]


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def exchange_public_token(public_token: str) -> Dict[str, Any]:
    """
    Exchange a public_token (from Link OR from sandbox helper)
    for an access_token + item_id.
    """
    client = get_plaid_client()
    req = ItemPublicTokenExchangeRequest(public_token=public_token)
    resp = client.item_public_token_exchange(req)
    return resp.to_dict()


def get_current_balances(access_token: str) -> Dict[str, Any]:
    """
    Get real-time balances for all accounts linked to an access_token.

    Returns the raw Plaid response as a dict.
    """
    client = get_plaid_client()
    req = AccountsBalanceGetRequest(access_token=access_token)
    resp = client.accounts_balance_get(req)
    return resp.to_dict()


def get_recent_transactions(
    access_token: str,
    days: int = 30,
    account_ids: Optional[List[str]] = None,
    count: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get recent transactions for the last `days` days.

    NOTE: Plaid's client requires account_ids to be a list *or omitted*,
    it must not be None, so we only pass it when we have one.
    """
    client = get_plaid_client()

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)

    # Build options without account_ids when it's None
    if account_ids:
        options = TransactionsGetRequestOptions(
            count=count,
            offset=offset,
            account_ids=account_ids,
        )
    else:
        options = TransactionsGetRequestOptions(
            count=count,
            offset=offset,
        )

    req = TransactionsGetRequest(
        access_token=access_token,
        start_date=start_date,
        end_date=end_date,
        options=options,
    )
    resp = client.transactions_get(req)
    return resp.to_dict()


def create_sandbox_access_token() -> Dict[str, str]:
    """
    SERVER-SIDE ONLY.

    Creates a sandbox public_token and exchanges it for an access_token.

    This lets you "auto-connect" a fake sandbox bank account with a single
    button (no Plaid Link UI) for testing.
    """
    client = get_plaid_client()

    sandbox_req = SandboxPublicTokenCreateRequest(
        institution_id=PLAID_SANDBOX_INSTITUTION_ID,
        initial_products=_parse_products(PLAID_PRODUCTS),
        # In sandbox this is optional, but you *could* also set country_codes:
        # country_codes=_parse_country_codes(PLAID_COUNTRY_CODES),
    )

    sandbox_resp = client.sandbox_public_token_create(sandbox_req)
    public_token = sandbox_resp.public_token

    exchange = exchange_public_token(public_token)
    return {
        "access_token": exchange["access_token"],
        "item_id": exchange["item_id"],
    }

"""Set up Stripe (test mode) for this app, using the Stripe CLI. Safe to re-run.

Prerequisite: a Stripe **test-mode** secret key in ``.env`` as ``STRIPE_SECRET_KEY``.
Then, from the repo root:

    python scripts/stripe_setup.py

Every Stripe call goes through the pinned Stripe CLI container
(``docker compose --profile stripe run stripe-cli ...``). Compose hands the
container the key from ``.env``; the key never passes through this script.

What it does:

1. Refuses a live-mode key (this project runs Stripe in test mode only).
2. Finds the Team and Business monthly prices — by lookup key, else by product
   name — and tags them with lookup keys. Creates the products and prices from
   the app's plan catalog if the account has none.
3. Stops if a Stripe price differs from what the app displays: the UI must
   show what Stripe charges.
4. Creates (or refreshes) a customer-portal configuration that allows switching
   between those two prices, cancelling, and updating the payment method. The
   app passes its id explicitly, so nothing has to be saved in the dashboard.
5. Reads the CLI's webhook signing secret.
6. Writes ``STRIPE_PRICE_TEAM``, ``STRIPE_PRICE_BUSINESS``,
   ``STRIPE_PORTAL_CONFIGURATION`` and ``STRIPE_WEBHOOK_SECRET`` into ``.env``.

Afterwards restart the API and start the webhook forwarder:

    docker compose up -d api
    docker compose --profile stripe up -d stripe-cli
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.entitlements import PAID_PLANS, PLANS, format_price  # noqa: E402

ENV_FILE = ROOT / ".env"
LOOKUP_KEYS = {plan: f"vendor_risk_{plan}_monthly" for plan in PAID_PLANS}
APP_TAG = "vendor-risk"
_WINDOWS_DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"


def _docker() -> str:
    found = os.environ.get("DOCKER_BIN") or shutil.which("docker")
    if not found and Path(_WINDOWS_DOCKER).exists():
        found = _WINDOWS_DOCKER
    if not found:
        sys.exit("Docker was not found. Start Docker Desktop, or set DOCKER_BIN to docker's path.")
    return found


def _cli(*args: str) -> str:
    """Run one Stripe CLI command in its container; return what it printed."""
    cmd = [_docker(), "compose", "--profile", "stripe", "run", "--rm", "--no-deps", "-T",
           "stripe-cli", *args]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          timeout=180, check=False)
    if proc.returncode != 0 and not proc.stdout.strip():
        sys.exit(f"Stripe CLI failed ({' '.join(args[:2])}): {proc.stderr.strip()[-500:]}")
    return proc.stdout.strip()


def stripe(*args: str) -> dict[str, Any]:
    """A Stripe CLI command that prints JSON. Exits with Stripe's message on error."""
    out = _cli(*args)
    try:
        data = json.loads(out)
    except ValueError:
        sys.exit(f"Unexpected Stripe CLI output for {' '.join(args[:2])}: {out[-300:]}")
    if isinstance(data, dict) and "error" in data:
        sys.exit(f"Stripe refused {' '.join(args[:2])}: {data['error'].get('message')}")
    return data


def _data(*pairs: str) -> list[str]:
    """``_data("a=1", "b=2")`` -> ``["-d", "a=1", "-d", "b=2"]``."""
    return [part for pair in pairs for part in ("-d", pair)]


# --------------------------------------------------------------------------- #
# Prices                                                                       #
# --------------------------------------------------------------------------- #
def ensure_price(plan_id: str) -> dict[str, Any]:
    plan, key = PLANS[plan_id], LOOKUP_KEYS[plan_id]
    listing = ("prices", "list", "--limit", "100",
               *_data("active=true", "type=recurring", "expand[]=data.product"))

    tagged = stripe(*listing, *_data(f"lookup_keys[]={key}"))["data"]
    if tagged:
        price, how = tagged[0], "found by lookup key"
    else:
        # A price made by hand in the dashboard has no lookup key: match the
        # product by name, preferring the amount the app displays.
        named = [
            p for p in stripe(*listing)["data"]
            if p["product"].get("active")
            and p["product"]["name"].strip().lower() == plan.name.lower()
            and (p.get("recurring") or {}).get("interval") == "month"
            and p["currency"] == "usd"
        ]
        named.sort(key=lambda p: p["unit_amount"] != plan.price_cents)
        if named:
            price, how = named[0], "found by product name; lookup key added"
            stripe("prices", "update", price["id"],
                   *_data(f"lookup_key={key}", "transfer_lookup_key=true"))
        else:
            product = stripe("products", "create", *_data(
                f"name={plan.name}", f"metadata[app]={APP_TAG}", f"metadata[plan]={plan_id}"))
            price = stripe("prices", "create", *_data(
                f"product={product['id']}", f"unit_amount={plan.price_cents}", "currency=usd",
                "recurring[interval]=month", f"lookup_key={key}"))
            price["product"] = product
            how = "created"

    amount = price["unit_amount"]
    print(f"  {plan.name:<9} {price['id']}  ${amount / 100:,.2f}/month  ({how})")
    if amount != plan.price_cents:
        sys.exit(
            f"\nStripe charges ${amount / 100:,.2f}/month for {plan.name}, but the app shows "
            f"{format_price(plan)}/month.\nMake them match: change the Stripe price, or "
            f"price_cents for {plan_id!r} in app/services/entitlements.py. Nothing was written."
        )
    return price


# --------------------------------------------------------------------------- #
# Customer portal                                                              #
# --------------------------------------------------------------------------- #
def ensure_portal(prices: dict[str, dict[str, Any]]) -> str:
    params = _data(
        "business_profile[headline]=Vendor Risk: manage your subscription",
        "features[invoice_history][enabled]=true",
        "features[payment_method_update][enabled]=true",
        "features[customer_update][enabled]=true",
        "features[customer_update][allowed_updates][0]=email",
        # Cancelling keeps the plan until the paid period ends (the app shows the date).
        "features[subscription_cancel][enabled]=true",
        "features[subscription_cancel][mode]=at_period_end",
        "features[subscription_update][enabled]=true",
        "features[subscription_update][default_allowed_updates][0]=price",
        "features[subscription_update][proration_behavior]=create_prorations",
        f"metadata[app]={APP_TAG}",
    )
    for i, plan_id in enumerate(PAID_PLANS):
        product = prices[plan_id]["product"]
        product_id = product["id"] if isinstance(product, dict) else product
        params += _data(
            f"features[subscription_update][products][{i}][product]={product_id}",
            f"features[subscription_update][products][{i}][prices][0]={prices[plan_id]['id']}",
        )

    configs = stripe("get", "/v1/billing_portal/configurations", *_data("limit=100"))["data"]
    ours = next((c for c in configs
                 if c.get("active") and (c.get("metadata") or {}).get("app") == APP_TAG), None)
    if ours:
        config = stripe("post", f"/v1/billing_portal/configurations/{ours['id']}", *params)
        print(f"  portal    {config['id']}  (refreshed)")
    else:
        config = stripe("post", "/v1/billing_portal/configurations", *params)
        print(f"  portal    {config['id']}  (created)")
    return str(config["id"])


# --------------------------------------------------------------------------- #
# .env                                                                         #
# --------------------------------------------------------------------------- #
def update_env(values: dict[str, str]) -> None:
    """Set each KEY=value in .env, replacing an existing line or appending."""
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    missing = []
    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(lambda _m, line=line: line, text, count=1)
        else:
            missing.append(line)
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n# Stripe test mode (written by scripts/stripe_setup.py)\n" + "\n".join(missing) + "\n"
    ENV_FILE.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    if not re.search(r"^STRIPE_SECRET_KEY=\S", ENV_FILE.read_text(encoding="utf-8")
                     if ENV_FILE.exists() else "", re.MULTILINE):
        sys.exit("Put a Stripe test-mode secret key in .env as STRIPE_SECRET_KEY first.")

    if stripe("get", "/v1/balance").get("livemode"):
        sys.exit("Refusing: STRIPE_SECRET_KEY is a live key. This project uses test mode only.")
    account = stripe("get", "/v1/account")
    name = ((account.get("settings") or {}).get("dashboard") or {}).get("display_name")
    print(f"Stripe account: {name or account.get('id')} (test mode)\n\nPrices and portal:")

    prices = {plan_id: ensure_price(plan_id) for plan_id in PAID_PLANS}
    portal = ensure_portal(prices)

    secret = _cli("listen", "--print-secret").splitlines()[-1].strip()
    if not secret.startswith("whsec_"):
        sys.exit("Could not read the webhook signing secret from the Stripe CLI.")

    update_env({
        "STRIPE_PRICE_TEAM": prices["team"]["id"],
        "STRIPE_PRICE_BUSINESS": prices["business"]["id"],
        "STRIPE_PORTAL_CONFIGURATION": portal,
        "STRIPE_WEBHOOK_SECRET": secret,
    })
    print(
        "\nWrote to .env: STRIPE_PRICE_TEAM, STRIPE_PRICE_BUSINESS, "
        "STRIPE_PORTAL_CONFIGURATION, STRIPE_WEBHOOK_SECRET (value not shown).\n\n"
        "Next:\n"
        "  docker compose up -d api\n"
        "  docker compose --profile stripe up -d stripe-cli\n"
        "Then subscribe from Settings > Plan & billing with card 4242 4242 4242 4242."
    )


if __name__ == "__main__":
    main()

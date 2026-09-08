"""One-time local bootstrap for persistent Hyperpure authentication."""

from __future__ import annotations

import argparse
import getpass
import json
import os

from cryptography.fernet import Fernet

from procurement_assistant.hyperpure_session import (
    HyperpureAuthError,
    HyperpureUnverifiedOutlet,
    build_session_provider,
)
from scrapers.hyperpure import scrape_authenticated_catalogue


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture and encrypt a reusable Hyperpure account session"
    )
    parser.add_argument("--phone", default=os.environ.get("HYPERPURE_PHONE"))
    parser.add_argument("--outlet-id", default=os.environ.get("HYPERPURE_OUTLET_ID"))
    parser.add_argument(
        "--generate-encryption-key",
        action="store_true",
        help="print a new key for local secret-manager setup and exit",
    )
    args = parser.parse_args()
    if args.generate_encryption_key:
        print(Fernet.generate_key().decode("ascii"))
        return 0
    phone = (args.phone or input("Hyperpure account phone number: ")).strip()
    if not phone:
        parser.error("--phone or HYPERPURE_PHONE is required")

    try:
        provider = build_session_provider()
        provider.request_otp(phone)
        print("Hyperpure confirmed the OTP request. Check the registered phone.")
        otp = getpass.getpass("OTP: ").strip()
        if not otp:
            print(json.dumps({"status": "failed", "reason": "OTP was empty"}))
            return 1
        location = provider.complete_otp(phone, otp, args.outlet_id)
        products = scrape_authenticated_catalogue(provider, location)
        if not products:
            raise HyperpureUnverifiedOutlet(
                "authenticated outlet returned no products, so pricing context is unverified"
            )
    except (HyperpureUnverifiedOutlet, ValueError) as exc:
        # A successful sign-in is encrypted before outlet validation, allowing
        # the operator to investigate a Guest Outlet without spending another OTP.
        print(
            json.dumps(
                {
                    "status": "authenticated",
                    "location_verified": False,
                    "reason": str(exc),
                    "next_action": "configure a real service outlet before scheduling",
                }
            )
        )
        return 2
    except HyperpureAuthError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}))
        return 1

    print(
        json.dumps(
            {
                "status": provider.last_status.value,
                "location_verified": True,
                "outlet": location.as_dict(catalogue_verified=True),
                "authenticated_product_count": len(products),
                "next_action": "configure the verified supplier location and scheduled worker",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

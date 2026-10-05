"""Admin accounts from the command line (the dashboard needs a first account to sign in).

    docker compose exec api python -m app.cli create-admin <username>   # prompts for a password
    docker compose exec api python -m app.cli set-password <username>
    docker compose exec api python -m app.cli list-admins

With --generate, a strong random password is created and printed once.
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from .admin.auth import AdminAccounts
from .content import DATA_DIR


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("create-admin", "set-password"):
        p = sub.add_parser(command)
        p.add_argument("username")
        p.add_argument("--generate", action="store_true", help="generate and print a random password")
    sub.add_parser("list-admins")
    args = parser.parse_args()

    accounts = AdminAccounts(DATA_DIR / "admin")
    if args.command == "list-admins":
        for admin in accounts.list():
            print(admin.username)
        return 0
    if args.generate:
        password = secrets.token_urlsafe(18)
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Again: "):
            print("Passwords don't match", file=sys.stderr)
            return 1
    try:
        if args.command == "create-admin":
            accounts.create(args.username, password, created_by="cli")
        else:
            accounts.set_password(args.username, password)
    except (ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"{args.command}: {args.username}" + (f"\npassword: {password}" if args.generate else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""`uv run superadmin create` and `uv run superadmin reset-password`.

For when the web setup page isn't an option (scripts, a forgotten password). The password is asked
for interactively, or read from `SUPERADMIN_PASSWORD` when stdin is not a terminal.
"""

import argparse
import asyncio
import getpass
import os
import sys

from app.core.database import SessionFactory, engine
from app.core.exceptions import AppError
from app.modules.users.service import UserService

MIN_PASSWORD_LENGTH = 8


def _password() -> str:
    if not sys.stdin.isatty():
        password = os.environ.get("SUPERADMIN_PASSWORD", "")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Password (again): "):
            sys.exit("Passwords don't match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


async def _run(args: argparse.Namespace, password: str) -> str:
    try:
        async with SessionFactory() as session:
            users = UserService(session)
            if args.command == "create":
                await users.create_super_admin(
                    email=args.email, password=password, full_name=args.name
                )
                return f"Super admin {args.email} created."
            await users.set_password(args.email, password)
            return f"Password for {args.email} changed."
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="superadmin")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a super admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="Super Admin", help="Name shown in the app")
    reset = commands.add_parser("reset-password", help="Set a new password for any account")
    reset.add_argument("--email", required=True)
    args = parser.parse_args()

    try:
        print(asyncio.run(_run(args, _password())))
    except AppError as exc:
        sys.exit(exc.message)

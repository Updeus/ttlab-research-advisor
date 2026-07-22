from __future__ import annotations

import argparse
import getpass

from sqlmodel import Session, select

from app.admin_accounts import create_admin_user, public_admin
from app.db import create_db_and_tables, engine
from app.models.admin import AdminUser


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage local TTLAB administrator accounts")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Create an administrator")
    create.add_argument("username")
    create.add_argument("--display-name", default="")
    create.add_argument("--password", help="Prefer omitting this option so the password is not saved in shell history")
    create.add_argument("--no-password-change", action="store_true")
    sub.add_parser("list", help="List administrators")
    args = parser.parse_args()
    create_db_and_tables()
    with Session(engine) as session:
        if args.command == "list":
            for user in session.exec(select(AdminUser).order_by(AdminUser.username)).all():
                print(public_admin(user))
            return
        password = args.password or getpass.getpass("Password: ")
        if not args.password:
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise SystemExit("Passwords do not match")
        user = create_admin_user(
            session,
            username=args.username,
            display_name=args.display_name or args.username,
            password=password,
            created_by="bootstrap-cli",
            must_change_password=not args.no_password_change,
        )
        print(f"Created admin {user.username} ({user.user_id})")


if __name__ == "__main__":
    main()

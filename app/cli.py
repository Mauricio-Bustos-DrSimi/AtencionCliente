import argparse
from getpass import getpass

from .db import ROLES, FIXED_ADMIN_USERNAME, get_user, initialize, list_users, save_user, set_account_password
from .security import hash_password


def create_account(username: str, full_name: str, role: str, scope_name: str | None):
    initialize()
    if role == "admin" and username.casefold() != FIXED_ADMIN_USERNAME:
        raise SystemExit("La cuenta administradora debe llamarse admin.")
    if any(row["username"].casefold() == username.casefold() for row in list_users()):
        raise SystemExit(f"The username {username!r} already exists.")
    if role not in ROLES:
        raise SystemExit(f"Unknown role: {role}")
    if role in {
        "jefe_comercial_ventas", "jefe_comercial_franquicias",
        "supervisor_ventas", "supervisor_franquicias", "gerencia",
    } and not scope_name:
        raise SystemExit("This role requires --scope-name.")

    while True:
        password = getpass("New password (minimum 12 characters): ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords did not match. Try again.")
            continue
        try:
            password_hash = hash_password(password)
            break
        except ValueError as exc:
            print(exc)

    if role == "admin":
        set_account_password(FIXED_ADMIN_USERNAME, password_hash)
    else:
        save_user(username, full_name, password_hash, role, scope_name)
    print(f"Account {username!r} created with role {ROLES[role]}.")


def change_password(username: str):
    initialize()
    existing = get_user(username)
    if not existing and username.casefold() != FIXED_ADMIN_USERNAME:
        raise SystemExit(f"No active account found for {username!r}.")
    while True:
        password = getpass("New password (minimum 12 characters): ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords did not match. Try again.")
            continue
        try:
            encoded = hash_password(password)
            break
        except ValueError as exc:
            print(exc)
    set_account_password(username, encoded)
    print(f"Password updated for {username!r}.")


def main():
    parser = argparse.ArgumentParser(description="Manage local application accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    reset_parser = commands.add_parser("set-password")
    reset_parser.add_argument("--username", required=True)

    for command, role, default_name in (
        ("create-admin", "admin", "Application administrator"),
        ("create-user", None, None),
    ):
        subparser = commands.add_parser(command)
        subparser.add_argument("--username", required=True)
        subparser.add_argument("--name", default=default_name)
        if role is None:
            subparser.add_argument("--role", required=True, choices=sorted(ROLES))
            subparser.add_argument("--scope-name")

    args = parser.parse_args()
    if args.command == "set-password":
        change_password(args.username)
        return
    role = "admin" if args.command == "create-admin" else args.role
    name = args.name or args.username
    create_account(args.username, name, role, getattr(args, "scope_name", None))


if __name__ == "__main__":
    main()

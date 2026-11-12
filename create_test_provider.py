
# ==========================================
# ELUNETTE - CREATE TEST SERVICE PROVIDER
# Local development only
# ==========================================

from getpass import getpass
from sqlite3 import IntegrityError

from werkzeug.security import generate_password_hash

from app import app
from database import get_db


def create_provider():

    print("\nELUNETTE - SERVICE PROVIDER SETUP")
    print("--------------------------------")

    # Collect account details
    full_name = input("Full Name: ").strip()

    email = input(
        "Email Address: "
    ).strip().lower()

    password = getpass("Password: ")

    confirm_password = getpass(
        "Confirm Password: "
    )

    # Validate account information
    if not 2 <= len(full_name) <= 100:
        print("Please enter a valid full name.")
        return

    if (
        "@" not in email
        or "." not in email.split("@")[-1]
        or len(email) > 254
    ):
        print("Please enter a valid email address.")
        return

    if len(password) < 12:
        print("Password must have at least 12 characters.")
        return

    if password != confirm_password:
        print("Passwords do not match.")
        return

    # Create account
    with app.app_context():

        db = get_db()

        try:
            db.execute(
                """
                INSERT INTO users (
                    full_name,
                    email,
                    password_hash,
                    role,
                    status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    full_name,
                    email,
                    generate_password_hash(password),
                    "service_provider",
                    "active"
                )
            )

            db.commit()

            print("\nService Provider created successfully!")
            print("Role: service_provider")
            print("Status: active")

        except IntegrityError:
            db.rollback()

            print(
                "\nAn account with this email "
                "already exists."
            )


if __name__ == "__main__":
    create_provider()

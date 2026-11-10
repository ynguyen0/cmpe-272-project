"""Create local-only configuration without writing or displaying shared credentials."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if destination.exists():
    raise SystemExit(".env already exists; edit it locally. No changes made.")
text = (root / ".env.example").read_text()
for name in ["DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "LEXFLOW_DEMO_PASSWORD"]:
    text = text.replace(f"{name}=\n", f"{name}={secrets.token_urlsafe(64)}\n")
with destination.open("x") as file:
    file.write(text)
destination.chmod(0o600)
print("Created ignored .env. View it locally for your demo password; never commit it.")

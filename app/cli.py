import argparse
import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.infrastructure.database import ApiKey, Application, Repository, Tenant
from app.services.security import digest


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value(), hide_parameters=True)
    repository = Repository(engine)
    try:
        async with repository.sessions.begin() as session:
            if args.command == "revoke-key":
                key = await session.get(ApiKey, args.id)
                if key is None:
                    raise SystemExit("API key not found.")
                key.revoked = True
                await repository.audit("api_key_revoked", str(uuid4()), "0" * 32)
                print("API key revoked.")
                return
            if args.command == "bootstrap" and args.output and Path(args.output).exists():
                print("Bootstrap key file already exists; no key was created.")
                return
            tenant = await session.get(Tenant, args.tenant)
            if tenant is None:
                session.add(Tenant(id=args.tenant, allowed_providers=args.providers.split(",")))
                await session.flush()
            application = await session.get(Application, args.application)
            if application and application.tenant_id != args.tenant:
                raise SystemExit("Application belongs to a different tenant.")
            if application is None:
                session.add(Application(id=args.application, tenant_id=args.tenant))
                await session.flush()
            raw = "gw_" + secrets.token_urlsafe(32)
            key_id = str(uuid4())
            session.add(
                ApiKey(
                    id=key_id,
                    application_id=args.application,
                    key_hash=digest(raw),
                    scopes=args.scopes.split(","),
                    expires_at=datetime.now(UTC) + timedelta(days=90),
                )
            )
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8")
            path.chmod(0o600)
            print(f"Created key {key_id}. Read the secret from {path}; keep it out of Git.")
        else:
            print(f"Key ID: {key_id}\nAPI key (shown once): {raw}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage gateway machine credentials.")
    parser.add_argument("command", choices=["create-key", "bootstrap", "revoke-key"])
    parser.add_argument("--id")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--application", default="demo-app")
    parser.add_argument("--providers", default="fake,fake_backup")
    parser.add_argument("--scopes", default="generation:execute,usage:read,providers:read")
    parser.add_argument("--output")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

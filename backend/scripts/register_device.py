import argparse
import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Device
from app.security import hash_device_secret


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register or update one ESP32 device in SQLite")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--device-secret", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--inactive", action="store_true")
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    settings = get_settings()
    await init_db()

    async with SessionLocal() as session:
        query = select(Device).where(Device.id == args.device_id)
        existing = (await session.execute(query)).scalar_one_or_none()

        secret_hash = hash_device_secret(args.device_secret, settings.device_secret_pepper)

        if existing is None:
            session.add(
                Device(
                    id=args.device_id,
                    name=args.name,
                    secret_hash=secret_hash,
                    is_active=not args.inactive,
                )
            )
            action = "created"
        else:
            existing.secret_hash = secret_hash
            existing.name = args.name or existing.name
            existing.is_active = not args.inactive
            action = "updated"

        await session.commit()

    print(f"Device {action}: {args.device_id}")


if __name__ == "__main__":
    asyncio.run(run())

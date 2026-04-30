import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.services.user_service import get_user_by_username, create_user
from app.schemas.user import UserCreate

async def seed_admin():
    async with AsyncSessionLocal() as db:
        admin_user = await get_user_by_username(db, settings.DEFAULT_ADMIN_USER)
        if not admin_user:
            print(f"Creating default admin user: {settings.DEFAULT_ADMIN_USER}")
            user_data = UserCreate(
                username=settings.DEFAULT_ADMIN_USER,
                password=settings.DEFAULT_ADMIN_PASS,
                role="admin",
                is_active=True
            )
            await create_user(db, user_data)
            print("Admin user created successfully.")
        else:
            print("Admin user already exists.")

if __name__ == "__main__":
    asyncio.run(seed_admin())

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    soniox_api_key: str | None = os.environ.get("SONIOX_API_KEY") or None
    soniox_temporary_key_url: str = "https://api.soniox.com/v1/auth/temporary-api-key"


settings = Settings()

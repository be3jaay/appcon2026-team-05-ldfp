import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    soniox_api_key: str | None = os.environ.get("SONIOX_API_KEY") or None
    soniox_temporary_key_url: str = "https://api.soniox.com/v1/auth/temporary-api-key"

    # PSA OpenSTAT PXWeb API. GET returns table metadata, POST runs a query.
    # Table: Labor Force Survey > "Rates Key Employment Indicators".
    openstat_unemployment_url: str = os.environ.get(
        "OPENSTAT_UNEMPLOYMENT_URL",
        "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/1B/LFS/0021B3FKEI2.px",
    )
    # Human-facing page for the same table, for source citations.
    openstat_unemployment_page_url: str = (
        "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__1B__LFS/0021B3FKEI2.px/"
    )
    openstat_timeout_seconds: float = 15.0


settings = Settings()

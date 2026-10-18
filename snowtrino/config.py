from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./snowtrino.db"
    infrastructure_mode: str = "mock"
    mock_trino_endpoint: str = "http://localhost:8080"
    mock_trino_startup_timeout_seconds: int = 120
    terraform_binary: str = "terraform"
    terraform_root: str = "terraform"
    terraform_timeout_seconds: int = 1800
    trino_connect_timeout_seconds: int = 10
    trino_query_timeout_seconds: int = 60
    trino_max_result_rows: int = 1000


settings = Settings()

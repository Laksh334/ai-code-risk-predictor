import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings. Override any value with an env var or a .env file."""

    app_name: str = "AI Code Risk Predictor API"
    version: str = "0.1.0"
    # Comma-separated origins allowed to call the API (frontend dev server).
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # SQLite for local dev; in production e.g.
    # postgresql+psycopg://user:pass@host:5432/risk_predictor
    database_url: str = "sqlite:///./risk_predictor.db"
    # "production" turns on safety checks (no default secret key, no wildcard CORS).
    environment: str = "development"
    # Dev: create tables on startup. Production: false, schema is managed by Alembic migrations.
    auto_create_tables: bool = True

    # --- Auth (Part 3) ---
    # MUST be overridden in production with a long random value, e.g.
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 1 day

    # --- Analysis (C1) ---
    # Past snapshots (every 6 months) computed on a repo's first scan for the trend chart.
    history_points: int = 6

    # --- GitHub App (C2) ---
    # Webhook secret set in the GitHub App settings. Empty = webhooks are refused (fail closed).
    github_webhook_secret: str = ""
    github_app_id: str = ""
    # App private key (PEM). Either the text itself (newlines may be written as \n) or a file path.
    github_private_key: str = ""
    github_private_key_path: str = ""
    # Alternative for testing without an App: a personal access token allowed to comment.
    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    dashboard_url: str = "http://localhost:5173"  # linked from PR comments

    # --- Deployment (E1) ---
    # Folder with the built React app (frontend/dist). When set, this server also serves the
    # dashboard: one service, one URL. The Docker image sets it.
    frontend_dist: str = ""

    model_config = SettingsConfigDict(env_file=".env")

    def model_post_init(self, __context) -> None:
        # Render tells every service its public URL; use it as the dashboard link for PR comments
        # when nothing else was configured (the frontend is served from this same URL).
        render_url = os.environ.get("RENDER_EXTERNAL_URL")
        if render_url and self.dashboard_url == "http://localhost:5173":
            self.dashboard_url = render_url.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def production_problems(self) -> list[str]:
        """Settings that would be unsafe on a public server."""
        problems = []
        if self.secret_key == "dev-only-change-me" or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a long random value (32+ characters)")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must list the real frontend URL(s), not '*'")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL should point to PostgreSQL, not SQLite")
        return problems


settings = Settings()

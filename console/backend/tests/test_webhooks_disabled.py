from app.core.config import settings
from app.main import app


def test_webhooks_are_disabled_in_the_mvp_api() -> None:
    assert settings.webhooks_enabled is False
    assert all("/webhooks" not in path for path in app.openapi()["paths"])

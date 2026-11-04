"""
Root entry point redirecting to backend.main:app for flexible deployment.
"""

from backend.main import app, create_app

__all__ = ["app", "create_app"]

if __name__ == "__main__":
    import uvicorn
    from backend.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level="info",
    )

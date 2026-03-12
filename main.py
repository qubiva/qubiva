import os
import uvicorn

if __name__ == "__main__":
    reload_enabled = os.getenv("LOCAL_DEV", "false").lower() == "true"
    uvicorn.run(
        "app.app:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=reload_enabled
    )

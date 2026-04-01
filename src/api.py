@asynccontextmanager
async def lifespan(application: "FastAPI"):
    global _config
    try:
        _config = load_config()
    except FileNotFoundError:
        logger.warning("config.yaml not found, dashboard will start without active config")
    yield

from app.api import create_app
from app.config import Settings

app = create_app(Settings())

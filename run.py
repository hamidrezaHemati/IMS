"""Entry point to start the IMS web application."""

import os
from ims import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("IMS_HOST", "127.0.0.1")
    port = int(os.environ.get("IMS_PORT", "5000"))
    debug = os.environ.get("IMS_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug)

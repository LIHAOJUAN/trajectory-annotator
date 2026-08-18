#!/usr/bin/env python3
import os
from waitress import serve
from app import app

serve(
    app,
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8765")),
    threads=int(os.environ.get("THREADS", "8")),
)

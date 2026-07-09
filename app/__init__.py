import logging
from flask import Flask

app = Flask(__name__)

# The frontend polls /get_logs every second, which makes Werkzeug's default
# per-request access log ("GET /get_logs HTTP/1.1 200 -") flood the
# terminal with a line every second. Raise it to WARNING so routine
# requests stay quiet but real errors (500s, tracebacks) still show.
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# Import routes after app is created
from . import routes

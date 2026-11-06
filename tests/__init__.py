import os, tempfile
from unittest import mock

_env = mock.patch.dict(os.environ, {"TURNSTILE_USER_CONFIG": os.path.join(tempfile.mkdtemp(), "none.json"), "CLAUDE_CONFIG_DIR": ""})
_env.start()

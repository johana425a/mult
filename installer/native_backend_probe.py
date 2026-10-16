"""Import the packaged settings router, offline and without private state."""
from pathlib import Path
import json
import os
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ.update(DEEPTUTOR_HOME=str(ROOT / 'runtime/install-probe/home'),
                  DEEPTUTOR_WORKSPACE_ROOT=str(ROOT / 'runtime/install-probe/content'),
                  HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'runtime/deeptutor-packages'))
sys.path.insert(0, str(ROOT))

def no_network(*args, **kwargs):
    raise RuntimeError('Network use is prohibited during installation validation')

socket.create_connection = no_network
from deeptutor.services.config import ConfigTestRunner, get_config_test_runner
from deeptutor.api.routers import settings
import deeptutor.services.config.test_runner as runner
for module in (runner, settings):
    Path(module.__file__).resolve().relative_to(ROOT)
print(json.dumps({'passed': True, 'production_config_test_service_present': True,
                  'settings_router_imported': True, 'model_calls': 0}))

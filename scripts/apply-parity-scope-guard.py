# Trigger the one-time PR patch runner after workflow registration.
from pathlib import Path
import subprocess

path = Path('backend/main.py')
text = path.read_text(encoding='utf-8')

old_import = '''from services.startup_validator import validate_startup_secrets\n\nvalidate_startup_secrets()\n'''
new_import = '''from services.startup_validator import validate_startup_secrets\nfrom services.parity_scope_guard import ParityScopeGuardMiddleware\n\nvalidate_startup_secrets()\n'''

old_app = '''app = FastAPI(title="GPI Document Hub API")\n\napp.add_middleware(\n    CORSMiddleware,\n'''
new_app = '''app = FastAPI(title="GPI Document Hub API")\n\n# Square9 cutover scope is AP/Warehouse only. Sales/Inside Sales routers remain\n# imported for post-parity compatibility, but their HTTP paths are fail-closed\n# unless an explicit post-parity override enables them.\napp.add_middleware(ParityScopeGuardMiddleware)\n\napp.add_middleware(\n    CORSMiddleware,\n'''

for label, old, new in (("import", old_import, new_import), ("middleware", old_app, new_app)):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one anchor, found {count}')
    text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')

changed = subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()
if changed != ['backend/main.py']:
    raise SystemExit(f'unexpected changed files: {changed}')

final = path.read_text(encoding='utf-8')
required = (
    'from services.parity_scope_guard import ParityScopeGuardMiddleware',
    'app.add_middleware(ParityScopeGuardMiddleware)',
)
for token in required:
    if token not in final:
        raise SystemExit(f'missing post-patch marker: {token}')

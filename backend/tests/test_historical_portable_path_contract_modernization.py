import ast
from pathlib import Path
TARGET=Path(__file__).parent/"test_step_4d2a_upload_dir_migration_parity.py"
def test_source_uses_portable_path_contract():
    s=TARGET.read_text(); t=ast.parse(s)
    names={n.name for n in ast.walk(t) if isinstance(n,ast.FunctionDef)}
    assert "test_upload_dir_is_root_uploads_child" in names
    assert "test_paths_root_dir_is_paths_module_directory" in names
    assert 'Path("/app/backend")' not in s
    assert 'Path("/app/backend/uploads")' not in s
def test_runtime_paths_are_module_relative():
    import paths
    assert paths.ROOT_DIR.resolve()==Path(paths.__file__).resolve().parent
    assert paths.UPLOAD_DIR.resolve()==(paths.ROOT_DIR/"uploads").resolve()
    assert paths.UPLOAD_DIR.is_dir()

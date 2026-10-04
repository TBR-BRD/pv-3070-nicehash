from unittest.mock import MagicMock, patch

from src.nicehash.manager import NiceHashManager


def make_proc(name, children=None):
    proc = MagicMock()
    proc.info = {"name": name}
    proc.children.return_value = children or []
    return proc


def manager():
    # Forward slashes, not the real "C:\...": os.path.basename only splits
    # on "\\" when Python itself runs on Windows, so a literal backslash
    # path here would parse wrong on this (Linux/macOS) test machine - a
    # test-environment quirk only, not a bug in the actual Windows deployment.
    return NiceHashManager(
        executable="C:/NiceHash/NiceHashMiner.exe",
        working_directory="C:/NiceHash",
        process_name="app_nhm.exe",
        startup_timeout=30,
        stop_timeout=20,
    )


def test_stop_also_terminates_the_backend_child_process():
    """The actual hashing happens in a separate per-algorithm child (e.g.
    gminer.exe) that NiceHash spawns under app_nhm.exe - stop() must reach
    it too, not just the two named launcher/app processes."""
    backend_child = make_proc("gminer.exe")
    app_proc = make_proc("app_nhm.exe", children=[backend_child])
    launcher_proc = make_proc("nicehashminer.exe")

    with patch("src.nicehash.manager.psutil.process_iter", side_effect=lambda attrs: iter([launcher_proc, app_proc])), \
         patch("src.nicehash.manager.psutil.wait_procs", return_value=([], [])):
        m = manager()
        m.stop()

    # Both the app process and its orphaned backend child must have been
    # terminated, not just the two launcher/app processes by name.
    app_proc.terminate.assert_called_once()
    backend_child.terminate.assert_called_once()
    launcher_proc.terminate.assert_called_once()


def test_find_with_children_includes_descendants():
    child = make_proc("gminer.exe")
    parent = make_proc("app_nhm.exe", children=[child])

    with patch("src.nicehash.manager.psutil.process_iter", return_value=iter([parent])):
        m = manager()
        found = m._find_with_children("app_nhm.exe")

    assert parent in found
    assert child in found
    assert len(found) == 2

from app.storage.local import LocalStorage


def test_local_path_rejects_parent_traversal(tmp_path):
    storage = LocalStorage(str(tmp_path / "uploads"))

    try:
        storage.local_path("../secret")
    except ValueError as exc:
        assert "escapes root" in str(exc)
    else:
        raise AssertionError("expected ValueError")

"""Unit tests for artifact session archiving."""

from pathlib import Path

from core.artifact_handler import (
    ArtifactHandler,
    build_archive_folder_name,
    cleanup_orphan_session_dirs,
    sanitize_game_slug,
)


def test_sanitize_game_slug():
    assert sanitize_game_slug("Gem Bonanza") == "GemBonanza"
    assert sanitize_game_slug("Tomb Cat") == "TombCat"
    assert sanitize_game_slug("CMB_COMBO_1025") == "CMBCOMBO1025"


def test_build_archive_folder_name_includes_game_id():
    name = build_archive_folder_name(
        "20260714_103011", "Fruity Bonanza", game_id="JDB-SLOT-114"
    )
    assert name == "20260714_103011_JDB-SLOT-114_FruityBonanza"


def test_build_archive_folder_name_run_and_fail_code():
    name = build_archive_folder_name(
        "20260720_094100",
        "Queen of Inca",
        game_id="FC-SLOT-040",
        run_label="run1",
        fail_code="PRE_BALANCE",
    )
    assert name == "20260720_094100_FC-SLOT-040_QueenofInca_run1_PRE_BALANCE"


def test_archive_session_includes_run_label_and_fail_code(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler.run_label = "run2"
    handler.set_fail_code("SPIN_NETWORK")
    handler._ensure_dirs()
    dest = handler.archive_session(
        "fail", "Zeus", provider="FC", game_id="FC-SLOT-001"
    )
    assert dest is not None
    folder = Path(dest).name
    assert "_run2" in folder
    assert "_SPIN_NETWORK" in folder


def test_archive_session_pass_omits_fail_code(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler.run_label = "run2"
    handler.set_fail_code("PRE_BALANCE")
    handler._ensure_dirs()
    dest = handler.archive_session(
        "pass", "Zeus", provider="FC", game_id="FC-SLOT-001"
    )
    folder = Path(dest).name
    assert "_run2" in folder
    assert "PRE_BALANCE" not in folder


def test_archive_session_moves_to_provider_pass(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler._ensure_dirs()
    (Path(handler.dirs["setup"]) / "probe.png").write_bytes(b"x")

    dest = handler.archive_session(
        "pass", "Gem Bonanza", provider="FC", game_id="FC-SLOT-021"
    )

    assert dest is not None
    norm = dest.replace("\\", "/")
    assert "/FC/pass/" in norm
    assert Path(dest).name.startswith(handler.session_timestamp)
    assert "FC-SLOT-021" in Path(dest).name
    assert "GemBonanza" in Path(dest).name
    assert (Path(dest) / "setup" / "probe.png").is_file()
    assert not Path(tmp_path / handler.session_timestamp).exists()


def test_capture_unique_names_on_repeat(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler._ensure_dirs()

    p1, _ = handler._resolve_capture_path(handler.dirs["setup"], "v_game_load_timeout")
    p2, d2 = handler._resolve_capture_path(handler.dirs["setup"], "v_game_load_timeout")
    p3, d3 = handler._resolve_capture_path(handler.dirs["setup"], "v_game_load_timeout")

    assert p1.endswith("v_game_load_timeout.png")
    assert d2 == "v_game_load_timeout_002"
    assert d3 == "v_game_load_timeout_003"
    assert p2 != p1 and p3 != p2


def test_archive_session_moves_to_provider_fail(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler._ensure_dirs()
    dest = handler.archive_session(
        "fail", "TombCat", provider="JDB", game_id="JDB-SLOT-001"
    )
    norm = dest.replace("\\", "/")
    assert "/JDB/fail/" in norm
    assert "JDB-SLOT-001" in Path(dest).name
    assert "TombCat" in Path(dest).name


def test_archive_session_misc_provider_when_missing(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler._ensure_dirs()
    dest = handler.archive_session("pass", "Unknown")
    assert "/_misc/pass/" in dest.replace("\\", "/")


def test_lazy_init_does_not_create_session_dir(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    assert not Path(handler.base_dir).exists()


def test_discard_ephemeral_removes_root_session(tmp_path):
    handler = ArtifactHandler(root_dir=str(tmp_path))
    handler._ensure_dirs()
    assert Path(handler.base_dir).is_dir()
    assert handler.discard_ephemeral()
    assert not Path(handler.base_dir).exists()


def test_cleanup_orphan_session_dirs(tmp_path):
    orphan = tmp_path / "20260713_123456"
    orphan.mkdir()
    (orphan / "debug").mkdir()
    (tmp_path / "FC").mkdir()
    (tmp_path / "FC" / "pass").mkdir()
    kept = tmp_path / "FC" / "pass" / "20260713_123456_Game"
    kept.mkdir()
    assert cleanup_orphan_session_dirs(str(tmp_path)) == 1
    assert not orphan.exists()
    assert kept.exists()

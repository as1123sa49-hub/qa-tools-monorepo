import logging
import os
import re
import shutil
import time

import allure

logger = logging.getLogger(__name__)

_SESSION_TS_DIR_RE = re.compile(r"^\d{8}_\d{6}$")


def sanitize_game_slug(name: str) -> str:
    """Folder-safe game label, e.g. 'Gem Bonanza' -> 'GemBonanza'."""
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "", (name or "").strip())
    return slug[:40] if slug else "unknown"


def sanitize_provider_slug(provider: str | None) -> str:
    """Folder-safe provider label, e.g. 'FC' -> 'FC'."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "", (provider or "").strip())
    return slug.upper() if slug else "_misc"


def sanitize_game_id_slug(game_id: str | None) -> str:
    """Folder-safe game id, e.g. 'FC-SLOT-021'."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "", (game_id or "").strip())
    return slug[:48] if slug else ""


def build_archive_folder_name(
    session_timestamp: str,
    game_slug: str,
    *,
    game_id: str | None = None,
    run_label: str | None = None,
    fail_code: str | None = None,
) -> str:
    """``{ts}_{gameId}_{Name}[_runN][_FAILCODE]`` when extras present."""
    name_part = sanitize_game_slug(game_slug)
    id_part = sanitize_game_id_slug(game_id)
    if id_part:
        base = f"{session_timestamp}_{id_part}_{name_part}"
    else:
        base = f"{session_timestamp}_{name_part}"
    if run_label:
        safe_run = re.sub(r"[^a-zA-Z0-9_-]+", "", str(run_label).strip())
        if safe_run:
            base = f"{base}_{safe_run}"
    if fail_code:
        safe_code = re.sub(r"[^a-zA-Z0-9_]+", "", str(fail_code).strip().upper())
        if safe_code:
            base = f"{base}_{safe_code}"
    return base


def cleanup_orphan_session_dirs(root_dir: str = "test_artifacts") -> int:
    """Remove leftover test_artifacts/YYYYMMDD_HHMMSS dirs (not under provider/pass|fail)."""
    if not os.path.isdir(root_dir):
        return 0
    removed = 0
    for name in os.listdir(root_dir):
        if not _SESSION_TS_DIR_RE.match(name):
            continue
        path = os.path.join(root_dir, name)
        if not os.path.isdir(path):
            continue
        try:
            shutil.rmtree(path)
            removed += 1
            logger.info("🗑️ Removed orphan artifact session: %s", path)
        except Exception as exc:
            logger.warning("⚠️ Could not remove orphan artifact dir %s: %s", path, exc)
    return removed


class ArtifactHandler:
    """全域測試產物管家 (Global Artifact Handler)
    負責統一管理所有測試產出物（截圖、影片、Debug 資訊）的生命週期與存放路徑。
    """

    def __init__(self, root_dir="test_artifacts"):
        self.root_dir = root_dir
        self.session_timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.base_dir = os.path.join(root_dir, self.session_timestamp)
        self._dirs_ready = False
        self._sync_dir_paths()
        self._capture_seq: dict[tuple[str, str], int] = {}
        # Optional labels written into the archived folder name (run1/run2 + fail code).
        self.run_label: str | None = None
        self.fail_code: str | None = None
        logger.debug("Artifacts prepared at: %s (lazy mkdir)", self.base_dir)

    def _sync_dir_paths(self) -> None:
        self.dirs = {
            "setup": os.path.join(self.base_dir, "setup"),
            "gameplay": os.path.join(self.base_dir, "gameplay"),
            "failures": os.path.join(self.base_dir, "failures"),
            "debug": os.path.join(self.base_dir, "debug"),
            "recordings": os.path.join(self.base_dir, "recordings"),
        }

    def _ensure_dirs(self) -> None:
        if self._dirs_ready:
            return
        for d in self.dirs.values():
            os.makedirs(d, exist_ok=True)
        self._dirs_ready = True
        logger.debug("Artifacts initialized at: %s", self.base_dir)

    def _resolve_capture_path(self, folder: str, name: str) -> tuple[str, str]:
        """Return unique filepath and display name; suffix _002+ on repeats."""
        safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "capture"
        key = (folder, safe)
        seq = self._capture_seq.get(key, 0) + 1
        self._capture_seq[key] = seq
        if seq == 1:
            display = safe
        else:
            display = f"{safe}_{seq:03d}"
        filepath = os.path.join(folder, f"{display}.png")
        return filepath, display

    def capture(self, page, name, category="gameplay", attach_to_allure=False):
        """通用截圖方法"""
        self._ensure_dirs()
        folder = self.dirs.get(category, self.dirs["debug"])
        filepath, display_name = self._resolve_capture_path(folder, name)

        if page is None:
            logger.error("Cannot capture screenshot for %s: page is None", name)
            return None

        try:
            page.screenshot(path=filepath)
            if category == "failures":
                logger.info("📸 failure capture: %s → %s", display_name, filepath)
            else:
                logger.debug("capture %s [%s] → %s", display_name, category, filepath)

            if attach_to_allure:
                with open(filepath, "rb") as f:
                    allure.attach(
                        f.read(),
                        name=display_name,
                        attachment_type=allure.attachment_type.PNG,
                    )
                logger.debug("Allure attach: %s", display_name)
            return filepath
        except Exception as e:
            logger.warning(f"⚠️ Snapshot failed for {name}: {e}")
            return None

    def move_video(self, src_path, new_name):
        """將 Playwright 產生的暫存影片移動並重命名到標準歸檔目錄"""
        if not os.path.exists(src_path):
            return None

        self._ensure_dirs()
        dst_filename = f"{new_name}.webm"
        dst_path = os.path.join(self.dirs["recordings"], dst_filename)

        try:
            shutil.move(src_path, dst_path)
            logger.info(f"🎥 Video archived: {dst_path}")
            return dst_path
        except Exception as e:
            logger.error(f"Failed to move video: {e}")
            return src_path

    def discard_ephemeral(self) -> bool:
        """Delete session folder when still under root (not archived to pass/fail)."""
        if not os.path.isdir(self.base_dir):
            return False
        root = os.path.normpath(self.root_dir)
        parent = os.path.normpath(os.path.dirname(self.base_dir))
        if parent != root:
            return False
        try:
            shutil.rmtree(self.base_dir)
            self._dirs_ready = False
            logger.debug("Discarded ephemeral artifacts: %s", self.base_dir)
            return True
        except Exception as exc:
            logger.warning("⚠️ Could not discard ephemeral artifacts %s: %s", self.base_dir, exc)
            return False

    def set_fail_code(self, code: str | None) -> None:
        """Record fail code for folder naming (e.g. PRE_BALANCE)."""
        if code:
            self.fail_code = re.sub(r"[^a-zA-Z0-9_]+", "", str(code).strip().upper()) or None

    def archive_session(
        self,
        outcome: str,
        game_slug: str,
        *,
        provider: str | None = None,
        game_id: str | None = None,
        run_label: str | None = None,
        fail_code: str | None = None,
    ) -> str | None:
        """Move session folder to test_artifacts/{provider}/{pass|fail}/{ts}_{id}_{name}[_runN][_CODE]/."""
        if not os.path.isdir(self.base_dir):
            return None

        bucket = "pass" if outcome == "pass" else "fail"
        provider_part = sanitize_provider_slug(provider)
        label = run_label if run_label is not None else self.run_label
        code = fail_code if fail_code is not None else self.fail_code
        # Pass folders keep run label but omit fail code.
        if outcome == "pass":
            code = None
        folder_name = build_archive_folder_name(
            self.session_timestamp,
            game_slug,
            game_id=game_id,
            run_label=label,
            fail_code=code,
        )
        dest_parent = os.path.join(self.root_dir, provider_part, bucket)
        os.makedirs(dest_parent, exist_ok=True)
        dest = os.path.join(dest_parent, folder_name)

        if os.path.normpath(self.base_dir) == os.path.normpath(dest):
            return dest

        if os.path.exists(dest):
            dest = os.path.join(dest_parent, f"{folder_name}_{int(time.time())}")

        try:
            shutil.move(self.base_dir, dest)
            self.base_dir = dest
            self._sync_dir_paths()
            self._dirs_ready = True
            logger.info(f"📦 Artifacts archived: {dest}")
            return dest
        except Exception as e:
            logger.error(f"Failed to archive artifacts to {dest}: {e}")
            return self.base_dir

import logging
import os
import time

import cv2
import numpy as np

from core.visual_auditor import VisualAuditor

logger = logging.getLogger(__name__)


class VideoAuditor:
    """影片視覺審查員 - V3 抗轉場誤判版"""

    @staticmethod
    def audit_video_file(video_path, check_every_n_frames=3, skip_first_seconds=15):
        if not os.path.exists(video_path):
            logger.error(f"Video not found: {video_path}")
            return []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        skip_frames = int(skip_first_seconds * fps)

        errors = []
        frame_idx = 0

        prev_frame_gray = None
        freeze_frame_counter = 0

        consecutive_visual_errors = 0
        last_error_type = None

        logger.info(
            f"🕵️ Scanning {os.path.basename(video_path)} ({total_frames} frames, "
            f"skipping first {skip_first_seconds}s)..."
        )
        start_time = time.time()

        while True:
            if not cap.grab():
                break

            if frame_idx % check_every_n_frames == 0:
                ret, frame = cap.retrieve()
                if not ret:
                    break

                timestamp = frame_idx / fps

                if frame_idx < skip_frames:
                    frame_idx += 1
                    continue

                is_valid, reason = VisualAuditor.check_screen_validity(frame)

                if not is_valid:
                    if reason == last_error_type:
                        consecutive_visual_errors += 1
                    else:
                        consecutive_visual_errors = 1
                        last_error_type = reason

                    error_persistence_threshold = 15

                    if "Pink" in reason:
                        error_persistence_threshold = 3

                    if consecutive_visual_errors == error_persistence_threshold:
                        logger.error(
                            f"❌ Persistent Failure confirmed at {timestamp:.2f}s: {reason}",
                        )
                        errors.append((timestamp, reason))
                else:
                    consecutive_visual_errors = 0
                    last_error_type = None

                try:
                    curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if prev_frame_gray is not None:
                        diff = cv2.absdiff(curr_gray, prev_frame_gray)
                        non_zero = np.count_nonzero(diff > 5)

                        if non_zero < 100:
                            freeze_frame_counter += 1
                        else:
                            freeze_frame_counter = 0

                        real_freeze_seconds = (freeze_frame_counter * check_every_n_frames) / fps

                        if real_freeze_seconds > 8.0:
                            if 8.0 < real_freeze_seconds < 8.5:
                                msg = "Animation Freeze (Main Thread Hang)"
                                errors.append((timestamp, msg))
                                logger.error(f"❄️ {msg} detected at {timestamp:.1f}s")

                    prev_frame_gray = curr_gray.copy()
                except Exception:
                    pass

            frame_idx += 1

        cap.release()
        audit_time = time.time() - start_time
        speed = total_frames / audit_time if audit_time > 0 else 0
        logger.info(f"✅ Audit Done in {audit_time:.2f}s (Speed: {speed:.0f} fps)")

        return errors

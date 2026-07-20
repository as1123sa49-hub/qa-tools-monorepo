import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class VisualAuditor:
    """視覺審查核心 (Visual Core) - V3 生產環境版"""

    @staticmethod
    def check_screen_validity(screenshot_bytes_or_img):
        img = None
        if isinstance(screenshot_bytes_or_img, bytes):
            nparr = np.frombuffer(screenshot_bytes_or_img, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        elif isinstance(screenshot_bytes_or_img, np.ndarray):
            img = screenshot_bytes_or_img

        if img is None:
            return False, "Image Decode Failed"

        h, w = img.shape[:2]
        target_width = 320
        if w > target_width:
            scale = target_width / w
            img_small = cv2.resize(img, (0, 0), fx=scale, fy=scale)
        else:
            img_small = img

        if VisualAuditor._has_pink_glitch(img_small):
            return False, "Pink Glitch (Missing Texture) Detected"

        if VisualAuditor._is_dead_screen(img_small):
            return False, "Dead Screen (Black/White) Detected"

        return True, "PASS"

    @staticmethod
    def _has_pink_glitch(img):
        """檢查 Unity 常見的 Missing Shader (洋紅色)"""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_magenta = np.array([140, 200, 200])
        upper_magenta = np.array([170, 255, 255])
        mask = cv2.inRange(hsv, lower_magenta, upper_magenta)

        kernel = np.ones((3, 3), np.uint8)
        mask_clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)

        contours, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 50:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            rect_area = w * h
            rectangularity = area / rect_area

            if rectangularity > 0.8:
                return True
        return False

    @staticmethod
    def _is_dead_screen(img):
        """檢測死黑或死白畫面"""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        total_pixels = gray.size

        black_pixels = cv2.countNonZero(cv2.inRange(gray, 0, 5))
        black_ratio = black_pixels / total_pixels

        if black_ratio > 0.98:
            return True

        white_pixels = cv2.countNonZero(cv2.inRange(gray, 250, 255))
        white_ratio = white_pixels / total_pixels

        if white_ratio > 0.98:
            return True

        return False

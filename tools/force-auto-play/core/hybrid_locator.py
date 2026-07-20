import io
import logging
import time

from PIL import Image

logger = logging.getLogger(__name__)


class HybridLocator:
    """Orchestrates VLM (Discovery) and OCR (Refinement) for a 'Relay' (接力) effect."""

    def __init__(self, vision_client, ui_locator):
        self.vision = vision_client
        self.ocr = ui_locator
        self._coord_cache = {}

    @staticmethod
    def compute_dpr(img_width, viewport_width):
        if viewport_width > 0:
            return img_width / viewport_width
        return 1.0

    @staticmethod
    def to_viewport(x, y, dpr):
        return (x / dpr, y / dpr)

    def get_cached_coords(self, key):
        return self._coord_cache.get(key)

    def set_cached_coords(self, key, coords):
        self._coord_cache[key] = coords

    def clear_cache(self, key=None):
        if key:
            self._coord_cache.pop(key, None)
        else:
            self._coord_cache.clear()

    def find_and_refine(self, page, target_description, context="all", keywords=None):
        """1. VLM identifies the area.
        2. Crop area.
        3. OCR refines/verifies text in the crop.

        keywords: optional list of strings to match against OCR text (overrides
                  auto-extracted keywords from target_description).
        """
        logger.info(f"Hybrid Relay: Finding '{target_description}'...")
        screenshot_bytes = page.screenshot()
        img = Image.open(io.BytesIO(screenshot_bytes))
        w, h = img.size

        vp_w = page.viewport_size["width"]
        dpr = self.compute_dpr(w, vp_w)
        if dpr > 1.01:
            logger.info(f"DPR detected: {dpr:.2f} (screenshot={w}x{h}, viewport={vp_w})")

        # PHASE 1: VLM Discovery
        vlm_coords = self.vision.detect_ui_element(screenshot_bytes, target_description)
        if not vlm_coords:
            logger.warning(f"VLM failed to discover '{target_description}'")
            return None

        x1, y1, x2, y2 = vlm_coords

        px_x1 = (x1 / 1000.0) * w
        px_y1 = (y1 / 1000.0) * h
        px_x2 = (x2 / 1000.0) * w
        px_y2 = (y2 / 1000.0) * h

        pad_x = 30
        pad_y_top = 30
        pad_y_bottom = 80
        crop_box = (
            max(0, px_x1 - pad_x),
            max(0, px_y1 - pad_y_top),
            min(w, px_x2 + pad_x),
            min(h, px_y2 + pad_y_bottom),
        )

        logger.info(f"Discovery Success. Cropping area: {crop_box}")
        cropped_img = img.crop(crop_box)

        if self.vision.debug:
            debug_crop_path = f"debug_hybrid_crop_{int(time.time())}.png"
            cropped_img.save(debug_crop_path)

        crop_bytes_io = io.BytesIO()
        cropped_img.save(crop_bytes_io, format="PNG")
        crop_bytes = crop_bytes_io.getvalue()

        # PHASE 2: OCR Refinement
        logger.info("PHASE 2: OCR Refinement on crop...")
        ocr_results = self.ocr.reader.readtext(crop_bytes)

        # Use caller-provided keywords if given, otherwise derive from description
        if keywords:
            target_keywords = [k.lower() for k in keywords]
        else:
            target_keywords = [
                kw
                for kw in target_description.lower().split()
                if len(kw) > 3 and kw not in ["game", "icon", "app", "banner"]
            ]

        best_match = None

        for bbox, text, prob in ocr_results:
            text_lower = text.lower()
            if any(kw in text_lower for kw in target_keywords):
                best_match = (bbox, text, prob)
                break

        if best_match:
            bbox, text, prob = best_match
            logger.info(f"OCR Refined Success! Text: '{text}' (prob: {prob:.2f})")

            c_tl, c_br = bbox[0], bbox[2]
            c_cx = (c_tl[0] + c_br[0]) / 2
            c_cy = (c_tl[1] + c_br[1]) / 2

            global_cx = crop_box[0] + c_cx
            global_cy = crop_box[1] + c_cy

            vp_x, vp_y = self.to_viewport(global_cx, global_cy, dpr)
            logger.info(
                f"Refined Coordinate: ({global_cx:.1f}, {global_cy:.1f}) -> "
                f"viewport ({vp_x:.1f}, {vp_y:.1f}) [DPR={dpr:.2f}]"
            )
            return (float(vp_x), float(vp_y))

        # FALLBACK: OCR fails, trust VLM center
        logger.warning(
            f"OCR failed to verify keywords for '{target_description}'. Falling back to VLM Center.",
        )
        vlm_cx = (px_x1 + px_x2) / 2
        vlm_cy = (px_y1 + px_y2) / 2
        vp_x, vp_y = self.to_viewport(vlm_cx, vlm_cy, dpr)
        return (float(vp_x), float(vp_y))

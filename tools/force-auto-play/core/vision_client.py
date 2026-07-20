import io
import logging

import ollama
from PIL import Image

# Configure logger
logger = logging.getLogger(__name__)


class VisionClient:
    """Client for interacting with Vision Model (Moondream) via Ollama."""

    def __init__(self, model_name="moondream", debug=False):
        self.model_name = model_name
        self.client = ollama.Client()
        self.debug = debug

    def detect_ui_element(self, image_bytes: bytes, element_description: str) -> list:
        """Detect UI element using direct image aspect ratio (standard Ollama behavior)."""
        # 1. No padding (Ollama handles it better internally for Moondream)
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # 2. Descriptive Prompt
        is_text = "'" in element_description or '"' in element_description
        spatial_hint = ""
        if "sidebar" in element_description.lower() or "left" in element_description.lower():
            spatial_hint = " Focus only on the purple vertical area on the LEFT edge."
        elif "center" in element_description.lower() or "modal" in element_description.lower():
            spatial_hint = " Focus only on the white rectangular area in the CENTER."

        text_instruction = " Focus specifically on the text characters." if is_text else ""

        prompt = (
            f"Locate the '{element_description}' in the image.{spatial_hint}{text_instruction} "
            "Return exactly one JSON array [ymin, xmin, ymax, xmax] using 0-1000 scale. "
            "Coordinate (0,0) is top-left, (1000,1000) is bottom-right. "
            "IMPORTANT: Return ONLY the JSON array, no other text."
        )

        messages = [{"role": "user", "content": prompt, "images": [image_bytes]}]

        try:
            logger.debug("Vision request: %s", element_description)
            response = self.client.generate(
                model=self.model_name,
                prompt=prompt,
                images=[image_bytes],
                stream=False,
            )
            content = response["response"].strip()
            logger.debug("Vision response: %s", content)

            # 检查是否明确表示找不到
            negative_phrases = [
                "not found",
                "cannot find",
                "can't find",
                "unable to locate",
                "not visible",
                "no such",
                "doesn't exist",
                "not present",
            ]
            if any(phrase in content.lower() for phrase in negative_phrases):
                logger.warning(f"Model explicitly stated element not found: {content}")
                return []

            import re

            nums = re.findall(r"[-+]?\d*\.\d+|\d+", content)

            if len(nums) >= 4:
                coords = [float(n) for n in nums[:4]]
                # Moondream standard: [ymin, xmin, ymax, xmax]
                ymin_raw, xmin_raw, ymax_raw, xmax_raw = coords

                # Detect scale (0-1 or 0-1000)
                max_raw = max(coords)
                s_factor = 1000.0 if max_raw > 1.1 else 1.0

                # Map back to 0-1000 standard (relative to input image w, h)
                x_start = min(xmin_raw, xmax_raw) / s_factor * 1000.0
                x_end = max(xmin_raw, xmax_raw) / s_factor * 1000.0
                y_start = min(ymin_raw, ymax_raw) / s_factor * 1000.0
                y_end = max(ymin_raw, ymax_raw) / s_factor * 1000.0

                # RETURN [xmin, ymin, xmax, ymax] for consistency
                return [x_start, y_start, x_end, y_end]

            return []
        except Exception as e:
            logger.error(f"Vision Detect Error: {e}")
            return []

    def detect_in_crop(
        self,
        image_bytes: bytes,
        region_coords: list,
        target_description: str,
    ) -> list:
        """Crop the image to the specified region and detect the target element within it."""
        import time

        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # Detect scale of region_coords
        max_val = max(region_coords[2], region_coords[3])  # xmax, ymax
        scale = 1000.0 if max_val > 1.1 else 1.0

        # xmin, ymin, xmax, ymax
        x1 = (region_coords[0] / scale) * w
        y1 = (region_coords[1] / scale) * h
        x2 = (region_coords[2] / scale) * w
        y2 = (region_coords[3] / scale) * h

        px_xmin, px_xmax = min(x1, x2), max(x1, x2)
        px_ymin, px_ymax = min(y1, y2), max(y1, y2)

        # Crop (with slight padding)
        pad = 20
        crop_box = (
            max(0, px_xmin - pad),
            max(0, px_ymin - pad),
            min(w, px_xmax + pad),
            min(h, px_ymax + pad),
        )
        cropped_img = img.crop(crop_box)

        crop_bytes_io = io.BytesIO()
        cropped_img.save(crop_bytes_io, format="PNG")
        crop_bytes = crop_bytes_io.getvalue()

        # Save crop for debugging
        import os

        crop_debug_path = os.path.abspath(f"debug_crop_{int(time.time())}.png")
        cropped_img.save(crop_debug_path)
        logger.info(f"Saved debug crop to: {crop_debug_path}")

        # Detect in Crop
        logger.info(f"Localized Search: Detecting '{target_description}' within crop...")
        crop_coords = self.detect_ui_element(crop_bytes, target_description)

        if not crop_coords:
            return []

        # Map back to original scale
        # crop_coords is [xmin, ymin, xmax, ymax] in 1000-scale relative to crop
        c_xmin, c_ymin, c_xmax, c_ymax = crop_coords

        crop_w = crop_box[2] - crop_box[0]
        crop_h = crop_box[3] - crop_box[1]

        mapped_xmin = crop_box[0] + (c_xmin / 1000.0) * crop_w
        mapped_ymin = crop_box[1] + (c_ymin / 1000.0) * crop_h
        mapped_xmax = crop_box[0] + (c_xmax / 1000.0) * crop_w
        mapped_ymax = crop_box[1] + (c_ymax / 1000.0) * crop_h

        return [
            (mapped_xmin / w) * 1000,
            (mapped_ymin / h) * 1000,
            (mapped_xmax / w) * 1000,
            (mapped_ymax / h) * 1000,
        ]

    def detect_in_layout_region(
        self,
        image_bytes: bytes,
        target_description: str,
        region: str,
    ) -> list:
        """Split screen into fixed regions (left, center, right) and detect within that segment."""
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        if region == "left":
            # Left 30%
            crop_box = (0, 0, int(w * 0.3), h)
        elif region == "center":
            # Center 60% (Modal focus)
            crop_box = (int(w * 0.2), 0, int(w * 0.8), h)
        elif region == "strict-center":
            # Narrow vertical pipe in the absolute middle
            crop_box = (int(w * 0.45), 0, int(w * 0.55), h)
        elif region == "checkbox-pipe":
            # Extremely narrow vertical pipe for dead-center checkbox hits
            # 缩小Y范围，只看底部区域
            crop_box = (int(w * 0.245), int(h * 0.7), int(w * 0.275), int(h * 0.85))
        elif region == "agreement-text":
            # 只看checkbox右边的文字区域
            crop_box = (int(w * 0.28), int(h * 0.73), int(w * 0.65), int(h * 0.83))
        elif region == "bottom-agreement-row":
            # Narrow horizontal slice for the final checkbox row
            crop_box = (0, int(h * 0.73), w, int(h * 0.83))
        elif region == "agree-button-only":
            # 只包含"I Agree All"按钮的区域，排除Exit
            crop_box = (int(w * 0.30), int(h * 0.70), int(w * 0.70), int(h * 0.85))
        elif region == "bottom-center":
            # Bottom part of center modal
            crop_box = (int(w * 0.25), int(h * 0.6), int(w * 0.75), h)
        elif region == "precise-center":
            # A more precise center region, e.g., for a modal
            crop_box = (int(w * 0.25), int(h * 0.15), int(w * 0.75), int(h * 0.85))
        elif region == "precise-left-modal":
            # A more precise left modal region, e.g., for checkboxes in a modal
            crop_box = (int(w * 0.25), int(h * 0.15), int(w * 0.5), int(h * 0.85))
        elif region == "right":
            # Right 30%
            crop_box = (int(w * 0.7), 0, w, h)
        else:
            return []

        cropped_img = img.crop(crop_box)
        crop_bytes_io = io.BytesIO()
        cropped_img.save(crop_bytes_io, format="PNG")
        crop_bytes = crop_bytes_io.getvalue()

        # Save debug crop
        import os
        import time

        debug_path = os.path.abspath(f"debug_layout_{region}_{int(time.time())}.png")
        cropped_img.save(debug_path)
        logger.info(f"Prescan: Layout crop saved to: {debug_path}")

        # Detect in Crop
        crop_coords = self.detect_ui_element(crop_bytes, target_description)

        if not crop_coords:
            return []

        # Map back to full scale
        c_xmin, c_ymin, c_xmax, c_ymax = crop_coords

        crop_w = crop_box[2] - crop_box[0]
        crop_h = crop_box[3] - crop_box[1]

        mapped_xmin = crop_box[0] + (c_xmin / 1000.0) * crop_w
        mapped_ymin = crop_box[1] + (c_ymin / 1000.0) * crop_h
        mapped_xmax = crop_box[0] + (c_xmax / 1000.0) * crop_w
        mapped_ymax = crop_box[1] + (c_ymax / 1000.0) * crop_h

        return [
            (mapped_xmin / w) * 1000,
            (mapped_ymin / h) * 1000,
            (mapped_xmax / w) * 1000,
            (mapped_ymax / h) * 1000,
        ]

    def detect_in_grid_region(
        self,
        image_bytes: bytes,
        target_description: str,
        x_start: float = 0.0,
        x_end: float = 1.0,
        y_start: float = 0.0,
        y_end: float = 1.0,
    ) -> list:
        """使用比例坐标裁剪任意区域进行检测

        Args:
            image_bytes: 图片字节
            target_description: 要检测的元素描述
            x_start: X轴起始比例 (0.0-1.0)
            x_end: X轴结束比例 (0.0-1.0)
            y_start: Y轴起始比例 (0.0-1.0)
            y_end: Y轴结束比例 (0.0-1.0)

        Returns:
            [xmin, ymin, xmax, ymax] 在原图0-1000坐标系中的位置

        Example:
            # 检测右上角 (右侧30%, 顶部15%)
            detect_in_grid_region(img, "Login button", 0.7, 1.0, 0.0, 0.15)

        """
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # 计算裁剪区域
        crop_box = (
            int(w * x_start),
            int(h * y_start),
            int(w * x_end),
            int(h * y_end),
        )

        cropped_img = img.crop(crop_box)
        crop_bytes_io = io.BytesIO()
        cropped_img.save(crop_bytes_io, format="PNG")
        crop_bytes = crop_bytes_io.getvalue()

        # Save debug crop
        import os
        import time

        region_name = f"grid_{x_start:.2f}-{x_end:.2f}_{y_start:.2f}-{y_end:.2f}"
        debug_path = os.path.abspath(f"debug_{region_name}_{int(time.time())}.png")
        cropped_img.save(debug_path)
        logger.info(
            f"Grid crop [{x_start:.2f}-{x_end:.2f}, {y_start:.2f}-{y_end:.2f}] saved to: {debug_path}",
        )

        # Detect in Crop
        crop_coords = self.detect_ui_element(crop_bytes, target_description)

        if not crop_coords:
            return []

        # Map back to full scale
        c_xmin, c_ymin, c_xmax, c_ymax = crop_coords

        crop_w = crop_box[2] - crop_box[0]
        crop_h = crop_box[3] - crop_box[1]

        mapped_xmin = crop_box[0] + (c_xmin / 1000.0) * crop_w
        mapped_ymin = crop_box[1] + (c_ymin / 1000.0) * crop_h
        mapped_xmax = crop_box[0] + (c_xmax / 1000.0) * crop_w
        mapped_ymax = crop_box[1] + (c_ymax / 1000.0) * crop_h

        return [
            (mapped_xmin / w) * 1000,
            (mapped_ymin / h) * 1000,
            (mapped_xmax / w) * 1000,
            (mapped_ymax / h) * 1000,
        ]
        cropped_img.save(debug_path)
        logger.info(f"Prescan: Layout crop saved to: {debug_path}")

        # Detect in Crop
        crop_coords = self.detect_ui_element(crop_bytes, target_description)

        if not crop_coords:
            return []

        # Map back to full scale
        c_xmin, c_ymin, c_xmax, c_ymax = crop_coords

        crop_w = crop_box[2] - crop_box[0]
        crop_h = crop_box[3] - crop_box[1]

        mapped_xmin = crop_box[0] + (c_xmin / 1000.0) * crop_w
        mapped_ymin = crop_box[1] + (c_ymin / 1000.0) * crop_h
        mapped_xmax = crop_box[0] + (c_xmax / 1000.0) * crop_w
        mapped_ymax = crop_box[1] + (c_ymax / 1000.0) * crop_h

        return [
            (mapped_xmin / w) * 1000,
            (mapped_ymin / h) * 1000,
            (mapped_xmax / w) * 1000,
            (mapped_ymax / h) * 1000,
        ]

    def detect_with_anchor_zoom(
        self,
        image_bytes: bytes,
        target_desc: str,
        anchor_desc: str,
        layout_region: str = "full",
        zoom_config: dict = None,
    ) -> list:
        """Locate anchor -> precision crop -> Find target.
        zoom_config can contain: zoom_w, zoom_h, x_offset, y_offset
        """
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size

        # Default config for resolution-independent targeting
        # rel_x_offset/rel_y_offset are fractions of image w/h
        config = {
            "zoom_w_rel": 0.2,  # 20% of width
            "zoom_h_rel": 0.15,  # 15% of height
            "rel_x_offset": 0.0,
            "rel_y_offset": 0.0,
        }
        if zoom_config:
            config.update(zoom_config)

        # 1. Detect anchor
        logger.info(f"Anchor Zoom Stage 1: Finding anchor '{anchor_desc}'...")
        anchor_coords = self.detect_in_layout_region(image_bytes, anchor_desc, layout_region)

        if not anchor_coords or len(anchor_coords) < 4:
            logger.warning("Anchor not found or invalid format. Fallback.")
            return self.detect_in_layout_region(image_bytes, target_desc, layout_region)

        # 2. Map Anchor to GLOBAL coordinates
        # IMPORTANT: detect_in_layout_region returns coordinates relative to the CROP if a region is used.
        # But wait, VisionClient.detect_ui_element (called by detect_in_layout_region)
        # ALREADY maps 0-1000 to the crop's portion of the FULL image.
        # So coords[1] (ymin) on 0-1000 scale refers to the FULL image's height.

        y1, x1, y2, x2 = anchor_coords

        # Center of anchor in GLOBAL pixel space
        acx_px = ((x1 + x2) / 2 / 1000.0) * w
        acy_px = ((y1 + y2) / 2 / 1000.0) * h

        target_center_x = acx_px + config["rel_x_offset"] * w
        target_center_y = acy_px + config["rel_y_offset"] * h

        zoom_w = int(config["zoom_w_rel"] * w)
        zoom_h = int(config["zoom_h_rel"] * h)

        # 3. Surgical Center
        cx1 = int(target_center_x - zoom_w // 2)
        cy1 = int(target_center_y - zoom_h // 2)
        cx2 = int(cx1 + zoom_w)
        cy2 = int(cy1 + zoom_h)

        # Clamp to image boundaries
        cx1 = max(0, min(w - 10, cx1))
        cy1 = max(0, min(h - 10, cy1))
        cx2 = max(cx1 + 10, min(w, cx2))
        cy2 = max(cy1 + 10, min(h, cy2))

        crop_box = (cx1, cy1, cx2, cy2)
        logger.info(f"Surgical Crop Box (L,T,R,B): {crop_box}")

        cropped_img = img.crop(crop_box)
        crop_bytes_io = io.BytesIO()
        cropped_img.save(crop_bytes_io, format="PNG")
        crop_bytes = crop_bytes_io.getvalue()

        if self.debug:
            import os
            import time

            debug_path = os.path.abspath(f"debug_zoom_{int(time.time())}.png")
            cropped_img.save(debug_path)
            logger.info(f"Zoom Crop saved to: {debug_path}")

        # 3. Detect target in precision crop
        logger.info(f"Anchor Zoom Stage 2: Detecting target '{target_desc}' in precision crop...")
        crop_coords = self.detect_ui_element(crop_bytes, target_desc)

        if crop_coords:
            xmin_c, ymin_c, xmax_c, ymax_c = crop_coords

            crop_w, crop_h = cx2 - cx1, cy2 - cy1
            mapped_xmin = cx1 + (xmin_c / 1000.0) * crop_w
            mapped_ymin = cy1 + (ymin_c / 1000.0) * crop_h
            mapped_xmax = cx1 + (xmax_c / 1000.0) * crop_w
            mapped_ymax = cy1 + (ymax_c / 1000.0) * crop_h

            return [
                (mapped_xmin / w) * 1000,
                (mapped_ymin / h) * 1000,
                (mapped_xmax / w) * 1000,
                (mapped_ymax / h) * 1000,
            ]
        logger.info("Vision failed to pinpoint. Using crop center as stable fallback.")
        # Center of the crop mapped to full scale
        mid_x = (cx1 + cx2) / 2
        mid_y = (cy1 + cy2) / 2
        # Return as a tiny box around the center
        return [
            ((mid_x - 5) / w) * 1000,
            ((mid_y - 5) / h) * 1000,
            ((mid_x + 5) / w) * 1000,
            ((mid_y + 5) / h) * 1000,
        ]

    def detect_with_grid_search(
        self,
        image_bytes: bytes,
        target_description: str,
        x_start: float = 0.0,
        x_end: float = 1.0,
        y_start: float = 0.0,
        y_end: float = 1.0,
        max_box_ratio: float = 0.7,
        search_directions: list = None,
        step_ratio: float = 0.5,
    ) -> list:
        """带网格搜索的元素检测，失败时自动尝试相邻区域

        Args:
            image_bytes: 图片字节
            target_description: 要检测的元素描述
            x_start, x_end, y_start, y_end: 初始搜索区域
            max_box_ratio: 边界框占裁剪区域的最大比例，超过则认为不准确
            search_directions: 搜索方向列表 ['up', 'down', 'left', 'right']
                              默认None时根据初始位置自动判断
            step_ratio: 移动步长，相对于当前区域大小的比例

        Returns:
            [xmin, ymin, xmax, ymax] 在原图0-1000坐标系中的位置

        Example:
            # 从右上角开始搜索Login按钮，失败时向下和向左尝试
            detect_with_grid_search(img, "Login", 0.7, 1.0, 0.0, 0.15,
                                   search_directions=['down', 'left'])

        """
        # 第一次尝试：在指定区域检测
        coords = self.detect_in_grid_region(
            image_bytes,
            target_description,
            x_start,
            x_end,
            y_start,
            y_end,
        )

        if coords:
            # 检查边界框是否太大
            c_xmin, c_ymin, c_xmax, c_ymax = coords
            box_width = (c_xmax - c_xmin) / 1000.0
            box_height = (c_ymax - c_ymin) / 1000.0
            region_width = x_end - x_start
            region_height = y_end - y_start

            width_ratio = box_width / region_width if region_width > 0 else 1
            height_ratio = box_height / region_height if region_height > 0 else 1

            # 计算绝对像素尺寸（假设标准分辨率）
            # 这里用1280x800作为参考
            abs_width_px = box_width * 1280
            abs_height_px = box_height * 800

            # 按钮/文本通常不超过200px宽，80px高
            max_reasonable_width = 250
            max_reasonable_height = 100

            # 如果边界框不太大，认为检测成功
            is_ratio_ok = width_ratio < max_box_ratio and height_ratio < max_box_ratio
            is_size_reasonable = (
                abs_width_px < max_reasonable_width and abs_height_px < max_reasonable_height
            )

            if is_ratio_ok and is_size_reasonable:
                logger.info(
                    f"✓ 检测成功，边界框占比: W={width_ratio:.1%}, H={height_ratio:.1%}, 尺寸: {abs_width_px:.0f}x{abs_height_px:.0f}px",
                )
                return coords
            if not is_ratio_ok:
                logger.warning(
                    f"⚠️  边界框占比太大: W={width_ratio:.1%}, H={height_ratio:.1%}，尝试相邻区域",
                )
            elif not is_size_reasonable:
                logger.warning(
                    f"⚠️  边界框绝对尺寸太大: {abs_width_px:.0f}x{abs_height_px:.0f}px（限制{max_reasonable_width}x{max_reasonable_height}px），尝试相邻区域",
                )
        else:
            logger.warning("⚠️  未检测到元素，尝试相邻区域")

        # 自动判断搜索方向
        if search_directions is None:
            search_directions = []
            # 根据初始位置判断可以搜索的方向
            if y_start > 0.1:  # 不在顶部，可以向上
                search_directions.append("up")
            if y_end < 0.9:  # 不在底部，可以向下
                search_directions.append("down")
            if x_start > 0.1:  # 不在左侧，可以向左
                search_directions.append("left")
            if x_end < 0.9:  # 不在右侧，可以向右
                search_directions.append("right")

        # 计算当前区域大小
        region_w = x_end - x_start
        region_h = y_end - y_start

        # 尝试相邻区域
        for direction in search_directions:
            new_x_start, new_x_end = x_start, x_end
            new_y_start, new_y_end = y_start, y_end

            if direction == "up":
                shift = region_h * step_ratio
                new_y_start = max(0.0, y_start - shift)
                new_y_end = max(0.0, y_end - shift)
                logger.info(f"🔍 尝试向上移动到 Y:[{new_y_start:.2f}-{new_y_end:.2f}]")
            elif direction == "down":
                shift = region_h * step_ratio
                new_y_start = min(1.0, y_start + shift)
                new_y_end = min(1.0, y_end + shift)
                logger.info(f"🔍 尝试向下移动到 Y:[{new_y_start:.2f}-{new_y_end:.2f}]")
            elif direction == "left":
                shift = region_w * step_ratio
                new_x_start = max(0.0, x_start - shift)
                new_x_end = max(0.0, x_end - shift)
                logger.info(f"🔍 尝试向左移动到 X:[{new_x_start:.2f}-{new_x_end:.2f}]")
            elif direction == "right":
                shift = region_w * step_ratio
                new_x_start = min(1.0, x_start + shift)
                new_x_end = min(1.0, x_end + shift)
                logger.info(f"🔍 尝试向右移动到 X:[{new_x_start:.2f}-{new_x_end:.2f}]")

            # 递归检测（但不再继续搜索，避免无限递归）
            coords = self.detect_in_grid_region(
                image_bytes,
                target_description,
                new_x_start,
                new_x_end,
                new_y_start,
                new_y_end,
            )

            if coords:
                c_xmin, c_ymin, c_xmax, c_ymax = coords
                box_width = (c_xmax - c_xmin) / 1000.0
                box_height = (c_ymax - c_ymin) / 1000.0
                new_region_width = new_x_end - new_x_start
                new_region_height = new_y_end - new_y_start

                width_ratio = box_width / new_region_width if new_region_width > 0 else 1
                height_ratio = box_height / new_region_height if new_region_height > 0 else 1

                # 同样检查绝对尺寸
                abs_width_px = box_width * 1280
                abs_height_px = box_height * 800
                max_reasonable_width = 250
                max_reasonable_height = 100

                is_ratio_ok = width_ratio < max_box_ratio and height_ratio < max_box_ratio
                is_size_reasonable = (
                    abs_width_px < max_reasonable_width and abs_height_px < max_reasonable_height
                )

                if is_ratio_ok and is_size_reasonable:
                    logger.info(
                        f"✓ 在{direction}方向找到，边界框占比: W={width_ratio:.1%}, H={height_ratio:.1%}, 尺寸: {abs_width_px:.0f}x{abs_height_px:.0f}px",
                    )
                    return coords

        # 所有方向都失败，返回空
        logger.warning("❌ 所有搜索方向均未找到合适的元素")
        return []

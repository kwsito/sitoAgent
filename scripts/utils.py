import base64
import os
import logging

# 设置Kivy日志系统
try:
    from kivy.logger import Logger
    KIVY_LOGGER_AVAILABLE = True
except ImportError:
    KIVY_LOGGER_AVAILABLE = False
    logging.basicConfig(level=logging.INFO)
    standard_logger = logging.getLogger('AppAgent')

try:
    from colorama import Fore, Style
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False


def print_with_color(text: str, color=""):
    # 优先使用Kivy Logger
    if KIVY_LOGGER_AVAILABLE:
        # 根据颜色设置日志级别
        if color == "red" or "ERROR" in text:
            Logger.error(text)
        elif color == "green":
            Logger.info(text)
        elif color == "yellow":
            Logger.info(text)
        elif color == "blue":
            Logger.info(text)
        elif color == "magenta":
            Logger.info(text)
        elif color == "cyan":
            Logger.info(text)
        else:
            Logger.info(text)
        return
    
    # 如果Kivy Logger不可用，使用标准logging
    if not KIVY_LOGGER_AVAILABLE:
        if color == "red" or "ERROR" in text:
            standard_logger.error(text)
        elif color == "green":
            standard_logger.info(text)
        elif color == "yellow":
            standard_logger.info(text)
        else:
            standard_logger.info(text)
        return
    
    # 如果colorama可用，使用colorama（仅限桌面环境）
    if COLORAMA_AVAILABLE:
        if color == "red":
            print(Fore.RED + text)
        elif color == "green":
            print(Fore.GREEN + text)
        elif color == "yellow":
            print(Fore.YELLOW + text)
        elif color == "blue":
            print(Fore.BLUE + text)
        elif color == "magenta":
            print(Fore.MAGENTA + text)
        elif color == "cyan":
            print(Fore.CYAN + text)
        elif color == "white":
            print(Fore.WHITE + text)
        elif color == "black":
            print(Fore.BLACK + text)
        else:
            print(text)
        print(Style.RESET_ALL)
    else:
        print(text)


def draw_bbox_multi(img_path, output_path, elem_list, record_mode=False, dark_mode=False):
    if not os.path.exists(img_path):
        print_with_color(f"ERROR: Input image does not exist: {img_path}", "red")
        return None

    try:
        import cv2
        import pyshine as ps
        imgcv = cv2.imread(img_path)
        if imgcv is None:
            print_with_color(f"ERROR: Failed to load image from {img_path}", "red")
            return None

        count = 1
        for elem in elem_list:
            try:
                top_left = elem.bbox[0]
                bottom_right = elem.bbox[1]
                left, top = int(top_left[0]), int(top_left[1])
                right, bottom = int(bottom_right[0]), int(bottom_right[1])
                label = str(count)

                if record_mode:
                    if getattr(elem, "attrib", None) == "clickable":
                        color = (250, 0, 0)
                    elif getattr(elem, "attrib", None) == "focusable":
                        color = (0, 0, 250)
                    else:
                        color = (0, 250, 0)
                    imgcv = ps.putBText(
                        imgcv,
                        label,
                        text_offset_x=(left + right) // 2 + 10,
                        text_offset_y=(top + bottom) // 2 + 10,
                        vspace=10,
                        hspace=10,
                        font_scale=1,
                        thickness=2,
                        background_RGB=color,
                        text_RGB=(255, 250, 250),
                        alpha=0.5,
                    )
                else:
                    text_color = (10, 10, 10) if dark_mode else (255, 250, 250)
                    bg_color = (255, 250, 250) if dark_mode else (10, 10, 10)
                    imgcv = ps.putBText(
                        imgcv,
                        label,
                        text_offset_x=(left + right) // 2 + 10,
                        text_offset_y=(top + bottom) // 2 + 10,
                        vspace=10,
                        hspace=10,
                        font_scale=1,
                        thickness=2,
                        background_RGB=bg_color,
                        text_RGB=text_color,
                        alpha=0.5,
                    )
            except Exception as e:
                print_with_color(f"ERROR: An exception occurs while labeling element {count}: {e}", "red")
            count += 1

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        result = cv2.imwrite(output_path, imgcv)
        if result and os.path.exists(output_path):
            return imgcv

        print_with_color(f"ERROR: Failed to save labeled image to {output_path}", "red")
        return None
    except Exception as e:
        print_with_color(f"WARN: OpenCV labeling unavailable, fallback to PIL: {e}", "yellow")

    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.open(img_path).convert("RGB")
        width, height = img.size
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()

        def _clamp(v, lo, hi):
            return lo if v < lo else hi if v > hi else v

        def _attrib_color(attrib):
            if record_mode:
                if attrib == "clickable":
                    return (250, 0, 0)
                if attrib == "focusable":
                    return (0, 0, 250)
                return (0, 250, 0)
            if dark_mode:
                return (255, 250, 250)
            return (10, 10, 10)

        count = 1
        for elem in elem_list:
            try:
                top_left = elem.bbox[0]
                bottom_right = elem.bbox[1]
                left, top = int(top_left[0]), int(top_left[1])
                right, bottom = int(bottom_right[0]), int(bottom_right[1])

                left = _clamp(left, 0, max(0, width - 1))
                right = _clamp(right, 0, max(0, width - 1))
                top = _clamp(top, 0, max(0, height - 1))
                bottom = _clamp(bottom, 0, max(0, height - 1))
                if right < left:
                    left, right = right, left
                if bottom < top:
                    top, bottom = bottom, top

                outline = _attrib_color(getattr(elem, "attrib", None))
                thick = 3
                for t in range(thick):
                    l2 = left + t
                    t2 = top + t
                    r2 = right - t
                    b2 = bottom - t
                    if r2 <= l2 or b2 <= t2:
                        break
                    draw.rectangle([l2, t2, r2, b2], outline=outline)

                label = str(count)
                cx = _clamp((left + right) // 2, 0, max(0, width - 1))
                cy = _clamp((top + bottom) // 2, 0, max(0, height - 1))

                try:
                    _bbox = draw.textbbox((0, 0), label, font=font)
                    tw = int(_bbox[2] - _bbox[0])
                    th = int(_bbox[3] - _bbox[1])
                except Exception:
                    tw, th = draw.textsize(label, font=font)
                pad = 4
                bg_left = _clamp(cx - (tw // 2) - pad, 0, max(0, width - 1))
                bg_top = _clamp(cy - (th // 2) - pad, 0, max(0, height - 1))
                bg_right = _clamp(cx + (tw // 2) + pad, 0, max(0, width - 1))
                bg_bottom = _clamp(cy + (th // 2) + pad, 0, max(0, height - 1))

                if dark_mode:
                    bg = (255, 250, 250)
                    fg = (10, 10, 10)
                else:
                    bg = (10, 10, 10)
                    fg = (255, 250, 250)

                draw.rectangle([bg_left, bg_top, bg_right, bg_bottom], fill=bg)
                draw.text((bg_left + pad, bg_top + pad), label, fill=fg, font=font)
            except Exception as e2:
                print_with_color(f"ERROR: PIL labeling element {count} failed: {e2}", "red")
            count += 1

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        img.save(output_path)
        if os.path.exists(output_path):
            return img

        print_with_color(f"ERROR: PIL save returned but file does not exist: {output_path}", "red")
        return None
    except Exception as e:
        print_with_color(f"ERROR: Failed to label image: {e}", "red")
        import traceback
        print_with_color(f"Traceback:\n{traceback.format_exc()}", "red")
        return None


def draw_grid(img_path, output_path):
    def get_unit_len(n):
        for i in range(1, n + 1):
            if n % i == 0 and 120 <= i <= 180:
                return i
        return -1

    if not os.path.exists(img_path):
        print_with_color(f"ERROR: Input image does not exist: {img_path}", "red")
        return -1, -1

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(img_path).convert("RGB")
        width, height = img.size
        
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()

        color = (255, 116, 113)
        unit_height = get_unit_len(height)
        if unit_height < 0:
            unit_height = 120
        unit_width = get_unit_len(width)
        if unit_width < 0:
            unit_width = 120
        thick = max(1, int(unit_width // 50))
        rows = height // unit_height
        cols = width // unit_width

        for i in range(rows):
            for j in range(cols):
                label = i * cols + j + 1
                left = int(j * unit_width)
                top = int(i * unit_height)
                right = int((j + 1) * unit_width)
                bottom = int((i + 1) * unit_height)
                for t in range(thick // 2 + 1):
                    draw.rectangle([left + t, top + t, right - t, bottom - t], outline=color)
                tx = left + int(unit_width * 0.05)
                ty = top + int(unit_height * 0.3)
                draw.text((tx + 2, ty + 2), str(label), fill=(0, 0, 0), font=font)
                draw.text((tx, ty), str(label), fill=color, font=font)

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        img.save(output_path)
        return rows, cols
    except Exception as e:
        print_with_color(f"WARN: PIL failed, trying cv2: {e}", "yellow")
        
        import cv2
        image = cv2.imread(img_path)
        if image is None:
            print_with_color(f"ERROR: Failed to load image from {img_path}", "red")
            return -1, -1
        
        height, width, _ = image.shape
        
        color = (255, 116, 113)
        unit_height = get_unit_len(height)
        if unit_height < 0:
            unit_height = 120
        unit_width = get_unit_len(width)
        if unit_width < 0:
            unit_width = 120
        thick = int(unit_width // 50)
        rows = height // unit_height
        cols = width // unit_width
        
        for i in range(rows):
            for j in range(cols):
                label = i * cols + j + 1
                left = int(j * unit_width)
                top = int(i * unit_height)
                right = int((j + 1) * unit_width)
                bottom = int((i + 1) * unit_height)
                cv2.rectangle(image, (left, top), (right, bottom), color, thick // 2)
                cv2.putText(image, str(label), (left + int(unit_width * 0.05) + 3, top + int(unit_height * 0.3) + 3), 0,
                            int(0.01 * unit_width), (0, 0, 0), thick)
                cv2.putText(image, str(label), (left + int(unit_width * 0.05), top + int(unit_height * 0.3)), 0,
                            int(0.01 * unit_width), color, thick)
        
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        result = cv2.imwrite(output_path, image)
        if result:
            if not os.path.exists(output_path):
                print_with_color(f"ERROR: cv2.imwrite returned True but file does not exist: {output_path}", "red")
        else:
            print_with_color(f"ERROR: cv2.imwrite returned False", "red")
        
        return rows, cols


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

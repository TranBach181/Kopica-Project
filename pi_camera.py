#!/usr/bin/env python3
"""
pi_camera.py — Ứng dụng chụp ảnh tối giản cho Raspberry Pi Zero 2W
Hardware : Raspberry Pi HQ Camera (IMX477)
Display  : Màn hình 3.5" HDMI
Shutter  : Nút bấm tại GPIO 26 (pull-up nội bộ)
OS       : Raspberry Pi OS Bookworm
"""

import os
import time
from datetime import datetime

# --- Thư viện Camera & GPIO ---
try:
    from picamera2 import Picamera2, Preview
    from libcamera import controls, Transform
except ImportError as e:
    print(f"[LỖI] Không tìm thấy picamera2: {e}")
    print("       Chạy: sudo apt install -y python3-picamera2")
    raise SystemExit(1)

try:
    from gpiozero import Button
except ImportError as e:
    print(f"[LỖI] Không tìm thấy gpiozero: {e}")
    print("       Chạy: sudo apt install -y python3-gpiozero")
    raise SystemExit(1)

# ─────────────────────────────────────────────
# CẤU HÌNH
# ─────────────────────────────────────────────
GPIO_SHUTTER      = 26                        # GPIO BCM (chân vật lý 37)
PREVIEW_SIZE      = (800, 480)                # Phù hợp màn hình 3.5" HDMI
CAPTURE_SIZE      = (4056, 3040)             # Độ phân giải tối đa IMX477
SAVE_DIR          = "/boot/firmware/Photos"   # Thư mục lưu ảnh
DEBOUNCE_TIME_S   = 0.3                       # Chống rung nút bấm (giây)
COOLDOWN_S        = 5.0                       # Thời gian chờ giữa hai lần chụp (giây)


def ensure_save_dir(path: str) -> None:
    """Tạo thư mục lưu ảnh nếu chưa tồn tại."""
    os.makedirs(path, exist_ok=True)
    print(f"[INFO] Thư mục lưu ảnh: {path}")


def build_filename() -> str:
    """Tạo tên file dựa trên thời gian thực: IMG_YYYYMMDD_HHMMSS.jpg"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"IMG_{timestamp}.jpg"


def make_capture_callback(camera: Picamera2):
    """
    Trả về hàm callback được gọi khi nút bấm được nhấn.
    Dùng closure để truy cập `camera` và `last_capture_time`.
    """
    state = {"last_time": 0.0}

    def on_button_pressed():
        now = time.monotonic()

        # Chống rung: bỏ qua nhấn trong 0.3s đầu
        if now - state["last_time"] < DEBOUNCE_TIME_S:
            return

        # Cooldown 5s: khóa nút sau mỗi lần chụp thành công
        remaining = COOLDOWN_S - (now - state["last_time"])
        if state["last_time"] != 0.0 and remaining > 0:
            print(f"[CHỜ] Vui lòng chờ thêm {remaining:.1f}s trước khi chụp tiếp.")
            return

        state["last_time"] = now

        filepath = os.path.join(SAVE_DIR, build_filename())
        print(f"[CHỤP] Đang lưu → {filepath} ...", end=" ", flush=True)

        try:
            # Chụp ảnh ở độ phân giải tối đa, không làm gián đoạn preview
            camera.capture_file(filepath)
            print(f"✓ Thành công — chờ {COOLDOWN_S:.0f}s trước khi chụp tiếp.")
        except Exception as e:
            print(f"\n[LỖI] Không thể lưu ảnh: {e}")

    return on_button_pressed


def main():
    print("=" * 50)
    print("  Pi Camera — Khởi động")
    print("=" * 50)

    # 1. Chuẩn bị thư mục lưu ảnh
    try:
        ensure_save_dir(SAVE_DIR)
    except PermissionError:
        print(f"[LỖI] Không có quyền ghi vào {SAVE_DIR}. Thử chạy với sudo.")
        raise SystemExit(1)

    # 2. Khởi tạo camera
    try:
        camera = Picamera2()

        # Cấu hình: stream chính (main) dùng để chụp, stream lores dùng preview
        # Transform(hflip+vflip) = xoay 180° → viewfinder hiển thị đúng chiều trên màn hình
        config = camera.create_preview_configuration(
            main={"size": CAPTURE_SIZE, "format": "RGB888"},
            lores={"size": PREVIEW_SIZE, "format": "YUV420"},
            display="lores",            # Preview lấy từ stream lores → nhẹ hơn
            transform=Transform(hflip=True, vflip=True),  # Lật 180°
        )
        camera.configure(config)

        # Bật autofocus liên tục nếu lens hỗ trợ (IMX477 fixed-focus thì bỏ qua)
        try:
            camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        except Exception:
            pass  # Lens fixed-focus → không cần autofocus

    except Exception as e:
        print(f"[LỖI] Không thể khởi tạo camera: {e}")
        raise SystemExit(1)

    # 3. Cấu hình nút bấm GPIO 26 với pull-up nội bộ
    shutter_btn = Button(GPIO_SHUTTER, pull_up=True, bounce_time=DEBOUNCE_TIME_S)

    # 4. Gắn callback chụp ảnh vào sự kiện nhấn nút
    shutter_btn.when_pressed = make_capture_callback(camera)

    # 5. Bật Preview trên Desktop (QT backend) rồi bắt đầu camera
    try:
        camera.start_preview(Preview.QT, x=0, y=0,
                             width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1])
        camera.start()
        print(f"[INFO] Viewfinder đang chạy tại {PREVIEW_SIZE[0]}×{PREVIEW_SIZE[1]}")
        print(f"[INFO] Nhấn nút GPIO {GPIO_SHUTTER} để chụp ảnh")
        print("[INFO] Nhấn Ctrl+C để thoát\n")

        # Vòng lặp chính — chỉ giữ chương trình sống, GPIO callback xử lý sự kiện
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n[INFO] Đang thoát...")
    except Exception as e:
        print(f"[LỖI] Lỗi runtime: {e}")
    finally:
        # Dọn dẹp tài nguyên
        camera.stop_preview()
        camera.stop()
        camera.close()
        print("[INFO] Camera đã đóng. Tạm biệt!")


if __name__ == "__main__":
    main()

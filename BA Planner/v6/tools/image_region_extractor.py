from __future__ import annotations

import argparse
import json
import re
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np
from PIL import Image, ImageTk

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import BASE_DIR


DEFAULT_OUTPUT_DIR = BASE_DIR / "debug" / "region_captures"
DEFAULT_PREFIX = "image_region"
PREVIEW_MAX_WIDTH = 1400
PREVIEW_MAX_HEIGHT = 900


def _sanitize_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned or fallback


def _next_output_paths(output_dir: Path, base_name: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 1000):
        suffix = f"_{idx:03d}"
        png_path = output_dir / f"{base_name}{suffix}.png"
        json_path = output_dir / f"{base_name}{suffix}.json"
        if not png_path.exists() and not json_path.exists():
            return png_path, json_path
    raise RuntimeError("too many extracted regions for the same base name")


def _payload_source_size(payload: dict) -> tuple[float, float] | None:
    source_size = payload.get("source_size")
    if isinstance(source_size, dict):
        width = float(source_size.get("width", 0) or 0)
        height = float(source_size.get("height", 0) or 0)
        if width > 0 and height > 0:
            return width, height
    window_rect = payload.get("window_rect")
    if isinstance(window_rect, dict):
        width = float(window_rect.get("width", 0) or 0)
        height = float(window_rect.get("height", 0) or 0)
        if width > 0 and height > 0:
            return width, height
    return None


def _quad_from_payload_for_image(payload: dict, image_size: tuple[int, int]) -> list[tuple[float, float]] | None:
    img_w, img_h = image_size
    points_ratio = payload.get("points_ratio")
    if isinstance(points_ratio, list) and len(points_ratio) >= 4:
        quad = []
        for point in points_ratio[:4]:
            quad.append((float(point.get("x", 0.0)) * img_w, float(point.get("y", 0.0)) * img_h))
        return quad

    points_client = payload.get("points_client")
    payload_size = _payload_source_size(payload)
    if isinstance(points_client, list) and len(points_client) >= 4 and payload_size is not None:
        src_w, src_h = payload_size
        scale_x = img_w / max(src_w, 1.0)
        scale_y = img_h / max(src_h, 1.0)
        quad = []
        for point in points_client[:4]:
            quad.append((float(point.get("x", 0.0)) * scale_x, float(point.get("y", 0.0)) * scale_y))
        return quad

    crop_box = payload.get("crop_box_image")
    if isinstance(crop_box, dict):
        src_size = payload_size or image_size
        src_w, src_h = src_size
        scale_x = img_w / max(src_w, 1.0)
        scale_y = img_h / max(src_h, 1.0)
        left = float(crop_box.get("left", 0.0)) * scale_x
        top = float(crop_box.get("top", 0.0)) * scale_y
        right = float(crop_box.get("right", 0.0)) * scale_x
        bottom = float(crop_box.get("bottom", 0.0)) * scale_y
        return [(left, top), (right, top), (right, bottom), (left, bottom)]

    preview_rect = payload.get("preview_rect")
    preview_scale = float(payload.get("preview_scale", 1.0) or 1.0)
    if isinstance(preview_rect, dict):
        left = float(preview_rect.get("left", 0.0)) / max(preview_scale, 1e-6)
        top = float(preview_rect.get("top", 0.0)) / max(preview_scale, 1e-6)
        right = float(preview_rect.get("right", 0.0)) / max(preview_scale, 1e-6)
        bottom = float(preview_rect.get("bottom", 0.0)) / max(preview_scale, 1e-6)
        scale_x = img_w / max(img_w, 1.0)
        scale_y = img_h / max(img_h, 1.0)
        return [
            (left * scale_x, top * scale_y),
            (right * scale_x, top * scale_y),
            (right * scale_x, bottom * scale_y),
            (left * scale_x, bottom * scale_y),
        ]
    return None


def _warp_quad_image(image: Image.Image, quad: list[tuple[float, float]]) -> Image.Image:
    top_left, top_right, bottom_right, bottom_left = quad
    top_width = ((top_right[0] - top_left[0]) ** 2 + (top_right[1] - top_left[1]) ** 2) ** 0.5
    bottom_width = ((bottom_right[0] - bottom_left[0]) ** 2 + (bottom_right[1] - bottom_left[1]) ** 2) ** 0.5
    left_height = ((bottom_left[0] - top_left[0]) ** 2 + (bottom_left[1] - top_left[1]) ** 2) ** 0.5
    right_height = ((bottom_right[0] - top_right[0]) ** 2 + (bottom_right[1] - top_right[1]) ** 2) ** 0.5
    dst_w = max(1, int(round(max(top_width, bottom_width))))
    dst_h = max(1, int(round(max(left_height, right_height))))

    src = np.array(quad, dtype=np.float32)
    dst = np.array(
        [(0.0, 0.0), (dst_w - 1.0, 0.0), (dst_w - 1.0, dst_h - 1.0), (0.0, dst_h - 1.0)],
        dtype=np.float32,
    )
    image_np = np.array(image.convert("RGBA"))
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image_np, matrix, (dst_w, dst_h))
    return Image.fromarray(warped)


class ImageRegionExtractor(tk.Tk):
    def __init__(self, *, initial_image: Path | None, output_dir: Path, prefix: str) -> None:
        super().__init__()
        self.title("Image Region Extractor")
        self.configure(bg="#152435")
        self.geometry("1480x980")

        self._output_dir = output_dir
        self._prefix_var = tk.StringVar(value=prefix)
        self._status_var = tk.StringVar(value="Open an image, drag a rectangle, then save.")

        self._source_path: Path | None = None
        self._source_image: Image.Image | None = None
        self._preview_image: Image.Image | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_scale = 1.0
        self._selection_canvas_id: int | None = None
        self._selection_preview: tuple[int, int, int, int] | None = None
        self._selection_quad_preview: list[tuple[float, float]] | None = None
        self._drag_start: tuple[int, int] | None = None
        self._region_path: Path | None = None

        self._build_ui()
        self._bind_events()

        if initial_image is not None:
            self._load_image(initial_image)

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg="#152435")
        top.pack(fill="x", padx=12, pady=12)

        tk.Button(top, text="Open Image", command=self._choose_image, width=14).pack(side="left")
        tk.Button(top, text="Load Region", command=self._choose_region, width=14).pack(side="left", padx=(8, 0))
        tk.Label(top, text="Name", bg="#152435", fg="#e8f4fd").pack(side="left", padx=(12, 6))
        tk.Entry(top, textvariable=self._prefix_var, width=28).pack(side="left")
        tk.Button(top, text="Reset Selection", command=self._reset_selection, width=16).pack(side="left", padx=(12, 0))
        tk.Button(top, text="Save Crop", command=self._save_crop, width=14).pack(side="left", padx=(12, 0))

        self._image_info = tk.Label(
            self,
            text="No image loaded",
            anchor="w",
            bg="#152435",
            fg="#7ab3d4",
        )
        self._image_info.pack(fill="x", padx=12)

        canvas_frame = tk.Frame(self, bg="#152435")
        canvas_frame.pack(fill="both", expand=True, padx=12, pady=12)

        self._canvas = tk.Canvas(canvas_frame, bg="#0d1b2a", highlightthickness=0, cursor="crosshair")
        self._canvas.pack(fill="both", expand=True)

        status = tk.Label(
            self,
            textvariable=self._status_var,
            anchor="w",
            justify="left",
            bg="#152435",
            fg="#e8f4fd",
        )
        status.pack(fill="x", padx=12, pady=(0, 12))

    def _bind_events(self) -> None:
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Control-o>", lambda _e: self._choose_image())
        self.bind("<Control-r>", lambda _e: self._choose_region())
        self.bind("<Control-s>", lambda _e: self._save_crop())
        self.bind("<Escape>", lambda _e: self._reset_selection())

    def _choose_image(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose image",
            filetypes=[
                ("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        self._load_image(Path(selected))

    def _choose_region(self) -> None:
        if self._source_image is None:
            messagebox.showinfo("Image Region Extractor", "Open an image first.")
            return
        selected = filedialog.askopenfilename(
            title="Choose region metadata",
            filetypes=[
                ("JSON", "*.json"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        self._load_region(Path(selected))

    def _load_region(self, path: Path) -> None:
        if self._source_image is None or self._preview_image is None:
            return
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        quad_image = _quad_from_payload_for_image(payload, self._source_image.size)
        if not quad_image:
            messagebox.showwarning("Image Region Extractor", "This JSON does not contain a usable region.")
            return
        quad_preview = [(x * self._preview_scale, y * self._preview_scale) for x, y in quad_image]
        self._region_path = path
        self._set_quad_selection(quad_preview)
        region_name = payload.get("name") or path.stem
        self._status_var.set(f"Loaded region: {region_name}")

    def _load_image(self, path: Path) -> None:
        image = Image.open(path).convert("RGBA")
        self._source_path = path
        self._source_image = image
        self._selection_preview = None
        self._selection_quad_preview = None
        self._drag_start = None
        self._region_path = None

        src_w, src_h = image.size
        scale = min(PREVIEW_MAX_WIDTH / max(src_w, 1), PREVIEW_MAX_HEIGHT / max(src_h, 1), 1.0)
        self._preview_scale = scale
        preview_size = (max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale))))
        self._preview_image = image.resize(preview_size, Image.Resampling.LANCZOS) if scale < 1.0 else image.copy()
        self._preview_photo = ImageTk.PhotoImage(self._preview_image)

        self._canvas.delete("all")
        self._canvas.config(width=preview_size[0], height=preview_size[1], scrollregion=(0, 0, preview_size[0], preview_size[1]))
        self._canvas.create_image(0, 0, image=self._preview_photo, anchor="nw")
        self._selection_canvas_id = None

        self._image_info.config(
            text=(
                f"{path.name} | original={src_w}x{src_h} "
                f"| preview={preview_size[0]}x{preview_size[1]} | scale={scale:.4f}"
            )
        )
        self._status_var.set("Drag to select a rectangle. Ctrl+S saves the crop.")

    def _reset_selection(self) -> None:
        self._selection_preview = None
        self._selection_quad_preview = None
        self._drag_start = None
        self._region_path = None
        if self._selection_canvas_id is not None:
            self._canvas.delete(self._selection_canvas_id)
            self._selection_canvas_id = None
        self._status_var.set("Selection cleared.")

    def _set_rect_selection(self, left: int, top: int, right: int, bottom: int) -> None:
        self._selection_preview = (left, top, right, bottom)
        self._selection_quad_preview = None
        if self._selection_canvas_id is not None:
            self._canvas.delete(self._selection_canvas_id)
        self._selection_canvas_id = self._canvas.create_rectangle(
            left, top, right, bottom, outline="#f5c842", width=2
        )

    def _set_quad_selection(self, quad_preview: list[tuple[float, float]]) -> None:
        self._selection_quad_preview = quad_preview
        xs = [p[0] for p in quad_preview]
        ys = [p[1] for p in quad_preview]
        self._selection_preview = (
            int(round(min(xs))),
            int(round(min(ys))),
            int(round(max(xs))),
            int(round(max(ys))),
        )
        if self._selection_canvas_id is not None:
            self._canvas.delete(self._selection_canvas_id)
        coords = [coord for point in quad_preview for coord in point]
        self._selection_canvas_id = self._canvas.create_polygon(
            *coords,
            outline="#4aa8e0",
            width=2,
            fill="",
        )

    def _on_press(self, event) -> None:
        if self._preview_image is None:
            return
        x = int(self._canvas.canvasx(event.x))
        y = int(self._canvas.canvasy(event.y))
        self._drag_start = (x, y)
        self._selection_quad_preview = None
        self._region_path = None
        if self._selection_canvas_id is not None:
            self._canvas.delete(self._selection_canvas_id)
        self._selection_canvas_id = self._canvas.create_rectangle(x, y, x, y, outline="#f5c842", width=2)

    def _on_drag(self, event) -> None:
        if self._preview_image is None or self._drag_start is None or self._selection_canvas_id is None:
            return
        x0, y0 = self._drag_start
        x1 = int(self._canvas.canvasx(event.x))
        y1 = int(self._canvas.canvasy(event.y))
        self._canvas.coords(self._selection_canvas_id, x0, y0, x1, y1)

    def _on_release(self, event) -> None:
        if self._preview_image is None or self._drag_start is None:
            return
        x0, y0 = self._drag_start
        x1 = int(self._canvas.canvasx(event.x))
        y1 = int(self._canvas.canvasy(event.y))
        left = max(0, min(x0, x1))
        top = max(0, min(y0, y1))
        right = min(self._preview_image.width, max(x0, x1))
        bottom = min(self._preview_image.height, max(y0, y1))
        self._drag_start = None
        if right - left < 2 or bottom - top < 2:
            self._status_var.set("Selection is too small.")
            return
        self._set_rect_selection(left, top, right, bottom)
        self._status_var.set(
            f"Selected preview rect: left={left}, top={top}, right={right}, bottom={bottom}"
        )

    def _save_crop(self) -> None:
        if self._source_image is None or self._source_path is None:
            messagebox.showinfo("Image Region Extractor", "Open an image first.")
            return
        if self._selection_preview is None:
            messagebox.showinfo("Image Region Extractor", "Select a region first.")
            return

        left, top, right, bottom = self._selection_preview
        quad_image = None
        crop_box_image = None
        if self._selection_quad_preview:
            quad_image = [(x / self._preview_scale, y / self._preview_scale) for x, y in self._selection_quad_preview]
            crop = _warp_quad_image(self._source_image, quad_image)
            xs = [point[0] for point in quad_image]
            ys = [point[1] for point in quad_image]
            crop_box_image = {
                "left": int(round(min(xs))),
                "top": int(round(min(ys))),
                "right": int(round(max(xs))),
                "bottom": int(round(max(ys))),
            }
        else:
            img_left = int(round(left / self._preview_scale))
            img_top = int(round(top / self._preview_scale))
            img_right = int(round(right / self._preview_scale))
            img_bottom = int(round(bottom / self._preview_scale))

            img_left = max(0, min(img_left, self._source_image.width))
            img_top = max(0, min(img_top, self._source_image.height))
            img_right = max(img_left + 1, min(img_right, self._source_image.width))
            img_bottom = max(img_top + 1, min(img_bottom, self._source_image.height))
            crop_box_image = {
                "left": img_left,
                "top": img_top,
                "right": img_right,
                "bottom": img_bottom,
            }
            crop = self._source_image.crop((img_left, img_top, img_right, img_bottom))

        base_name = _sanitize_name(self._prefix_var.get(), DEFAULT_PREFIX)
        png_path, json_path = _next_output_paths(self._output_dir, base_name)
        crop.save(png_path)

        payload = {
            "name": base_name,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "source_image_path": str(self._source_path),
            "source_size": {
                "width": self._source_image.width,
                "height": self._source_image.height,
            },
            "preview_scale": round(self._preview_scale, 6),
            "preview_rect": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
            },
            "crop_box_image": crop_box_image,
            "output_size": {
                "width": crop.width,
                "height": crop.height,
            },
            "image_path": str(png_path),
            "region_source_path": str(self._region_path) if self._region_path else None,
            "selection_mode": "quad" if quad_image else "rect",
            "points_image": (
                [{"x": round(x, 3), "y": round(y, 3)} for x, y in quad_image]
                if quad_image
                else None
            ),
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._status_var.set(f"Saved crop: {png_path.name}")
        messagebox.showinfo("Image Region Extractor", f"Saved:\n{png_path}\n{json_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open a local image file, drag a rectangle, and save the selected crop."
    )
    parser.add_argument("image", nargs="?", help="Optional initial image path to open.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where cropped PNG/JSON files will be saved.",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="Base filename prefix for saved crops.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    initial_image = Path(args.image).expanduser() if args.image else None
    app = ImageRegionExtractor(
        initial_image=initial_image,
        output_dir=Path(args.output_dir).expanduser(),
        prefix=args.prefix,
    )
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

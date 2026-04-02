"""
gui/dashboard.py — 메인 대시보드 GUI
블루아카이브 테마, 스캔 결과 표시, 설정 위자드 진입
"""

import json
import threading
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageTk

from core.config import save_config, load_config, config_exists
from core.scanner import ItemScanner, ScanResult
from gui.overlay import SetupWizard, REGION_CONFIGS

# ── 테마 ──────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BA_BG         = "#0d1b2a"
BA_CARD       = "#152435"
BA_CARD2      = "#1a2e40"
BA_BLUE       = "#1a6fad"
BA_LIGHT_BLUE = "#4aa8e0"
BA_YELLOW     = "#f5c842"
BA_GREEN      = "#3dbf7a"
BA_ORANGE     = "#e8894a"
BA_RED        = "#e85a5a"
BA_TEXT       = "#e8f4fd"
BA_SUBTEXT    = "#7ab3d4"
FONT_KR       = "Malgun Gothic"


# ── 컴포넌트 ───────────────────────────────────────────────
class ResourceCard(ctk.CTkFrame):
    def __init__(self, master, icon: str, label: str, value: str, **kw):
        super().__init__(master, fg_color=BA_CARD2, corner_radius=10, **kw)
        ctk.CTkLabel(self, text=icon, font=ctk.CTkFont(size=20)).pack(pady=(10, 2))
        ctk.CTkLabel(self, text=label,
                     font=ctk.CTkFont(family=FONT_KR, size=10),
                     text_color=BA_SUBTEXT).pack()
        ctk.CTkLabel(self, text=value,
                     font=ctk.CTkFont(family=FONT_KR, size=14, weight="bold"),
                     text_color=BA_TEXT).pack(pady=(2, 10))


class ItemRow(ctk.CTkFrame):
    def __init__(self, master, item, idx: int, **kw):
        bg = BA_CARD if idx % 2 == 0 else BA_CARD2
        super().__init__(master, fg_color=bg, corner_radius=6, **kw)

        tier_color = {
            "T1": "#aaaaaa", "T2": "#5bc2e7", "T3": "#3dbf7a",
            "T4": "#f5c842", "T5": "#e8894a", "T6": "#e85a5a",
            "T7": "#c97bec", "T8": "#4aa8e0", "T9": "#f5c842", "T10": "#e8894a",
        }.get(item.tier or "", BA_SUBTEXT)

        # 인덱스
        ctk.CTkLabel(self, text=f"{idx+1:>3}",
                     font=ctk.CTkFont(size=11), text_color=BA_SUBTEXT,
                     width=32).pack(side="left", padx=(8, 0))

        # 티어 배지
        tier_frame = ctk.CTkFrame(self, fg_color=tier_color, corner_radius=4, width=32, height=20)
        tier_frame.pack(side="left", padx=6)
        tier_frame.pack_propagate(False)
        ctk.CTkLabel(tier_frame, text=item.tier or "-",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="white").place(relx=0.5, rely=0.5, anchor="center")

        # 이름
        ctk.CTkLabel(self, text=item.name or "알 수 없음",
                     font=ctk.CTkFont(family=FONT_KR, size=12),
                     text_color=BA_TEXT, anchor="w").pack(side="left", padx=4, fill="x", expand=True)

        # 수량
        ctk.CTkLabel(self, text=f"× {item.quantity or '?'}",
                     font=ctk.CTkFont(family=FONT_KR, size=12, weight="bold"),
                     text_color=BA_YELLOW, width=80, anchor="e").pack(side="right", padx=12)


class SetupStatusPanel(ctk.CTkFrame):
    """설정 완료 여부 표시 패널"""
    def __init__(self, master, config: dict | None, **kw):
        super().__init__(master, fg_color=BA_CARD, corner_radius=12, **kw)

        ctk.CTkLabel(self, text="영역 설정 현황",
                     font=ctk.CTkFont(family=FONT_KR, size=13, weight="bold"),
                     text_color=BA_LIGHT_BLUE).pack(padx=14, pady=(12, 6), anchor="w")

        for key, cfg in REGION_CONFIGS.items():
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=2)

            done = config is not None and key in config
            icon = "✅" if done else "⬜"
            color = BA_GREEN if done else BA_SUBTEXT

            ctk.CTkLabel(row, text=f"{icon}  {cfg['label']}",
                         font=ctk.CTkFont(family=FONT_KR, size=11),
                         text_color=color, anchor="w").pack(side="left")

        ctk.CTkLabel(self, text="").pack(pady=4)


# ── 메인 앱 ───────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Blue Archive Analyzer")
        self.geometry("1200x780")
        self.minsize(960, 640)
        self.configure(fg_color=BA_BG)

        self.config_data = load_config()
        self.scan_result: ScanResult | None = None
        self.is_scanning = False
        self.status_var = ctk.StringVar(value="대기 중...")
        self.progress_var = ctk.StringVar(value="")

        self._build_ui()
        self._refresh_setup_status()

    # ── UI 구성 ───────────────────────────────────────────
    def _build_ui(self):
        # 헤더
        header = ctk.CTkFrame(self, fg_color=BA_CARD, corner_radius=0, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(header, text="🎓  Blue Archive  Analyzer",
                     font=ctk.CTkFont(family=FONT_KR, size=20, weight="bold"),
                     text_color=BA_LIGHT_BLUE).pack(side="left", padx=24)

        ctk.CTkLabel(header, textvariable=self.status_var,
                     font=ctk.CTkFont(family=FONT_KR, size=11),
                     text_color=BA_SUBTEXT).pack(side="right", padx=24)

        # 본문
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=12)

        # ── 왼쪽 사이드바 ──
        sidebar = ctk.CTkFrame(body, fg_color="transparent", width=260)
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        # ── 오른쪽 메인 ──
        main = ctk.CTkFrame(body, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)
        self._build_main(main)

    def _build_sidebar(self, parent):
        # 설정 상태
        self.setup_panel = SetupStatusPanel(parent, self.config_data)
        self.setup_panel.pack(fill="x", pady=(0, 10))

        # 설정 버튼
        self.setup_btn = ctk.CTkButton(
            parent, text="⚙️  영역 설정 시작",
            font=ctk.CTkFont(family=FONT_KR, size=13, weight="bold"),
            fg_color=BA_BLUE, hover_color=BA_LIGHT_BLUE,
            height=42, corner_radius=10,
            command=self._start_setup
        )
        self.setup_btn.pack(fill="x", pady=(0, 6))

        # 재설정 버튼
        ctk.CTkButton(
            parent, text="🔄  영역 재설정",
            font=ctk.CTkFont(family=FONT_KR, size=11),
            fg_color=BA_CARD2, hover_color=BA_BLUE,
            height=32, corner_radius=8,
            command=self._reset_config
        ).pack(fill="x", pady=(0, 12))

        # 스캔 버튼
        self.scan_btn = ctk.CTkButton(
            parent, text="🔍  전체 스캔 시작",
            font=ctk.CTkFont(family=FONT_KR, size=13, weight="bold"),
            fg_color=BA_GREEN, hover_color="#2da864",
            height=42, corner_radius=10,
            command=self._start_scan,
            state="disabled"
        )
        self.scan_btn.pack(fill="x", pady=(0, 6))

        # 재화 스캔
        self.res_btn = ctk.CTkButton(
            parent, text="💰  재화만 스캔",
            font=ctk.CTkFont(family=FONT_KR, size=11),
            fg_color=BA_CARD2, hover_color=BA_BLUE,
            height=32, corner_radius=8,
            command=self._scan_resources_only,
            state="disabled"
        )
        self.res_btn.pack(fill="x", pady=(0, 12))

        # 진행 상황
        prog_frame = ctk.CTkFrame(parent, fg_color=BA_CARD, corner_radius=10)
        prog_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(prog_frame, text="진행 상황",
                     font=ctk.CTkFont(family=FONT_KR, size=11),
                     text_color=BA_SUBTEXT).pack(padx=12, pady=(8, 4), anchor="w")
        ctk.CTkLabel(prog_frame, textvariable=self.progress_var,
                     font=ctk.CTkFont(family=FONT_KR, size=10),
                     text_color=BA_TEXT, wraplength=220,
                     justify="left").pack(padx=12, pady=(0, 10), anchor="w")

        # 저장 버튼
        ctk.CTkButton(
            parent, text="💾  결과 저장 (JSON)",
            font=ctk.CTkFont(family=FONT_KR, size=11),
            fg_color=BA_CARD2, hover_color=BA_BLUE,
            height=32, corner_radius=8,
            command=self._save_result
        ).pack(fill="x")

    def _build_main(self, parent):
        # 재화 카드 행
        self.res_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.res_frame.pack(fill="x", pady=(0, 12))
        self._build_resource_cards({})

        # 탭
        self.tabview = ctk.CTkTabview(parent, fg_color=BA_CARD, corner_radius=12)
        self.tabview.pack(fill="both", expand=True)
        self.tabview.add("📦  아이템 목록")
        self.tabview.add("👩  학생 정보")

        # 아이템 목록
        self.item_scroll = ctk.CTkScrollableFrame(
            self.tabview.tab("📦  아이템 목록"),
            fg_color="transparent"
        )
        self.item_scroll.pack(fill="both", expand=True)
        self._show_empty_items()

        # 학생 정보 (추후 확장)
        ctk.CTkLabel(
            self.tabview.tab("👩  학생 정보"),
            text="학생 화면에서 스캔 시 표시됩니다",
            font=ctk.CTkFont(family=FONT_KR, size=13),
            text_color=BA_SUBTEXT
        ).pack(expand=True)

    def _build_resource_cards(self, resources: dict):
        for w in self.res_frame.winfo_children():
            w.destroy()

        data = [
            ("💰", "크레딧",    resources.get("크레딧",  "-")),
            ("💎", "청휘석", resources.get("청휘석", "-")),
        ]
        for icon, label, value in data:
            card = ResourceCard(self.res_frame, icon, label, str(value))
            card.pack(side="left", fill="x", expand=True, padx=4)

    def _show_empty_items(self):
        for w in self.item_scroll.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.item_scroll,
            text="📋\n\n영역 설정 완료 후\n스캔 버튼을 눌러줘",
            font=ctk.CTkFont(family=FONT_KR, size=13),
            text_color=BA_SUBTEXT, justify="center"
        ).pack(expand=True, pady=60)

    def _show_items(self, items):
        for w in self.item_scroll.winfo_children():
            w.destroy()

        if not items:
            ctk.CTkLabel(self.item_scroll, text="아이템을 찾지 못했어",
                         font=ctk.CTkFont(family=FONT_KR, size=13),
                         text_color=BA_SUBTEXT).pack(pady=40)
            return

        # 헤더
        hdr = ctk.CTkFrame(self.item_scroll, fg_color=BA_BLUE, corner_radius=6)
        hdr.pack(fill="x", pady=(0, 4))
        for txt, w in [("#", 32), ("티어", 42), ("아이템 이름", 0), ("수량", 80)]:
            ctk.CTkLabel(hdr, text=txt,
                         font=ctk.CTkFont(family=FONT_KR, size=11, weight="bold"),
                         text_color="white",
                         width=w if w else 0).pack(
                side="left", padx=(8 if txt == "#" else 4)
            )

        for i, item in enumerate(items):
            ItemRow(self.item_scroll, item, i).pack(fill="x", pady=1)

    # ── 설정 위자드 ───────────────────────────────────────
    def _start_setup(self):
        self.status_var.set("⚙️ 영역 설정 중...")
        self.withdraw()  # 메인 창 숨김

        def on_complete(results: dict):
            save_config(results)
            self.config_data = load_config()
            self.deiconify()
            self._refresh_setup_status()
            self.status_var.set("✅ 영역 설정 완료!")

        def on_cancel():
            self.deiconify()
            self.status_var.set("❌ 설정 취소됨")

        wizard = SetupWizard(self, on_complete=on_complete, on_cancel=on_cancel)
        wizard.start()

    def _reset_config(self):
        from pathlib import Path
        Path("config.json").unlink(missing_ok=True)
        self.config_data = None
        self._refresh_setup_status()
        self.status_var.set("🔄 설정 초기화됨")

    def _refresh_setup_status(self):
        # 설정 상태 패널 갱신
        self.setup_panel.destroy()
        self.setup_panel = SetupStatusPanel(
            self.setup_btn.master, self.config_data
        )
        self.setup_panel.pack(fill="x", pady=(0, 10), before=self.setup_btn)

        # 스캔 버튼 활성화 여부
        all_set = (self.config_data is not None and
                   all(k in self.config_data for k in REGION_CONFIGS))
        state = "normal" if all_set else "disabled"
        self.scan_btn.configure(state=state)
        self.res_btn.configure(state=state)

    # ── 스캔 ──────────────────────────────────────────────
    def _start_scan(self):
        if self.is_scanning or not self.config_data:
            return
        self.is_scanning = True
        self.scan_btn.configure(state="disabled", text="스캔 중...")
        self.progress_var.set("스캔 준비 중...")

        def task():
            def on_progress(msg, cur, total):
                self.after(0, lambda: self.progress_var.set(msg))
                self.after(0, lambda: self.status_var.set(msg))

            scanner = ItemScanner(self.config_data, on_progress=on_progress)
            result = scanner.run_full_scan()
            self.scan_result = result

            self.after(0, lambda: self._build_resource_cards(result.resources))
            self.after(0, lambda: self._show_items(result.items))
            self.after(0, lambda: self.status_var.set(
                f"✅ 스캔 완료 — 아이템 {len(result.items)}개"
            ))
            self.after(0, lambda: self.scan_btn.configure(
                state="normal", text="🔍  전체 스캔 시작"
            ))
            self.is_scanning = False

        threading.Thread(target=task, daemon=True).start()

    def _scan_resources_only(self):
        if self.is_scanning or not self.config_data:
            return

        def task():
            from core.capture import capture_window
            img = capture_window()
            if img:
                from core.ocr import read_resources
                from core.capture import crop_region
                cropped = crop_region(img, self.config_data["resources"])
                resources = read_resources(cropped)
                self.after(0, lambda: self._build_resource_cards(resources))
                self.after(0, lambda: self.status_var.set("✅ 재화 스캔 완료"))
            else:
                self.after(0, lambda: self.status_var.set("❌ 캡처 실패"))

        threading.Thread(target=task, daemon=True).start()

    # ── 저장 ──────────────────────────────────────────────
    def _save_result(self):
        if not self.scan_result:
            self.status_var.set("⚠️ 저장할 결과가 없어")
            return
        from tkinter import filedialog
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"ba_scan_{ts}.json",
            filetypes=[("JSON", "*.json")]
        )
        if path:
            data = {
                "scanned_at": ts,
                "resources": self.scan_result.resources,
                "items": [
                    {"name": i.name, "quantity": i.quantity,
                     "tier": i.tier, "category": i.category}
                    for i in self.scan_result.items
                ],
            }
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            self.status_var.set(f"💾 저장 완료: {Path(path).name}")

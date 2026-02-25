"""Sensor de visão: captura de tela + OCR + contexto visual para o LLM."""

import base64
import io
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Tuple

from jarvis.config import (
    SCREEN_CAPTURE_FPS,
    OCR_LANGUAGES,
    TESSERACT_CMD,
    VISION_DEBUG,
    VISION_JPEG_QUALITY,
    VISION_MAX_WIDTH,
)
import os


class VisionSensor:
    """
    Captura a tela em baixa taxa e extrai texto via OCR.

    Roda em thread de background; o resultado fica em cache para leitura.
    Fornece:
      - get_last_ocr()         → texto OCR (quando Tesseract disponível)
      - get_screen_context_text() → texto OCR ou descrição de fallback
      - get_screenshot_base64()   → JPEG comprimido em base64 (para Claude Vision)
      - get_frame_age()           → segundos desde última captura
      - capture_if_stale()        → captura novo frame se cache antigo
    """

    def __init__(self):
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Estado compartilhado (protegido por lock)
        self._last_ocr: str = ""
        self._last_frame_time: float = 0.0
        self._last_screenshot = None          # PIL Image (já em escala reduzida)
        self._last_monitor_info: str = ""
        self._last_resolution: Tuple[int, int] = (0, 0)
        self._ocr_enabled: bool = True

        self._frame_interval: float = 1.0 / SCREEN_CAPTURE_FPS

        self._setup_tesseract()

    # ------------------------------------------------------------------ #
    #  Setup                                                               #
    # ------------------------------------------------------------------ #

    def _setup_tesseract(self) -> None:
        try:
            import pytesseract
            if os.path.exists(TESSERACT_CMD):
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
            # Configura pasta de dados de idioma (tessdata do usuário)
            tessdata = os.getenv("TESSDATA_PREFIX", "")
            if tessdata and os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata
            if VISION_DEBUG:
                print(f"[Vision] Tesseract configurado: {TESSERACT_CMD}")
        except ImportError:
            print("[Vision] pytesseract não instalado — OCR desativado.")
            self._ocr_enabled = False

    # ------------------------------------------------------------------ #
    #  Controle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="jarvis-vision"
        )
        self._thread.start()
        print("[Vision] Sensor de visão iniciado.")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        print("[Vision] Sensor de visão parado.")

    # ------------------------------------------------------------------ #
    #  Loop de captura                                                     #
    # ------------------------------------------------------------------ #

    def _capture_loop(self) -> None:
        while self._running:
            start = time.monotonic()
            try:
                self.capture()
            except Exception as e:
                print(f"[Vision] Erro na captura: {e}")
            elapsed = time.monotonic() - start
            sleep_time = max(0.0, self._frame_interval - elapsed)
            time.sleep(sleep_time)

    def capture(self) -> None:
        """Captura um frame e faz OCR (chamado internamente ou sob demanda)."""
        t_cap = time.perf_counter()
        screenshot, monitor_info, resolution = self._take_screenshot()
        if screenshot is None:
            return

        cap_ms = (time.perf_counter() - t_cap) * 1000
        now = time.time()
        ts_str = datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]

        with self._lock:
            self._last_screenshot = screenshot
            self._last_frame_time = now
            self._last_monitor_info = monitor_info
            self._last_resolution = resolution

        if VISION_DEBUG:
            print(
                f"[Vision] Captura OK | {ts_str} | "
                f"{resolution[0]}x{resolution[1]} | "
                f"{monitor_info} | "
                f"captura={cap_ms:.0f}ms"
            )

        if self._ocr_enabled:
            t_ocr = time.perf_counter()
            ocr_text = self._run_ocr(screenshot)
            ocr_ms = (time.perf_counter() - t_ocr) * 1000
            with self._lock:
                self._last_ocr = ocr_text
            if VISION_DEBUG:
                print(
                    f"[Vision] OCR OK | {len(ocr_text)} chars | {ocr_ms:.0f}ms"
                )

    def _take_screenshot(self):
        """Captura a tela usando mss. Retorna (PIL Image, monitor_info, resolution) ou (None, '', (0,0))."""
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                monitors = sct.monitors
                # Monitor 1 = monitor principal (índice 0 é "todos juntos")
                if len(monitors) < 2:
                    print("[Vision] Nenhum monitor detectado pelo mss.")
                    return None, "", (0, 0)

                monitor = monitors[1]
                monitor_info = (
                    f"monitor 1 ({monitor['width']}x{monitor['height']} "
                    f"@ {monitor.get('left', 0)},{monitor.get('top', 0)})"
                )

                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                orig_w, orig_h = img.size

                # Reduz resolução para OCR mais rápido
                img = img.resize((orig_w // 2, orig_h // 2))
                resolution = img.size
                return img, monitor_info, resolution

        except ImportError:
            print("[Vision] mss não instalado — captura de tela desativada.")
            return None, "", (0, 0)
        except Exception as e:
            print(f"[Vision] Erro ao capturar tela ({type(e).__name__}): {e}")
            return None, "", (0, 0)

    def _run_ocr(self, image) -> str:
        """Executa OCR na imagem. Retorna texto ou string vazia."""
        if not self._ocr_enabled or image is None:
            return ""
        try:
            import pytesseract

            # Converte para escala de cinza para melhor OCR
            gray = image.convert("L")
            text = pytesseract.image_to_string(
                gray,
                lang=OCR_LANGUAGES,
                config="--psm 6",   # Assume bloco uniforme de texto
            )
            return text.strip()
        except Exception as e:
            if "tesseract" in str(e).lower():
                self._ocr_enabled = False
                print(
                    "[Vision] Tesseract não encontrado — OCR desativado. "
                    "Instale de: https://github.com/UB-Mannheim/tesseract/wiki\n"
                    "[Vision] Visão multimodal (Claude) ainda funciona sem OCR."
                )
            return ""

    # ------------------------------------------------------------------ #
    #  Leitura do estado (thread-safe)                                     #
    # ------------------------------------------------------------------ #

    def get_last_ocr(self, max_chars: int = 800) -> str:
        """Retorna o último texto OCR capturado (vazio se OCR desativado)."""
        with self._lock:
            text = self._last_ocr
        return text[:max_chars] if text else ""

    def get_screen_context_text(self, max_chars: int = 800) -> str:
        """
        Retorna contexto textual da tela para providers sem visão multimodal.
        Se OCR ativo: retorna o texto OCR.
        Se OCR inativo mas screenshot disponível: retorna metadados do frame.
        """
        with self._lock:
            text = self._last_ocr
            has_screenshot = self._last_screenshot is not None
            frame_time = self._last_frame_time
            res = self._last_resolution
            monitor_info = self._last_monitor_info

        if text:
            return text[:max_chars]

        if has_screenshot:
            age = round(time.time() - frame_time, 1)
            ts_str = datetime.fromtimestamp(frame_time).strftime("%H:%M:%S")
            return (
                f"[Screenshot disponível: {res[0]}x{res[1]}, "
                f"{monitor_info}, capturado às {ts_str} ({age}s atrás). "
                f"OCR não disponível — use visão multimodal para analisar o conteúdo.]"
            )

        return ""

    def get_screenshot_base64(
        self,
        quality: Optional[int] = None,
        max_width: Optional[int] = None,
    ) -> Optional[str]:
        """
        Retorna o último screenshot como JPEG base64 para uso multimodal (Claude Vision).
        Retorna None se nenhum frame foi capturado.
        """
        q = quality if quality is not None else VISION_JPEG_QUALITY
        mw = max_width if max_width is not None else VISION_MAX_WIDTH

        with self._lock:
            screenshot = self._last_screenshot
            frame_time = self._last_frame_time
            resolution = self._last_resolution

        if screenshot is None:
            return None

        try:
            img = screenshot
            w, h = img.size
            if w > mw:
                ratio = mw / w
                img = img.resize((int(w * ratio), int(h * ratio)))

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=q, optimize=True)
            b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            size_kb = len(buffer.getvalue()) / 1024

            if VISION_DEBUG:
                age = round(time.time() - frame_time, 1)
                print(
                    f"[Vision] Screenshot base64 | "
                    f"{img.size[0]}x{img.size[1]} | "
                    f"quality={q} | {size_kb:.1f}KB | "
                    f"frame_age={age}s"
                )
            return b64
        except Exception as e:
            print(f"[Vision] Erro ao codificar screenshot: {e}")
            return None

    def get_frame_age(self) -> float:
        """Retorna a idade do último frame em segundos."""
        with self._lock:
            ft = self._last_frame_time
        if ft == 0.0:
            return float("inf")
        return time.time() - ft

    def capture_if_stale(self, max_age_s: float = 2.0) -> bool:
        """
        Captura um novo frame se o atual for mais velho que max_age_s.
        Retorna True se capturou novo frame.
        """
        if self.get_frame_age() > max_age_s:
            self.capture()
            return True
        return False

    def get_context(self) -> Dict[str, str]:
        """Retorna contexto visual resumido para o agente."""
        with self._lock:
            has_screenshot = self._last_screenshot is not None
            frame_time = self._last_frame_time
            resolution = self._last_resolution

        return {
            "screen_text": self.get_screen_context_text(),
            "has_screenshot": str(has_screenshot),
            "frame_age_s": str(round(self.get_frame_age(), 1)),
            "resolution": f"{resolution[0]}x{resolution[1]}" if resolution != (0, 0) else "",
        }

    def capture_on_demand(self) -> str:
        """Força captura imediata e retorna o texto OCR (ou contexto de fallback)."""
        self.capture()
        return self.get_screen_context_text()

    @property
    def ocr_enabled(self) -> bool:
        return self._ocr_enabled

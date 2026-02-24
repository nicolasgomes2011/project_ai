"""Sensor de visão: captura de tela + OCR + detecção de contexto visual."""

import threading
import time
from typing import Optional, Dict

from jarvis.config import SCREEN_CAPTURE_FPS, OCR_LANGUAGES, TESSERACT_CMD
import os


class VisionSensor:
    """
    Captura a tela em baixa taxa e extrai texto via OCR.
    Roda em thread de background; o resultado fica em cache para leitura.
    """

    def __init__(self):
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Estado compartilhado (protegido por lock)
        self._last_ocr: str = ""
        self._last_frame_time: float = 0.0
        self._last_screenshot = None          # PIL Image
        self._ocr_enabled: bool = True

        self._frame_interval: float = 1.0 / SCREEN_CAPTURE_FPS
        self._prev_ocr_hash: int = 0          # Para detectar mudanças

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
        screenshot = self._take_screenshot()
        if screenshot is None:
            return

        with self._lock:
            self._last_screenshot = screenshot
            self._last_frame_time = time.time()

        if self._ocr_enabled:
            ocr_text = self._run_ocr(screenshot)
            with self._lock:
                self._last_ocr = ocr_text

    def _take_screenshot(self):
        """Captura a tela usando mss. Retorna PIL Image ou None."""
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # Monitor principal
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                # Reduz resolução para OCR mais rápido
                w, h = img.size
                img = img.resize((w // 2, h // 2))
                return img
        except ImportError:
            print("[Vision] mss não instalado — captura de tela desativada.")
            return None
        except Exception as e:
            print(f"[Vision] Erro ao capturar tela: {e}")
            return None

    def _run_ocr(self, image) -> str:
        """Executa OCR na imagem. Retorna texto ou string vazia."""
        if not self._ocr_enabled or image is None:
            return ""
        try:
            import pytesseract
            from PIL import Image

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
                print("[Vision] Tesseract não encontrado — OCR desativado. "
                      "Instale de: https://github.com/UB-Mannheim/tesseract/wiki")
            return ""

    # ------------------------------------------------------------------ #
    #  Leitura do estado (thread-safe)                                     #
    # ------------------------------------------------------------------ #

    def get_last_ocr(self, max_chars: int = 800) -> str:
        """Retorna o último texto OCR capturado."""
        with self._lock:
            text = self._last_ocr
        return text[:max_chars] if text else ""

    def get_context(self) -> Dict[str, str]:
        """Retorna contexto visual para o agente."""
        ocr = self.get_last_ocr()
        return {
            "screen_text": ocr,
            "has_ocr": str(bool(ocr)),
            "frame_age_s": str(round(time.time() - self._last_frame_time, 1)),
        }

    def capture_on_demand(self) -> str:
        """Força captura imediata e retorna o texto OCR."""
        self.capture()
        return self.get_last_ocr()

    @property
    def ocr_enabled(self) -> bool:
        return self._ocr_enabled

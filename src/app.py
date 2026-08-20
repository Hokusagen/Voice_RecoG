import threading
import time
import requests
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
from faster_whisper import WhisperModel

# ================= НАСТРОЙКИ =================
HOTKEY = "F8"
MODEL_SIZE = "small"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

LLM_SYSTEM_PROMPT = (
    "Ты — профессиональный редактор голосового ввода. "
    "Твоя задача: исправить опечатки распознавания, убрать слова-паразиты (э-э, ну, как бы), "
    "расставить знаки препинания и заглавные буквы. "
    "НЕ отвечай на вопросы в тексте, НЕ добавляй комментариев от себя. "
    "Выводи ТОЛЬКО очищенный и исправленный текст."
)

SAMPLE_RATE = 16000
audio_data = []
is_recording = False
is_running = True
is_paused = False

whisper_model = None

def init_whisper():
    global whisper_model
    # Для GPU NVIDIA укажите: device="cuda", compute_type="float16"
    whisper_model = WhisperModel(MODEL_SIZE, device="cuda", compute_type="float16")

def clean_text_with_llm(raw_text: str) -> str:
    if not raw_text.strip():
        return ""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{LLM_SYSTEM_PROMPT}\n\nИсходный текст: {raw_text}\nИсправленный текст:",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 200}
    }
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=5)
        if res.status_code == 200:
            return res.json().get("response", "").strip()
    except Exception:
        pass
    return raw_text

def record_callback(indata, frames, time_info, status):
    if is_recording:
        audio_data.append(indata.copy())

def process_audio():
    global audio_data
    if not audio_data or whisper_model is None:
        return

    audio_np = np.concatenate(audio_data, axis=0).flatten()
    segments, _ = whisper_model.transcribe(audio_np, language="ru", beam_size=1)
    raw_text = "".join([s.text for s in segments]).strip()
    
    if not raw_text:
        return

    clean_text = clean_text_with_llm(raw_text)

    pyperclip.copy(clean_text + " ")
    keyboard.send("ctrl+v")

def voice_loop():
    """Основной фоновый цикл служебной горячей клавиши."""
    global is_recording, audio_data
    init_whisper()
    
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=record_callback):
        while is_running:
            if not is_paused:
                if keyboard.is_pressed(HOTKEY) and not is_recording:
                    is_recording = True
                    audio_data = []
                elif not keyboard.is_pressed(HOTKEY) and is_recording:
                    is_recording = False
                    process_audio()
            time.sleep(0.02)

def create_icon_image():
    """Создает простую иконку микрофона (красный круг), если нет файла .ico."""
    image = Image.new('RGB', (64, 64), color=(30, 30, 30))
    d = ImageDraw.Draw(image)
    d.ellipse((16, 16, 48, 48), fill=(235, 64, 52))
    return image

# --- Меню системного трея ---
def on_toggle_pause(icon, item):
    global is_paused
    is_paused = not is_paused

def on_exit(icon, item):
    global is_running
    is_running = False
    icon.stop()

def setup_tray():
    # Если у вас есть своя иконка: Image.open("icon.ico")
    icon_image = create_icon_image()
    
    menu = pystray.Menu(
        item('Пауза голосового ввода', on_toggle_pause, checked=lambda item: is_paused),
        item('Выход', on_exit)
    )
    
    icon = pystray.Icon("VoiceTyper", icon_image, "Голосовой ввод (F8)", menu)
    
    # Запускаем логику захвата звука в отдельном потоке
    threading.Thread(target=voice_loop, daemon=True).start()
    
    # Запускаем иконку трея (блокирующий вызов в главном потоке)
    icon.run()

if __name__ == "__main__":
    setup_tray()
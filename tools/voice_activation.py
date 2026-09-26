import json, os, tempfile, threading, time
from datetime import datetime
from typing import Optional
from .registry import register

SAMPLE_RATE = 16000
ENERGY_THRESHOLD = 0.008
SILENCE_TIMEOUT = 1.5
MAX_RECORD_SECONDS = 15
WAKE_WORDS = ["ainslup", "hey ainslup", "ey ainslup", "xens", "hey xens"]
CONVERSATION_TIMEOUT = 60

class VoiceActivator:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._is_speaking = False
        self._silence_start = 0.0
        self._audio_buffer: list = []
        self._is_processing = False
        self._wake_mode = True
        self._last_transcription = ""
        self._in_conversation = False
        self._last_activity = 0.0
        self._whisper_model = None
        self._stream = None

    def start(self, mode: str = "wake_word") -> Optional[str]:
        """Devuelve None si arrancó OK, o un mensaje de error."""
        if self._running:
            return None
        self._wake_mode = mode in ("wake_word", "conversation")
        self._conversation_mode = mode == "conversation"
        try:
            import sounddevice as sd
        except ImportError:
            return "sounddevice no instalado (pip install sounddevice)"
        try:
            from faster_whisper import WhisperModel
            self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        except Exception:
            return "faster_whisper no disponible o falló la carga del modelo"
        self._running = True
        self._stop.clear()
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        self._stream.start()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="voice-activator")
        self._thread.start()
        return None

    def stop(self):
        self._running = False
        self._stop.set()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    @property
    def last_transcription(self) -> str:
        return self._last_transcription

    def status(self) -> dict:
        return {"running": self._running, "in_conversation": self._in_conversation, "last_transcription": self._last_transcription[:60]}

    def _loop(self):
        window = int(SAMPLE_RATE * 0.5)
        while not self._stop.is_set():
            try:
                chunk, _ = self._stream.read(window)
                energy = (chunk ** 2).mean() ** 0.5
                if energy > ENERGY_THRESHOLD:
                    if not self._is_speaking:
                        self._is_speaking = True
                        self._audio_buffer = []
                        self._silence_start = 0.0
                    self._audio_buffer.append(chunk.copy())
                    self._silence_start = time.time()
                else:
                    if self._is_speaking:
                        elapsed = time.time() - self._silence_start
                        if elapsed > SILENCE_TIMEOUT or len(self._audio_buffer) * 0.5 > MAX_RECORD_SECONDS:
                            self._is_speaking = False
                            if not self._is_processing:
                                self._is_processing = True
                                threading.Thread(target=self._process_audio, args=(list(self._audio_buffer),), daemon=True).start()
                            self._audio_buffer = []
                if self._conversation_mode and self._in_conversation and time.time() - self._last_activity > CONVERSATION_TIMEOUT:
                    self._in_conversation = False
            except Exception:
                pass

    def _process_audio(self, buffer_frames):
        try:
            if not buffer_frames or self._whisper_model is None:
                return
            import numpy as np
            audio = np.concatenate(buffer_frames) if len(buffer_frames) > 1 else buffer_frames[0]
            audio_int16 = (audio * 32767).astype("int16")
            tmp = os.path.join(tempfile.gettempdir(), f"vad_{datetime.now().strftime('%H%M%S')}.wav")
            try:
                import scipy.io.wavfile as wav
                wav.write(tmp, SAMPLE_RATE, audio_int16)
            except ImportError:
                import wave
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(audio_int16.tobytes())
            segments, _ = self._whisper_model.transcribe(tmp, language="es")
            texto = " ".join(seg.text for seg in segments).strip()
            self._last_transcription = texto
            try:
                os.remove(tmp)
            except Exception:
                pass
            if not texto:
                return
            texto_lower = texto.lower().strip()
            if self._conversation_mode:
                for ww in WAKE_WORDS:
                    if ww in texto_lower:
                        self._in_conversation = True
                        self._last_activity = time.time()
                        return
                if self._in_conversation:
                    self._last_activity = time.time()
            elif self._wake_mode:
                for ww in WAKE_WORDS:
                    if ww in texto_lower:
                        self._in_conversation = True
                        self._last_activity = time.time()
                        return
        except Exception:
            pass
        finally:
            self._is_processing = False

_activator: Optional[VoiceActivator] = None

def get_activator() -> VoiceActivator:
    global _activator
    if _activator is None:
        _activator = VoiceActivator()
    return _activator

@register(name="start_voice_activation", description="Iniciar deteccion de voz continua (always listening)", parameters={"type": "object", "properties": {"mode": {"type": "string", "enum": ["wake_word", "conversation"], "description": "wake_word: espera a 'XENS', conversation: loop automatico"}}, "required": []}, tier="premium")
def start_voice_activation(mode: str = "wake_word") -> str:
    act = get_activator()
    err = act.start(mode=mode)
    if err:
        return json.dumps({"error": err, "success": False})
    return json.dumps({"success": True, "message": f"Activacion de voz iniciada (modo: {mode})"})

@register(name="stop_voice_activation", description="Detener deteccion de voz continua", parameters={"type": "object", "properties": {}, "required": []}, tier="premium", internal=True)
def stop_voice_activation() -> str:
    act = get_activator()
    act.stop()
    return "Activacion de voz detenida"

@register(name="voice_activation_status", description="Estado del detector de voz", parameters={"type": "object", "properties": {}, "required": []}, tier="free")
def voice_activation_status() -> str:
    act = get_activator()
    s = act.status()
    return f"VoiceActivation: {'activo' if s['running'] else 'detenido'}, en_conversacion={s['in_conversation']}, ultima='{s['last_transcription'] or 'N/A'}'"

@register(name="start_voice_loop", description="Alias de start_voice_activation para compatibilidad", tier="premium")
def start_voice_loop() -> str:
    return start_voice_activation(mode="conversation")

@register(name="stop_voice_loop", description="Alias de stop_voice_activation para compatibilidad", tier="premium", internal=True)
def stop_voice_loop() -> str:
    return stop_voice_activation()

@register(name="voice_loop_status", description="Alias de voice_activation_status para compatibilidad", tier="free")
def voice_loop_status() -> str:
    return voice_activation_status()

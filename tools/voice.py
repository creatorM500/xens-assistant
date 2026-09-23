from .registry import register
"""
voice.py — Text-to-Speech and Speech-to-Text.
TTS: edge-tts (streaming/natural) with pyttsx3 fallback.
STT: faster-whisper + sounddevice.
Ported from Xens Omni voz.py with cleanup and JSON returns.
"""
import asyncio, json, logging, os, threading, tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xens.tools.voice")

_TTS_ENGINE = None
_TTS_LOCK = threading.Lock()
_TTS_STREAMING = False
_TTS_STREAMING_LOCK = threading.Lock()


def _get_tts():
    global _TTS_ENGINE
    if _TTS_ENGINE is not None:
        return _TTS_ENGINE
    try:
        import pyttsx3
        _TTS_ENGINE = pyttsx3.init()
        _TTS_ENGINE.setProperty("rate", 160)
        _TTS_ENGINE.setProperty("volume", 0.9)
        voices = _TTS_ENGINE.getProperty("voices")
        for v in voices:
            if "spanish" in v.name.lower() or "español" in v.name.lower():
                _TTS_ENGINE.setProperty("voice", v.id)
                break
    except Exception:
        _TTS_ENGINE = False
    return _TTS_ENGINE


def _has_edge_tts() -> bool:
    try:
        import edge_tts
        return True
    except ImportError:
        return False


@register(name="speak", description="Speak text aloud using TTS (edge-tts or pyttsx3 fallback).", tier="free")
def speak(text: str, voice: str = "es-ES-AbrilNeural", style: str = "cheerful", rate: str = "+4%", pitch: str = "+2Hz") -> str:
    if not text or not text.strip():
        return json.dumps({"error": "Text is required", "success": False})
    if _has_edge_tts():
        # SSML expresivo para voz humana con entonación (cualquier PC con internet)
        ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="es-ES"><voice name="{voice}"><mstts:express-as style="{style}"><prosody rate="{rate}" pitch="{pitch}">{text}</prosody></mstts:express-as></voice></speak>'
        return _speak_edge(ssml, voice, is_ssml=True)
    tts = _get_tts()
    if not tts:
        return json.dumps({"error": "TTS not available (pip install edge-tts or pyttsx3)", "success": False})
    try:
        def _do_speak():
            with _TTS_LOCK:
                tts.say(text)
                tts.runAndWait()
        thread = threading.Thread(target=_do_speak, daemon=True)
        thread.start()
        return json.dumps({"success": True, "engine": "pyttsx3", "text": text[:80]})
    except Exception as e:
        return json.dumps({"error": f"TTS failed: {e}", "success": False})


def _speak_edge(text: str, voice: str = "es-ES-AbrilNeural", is_ssml: bool = False) -> str:
    try:
        thread = threading.Thread(
            target=_async_loop,
            args=(_speak_edge_async(text, voice, is_ssml),),
            daemon=True,
        )
        thread.start()
        preview = text[:80].replace("<", "").replace(">", "")
        return json.dumps({"success": True, "engine": "edge-tts", "voice": voice, "text": preview})
    except Exception as e:
        return json.dumps({"error": f"Edge TTS failed: {e}", "success": False})


def _async_loop(coro):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
        loop.close()
    except Exception as e:
        logger.warning("TTS async error: %s", e)


async def _speak_edge_async(text: str, voice: str = "es-ES-AbrilNeural", is_ssml: bool = False):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    with _TTS_STREAMING_LOCK:
        global _TTS_STREAMING
        _TTS_STREAMING = True
        # FIX estática: edge-tts stream es MP3, no PCM. No usar pyaudio directo (causa ruido).
        # Siempre guardar a archivo y reproducir con pygame/winsound (cualquier PC).
        try:
            tmp = Path(tempfile.gettempdir()) / f"xens_tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
            await communicate.save(str(tmp))
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(str(tmp))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    await asyncio.sleep(0.1)
                pygame.mixer.quit()
            except ImportError:
                try:
                    import winsound
                    winsound.PlaySound(str(tmp), winsound.SND_FILENAME | winsound.SND_ASYNC)
                    await asyncio.sleep(0.5)
                    # esperar duración estimada (no bloqueante perfecto, pero sin estática)
                    await asyncio.sleep(len(text) * 0.05)
                except Exception:
                    import subprocess
                    subprocess.run(["cmd", "/c", "start", "", str(tmp)], shell=False)
                    await asyncio.sleep(2)
            try:
                tmp.unlink()
            except Exception:
                pass
        except Exception as e:
            logger.warning("Edge TTS failed: %s", e)
        finally:
            _TTS_STREAMING = False


@register(name="stop_speech", description="Stop any ongoing TTS speech.", tier="free", internal=True)
def stop_speech():
    with _TTS_STREAMING_LOCK:
        global _TTS_STREAMING
        _TTS_STREAMING = False


def is_speaking() -> bool:
    with _TTS_STREAMING_LOCK:
        return _TTS_STREAMING


def _has_sounddevice() -> bool:
    try:
        import sounddevice
        return True
    except ImportError:
        return False


def _has_whisper() -> bool:
    try:
        import faster_whisper
        return True
    except ImportError:
        return False


@register(name="listen", description="Record microphone and transcribe to text using faster-whisper.", tier="free")
def listen(duration: int = 5, model: str = "tiny") -> str:
    if not _has_sounddevice():
        return json.dumps({"error": "Recording not available (pip install sounddevice)", "success": False})
    if not _has_whisper():
        return json.dumps({"error": "STT not available (pip install faster-whisper)", "success": False})
    try:
        import sounddevice as sd
        from faster_whisper import WhisperModel
        sample_rate = 16000
        audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        tmp = Path(tempfile.gettempdir()) / f"voice_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        try:
            import scipy.io.wavfile as wav
            wav.write(str(tmp), sample_rate, audio)
        except ImportError:
            import wave
            import numpy as np
            with wave.open(str(tmp), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes((np.asarray(audio) * 32767).astype("int16").tobytes())
        model_instance = WhisperModel(model, device="cpu", compute_type="int8")
        segments, _ = model_instance.transcribe(str(tmp), language="es")
        text = " ".join(seg.text for seg in segments).strip()
        try:
            tmp.unlink()
        except Exception:
            pass
        if text:
            return json.dumps({"success": True, "text": text, "duration": duration})
        return json.dumps({"success": True, "text": "", "note": "No speech detected"})
    except Exception as e:
        return json.dumps({"error": f"Recording failed: {e}", "success": False})


@register(name="voice_status", description="Check TTS and STT availability.", tier="free")
def voice_status() -> str:
    return json.dumps({
        "success": True,
        "tts": _has_edge_tts() or _get_tts() is not False,
        "stt": _has_sounddevice() and _has_whisper(),
        "edge_tts": _has_edge_tts(),
        "sounddevice": _has_sounddevice(),
        "faster_whisper": _has_whisper(),
        "currently_speaking": _TTS_STREAMING,
    })

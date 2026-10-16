import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path


class SttUnavailableError(RuntimeError):
    pass


@dataclass
class TranscriptUpdate:
    partial: str | None = None
    final: str | None = None


class VoskTranscriber:
    """One Vosk recognizer per active WebSocket session."""

    def __init__(self, model_path: Path, silence_seconds: float, rms_threshold: int):
        try:
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:  # pragma: no cover - dependency failure
            raise SttUnavailableError("Vosk is not installed. Run pip install -e '.[dev]'.") from exc
        if not model_path.exists():
            raise SttUnavailableError(f"Vosk model not found at {model_path}")
        self._model = Model(str(model_path))
        self._recognizer_factory = KaldiRecognizer
        self._recognizer = self._new_recognizer()
        self._silence_seconds = silence_seconds
        self._rms_threshold = rms_threshold
        self._silent_for = 0.0

    def _new_recognizer(self):
        recognizer = self._recognizer_factory(self._model, 16_000)
        recognizer.SetWords(True)
        return recognizer

    def accept_audio(self, pcm: bytes) -> TranscriptUpdate:
        if not pcm:
            return TranscriptUpdate()
        duration = len(pcm) / 32_000  # 16 kHz × mono × 16-bit
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[:len(pcm) - len(pcm) % 2])
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0
        self._silent_for = self._silent_for + duration if rms < self._rms_threshold else 0.0
        if self._recognizer.AcceptWaveform(pcm):
            return TranscriptUpdate(final=self._text(self._recognizer.Result()))
        if self._silent_for >= self._silence_seconds:
            return TranscriptUpdate(final=self._flush())
        return TranscriptUpdate(partial=self._text(self._recognizer.PartialResult(), "partial"))

    def finish(self) -> TranscriptUpdate:
        return TranscriptUpdate(final=self._flush())

    def _flush(self) -> str:
        text = self._text(self._recognizer.FinalResult())
        self._recognizer = self._new_recognizer()
        self._silent_for = 0.0
        return text

    @staticmethod
    def _text(raw: str, key: str = "text") -> str:
        return str(json.loads(raw).get(key, "")).strip()

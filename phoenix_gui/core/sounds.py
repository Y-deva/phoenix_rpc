"""Small, dependency-free interface sounds.

The WAV files are synthesized once into the user cache directory. This
keeps the repository free of binary assets, avoids network access, and
lets the volume setting work uniformly on every platform supported by
Qt Multimedia.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

from PyQt6.QtCore import QObject, QStandardPaths, QUrl

try:
    from PyQt6.QtMultimedia import QSoundEffect
except ImportError:  # pragma: no cover - minimal Qt builds
    QSoundEffect = None  # type: ignore[assignment]

from ..settings import Settings

SAMPLE_RATE = 44100
SOUND_NAMES = ("success", "error", "notify")


def synthesize_wav(
    notes: list[tuple[float, float, float]], duration: float = 0.35
) -> bytes:
    """Synthesize a short mono WAV from (frequency, start, length) notes.

    A short attack and exponential release avoid clicks. Silence is
    appended so the file always has the requested duration.
    """
    total_samples = max(1, int(duration * SAMPLE_RATE))
    samples = [0.0] * total_samples
    for frequency, start, length in notes:
        begin = max(0, int(start * SAMPLE_RATE))
        count = max(1, int(length * SAMPLE_RATE))
        for index in range(count):
            position = begin + index
            if position >= total_samples:
                break
            envelope = min(1.0, index / max(1, int(0.012 * SAMPLE_RATE)))
            envelope *= math.exp(-3.2 * index / count)
            samples[position] += (
                math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
                * envelope
                * 0.32
            )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for value in samples:
            clipped = max(-1.0, min(1.0, value))
            frames.extend(struct.pack("<h", int(clipped * 32767)))
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


SOUND_RECIPES = {
    "success": ([(659.25, 0.0, 0.16), (880.0, 0.13, 0.22)], 0.4),
    "error": ([(220.0, 0.0, 0.22), (174.61, 0.16, 0.3)], 0.48),
    "notify": ([(880.0, 0.0, 0.12)], 0.2),
}


def cache_directory() -> Path:
    """Return the per-user cache directory for synthesized sounds."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    path = Path(base or (Path.home() / ".cache" / "phoenix-wallet")) / "sounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_sound_files() -> dict[str, Path]:
    """Create the WAV files if they are missing and return their paths."""
    directory = cache_directory()
    result: dict[str, Path] = {}
    for name in SOUND_NAMES:
        path = directory / f"{name}.wav"
        if not path.is_file():
            notes, duration = SOUND_RECIPES[name]
            try:
                path.write_bytes(synthesize_wav(notes, duration))
            except OSError:
                continue
        result[name] = path
    return result


class SoundPlayer(QObject):
    """Play optional UI sounds while respecting the volume setting."""

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        """Initialize the SoundPlayer instance."""
        super().__init__(parent)
        self._settings = settings
        self._effects: dict[str, object] = {}
        self._available = QSoundEffect is not None
        settings.changed.connect(self._on_setting_changed)
        if self._available and settings.sounds_enabled:
            self._prepare()

    def _on_setting_changed(self, key: str, value: object) -> None:
        """Apply volume changes immediately and prepare effects on demand."""
        if key == "sounds/volume":
            self._apply_volume()
        elif key == "sounds/enabled" and value:
            self._prepare()

    def _prepare(self) -> None:
        """Create the effects and their cache files on first use."""
        if self._effects or not self._available:
            return
        try:
            for name, path in ensure_sound_files().items():
                effect = QSoundEffect(self)
                effect.setSource(QUrl.fromLocalFile(str(path)))
                self._effects[name] = effect
            self._apply_volume()
        except Exception:  # pragma: no cover - no audio backend in headless CI
            self._available = False

    def _apply_volume(self) -> None:
        """Push the current volume to every prepared effect."""
        volume = self._settings.sound_volume / 100.0
        for effect in self._effects.values():
            try:
                effect.setVolume(volume)
            except Exception:
                pass

    @property
    def available(self) -> bool:
        """Return whether an audio backend is available."""
        return self._available

    def play(self, name: str = "notify") -> None:
        """Play one of success, error or notify when sounds are enabled."""
        if not self._available or not self._settings.sounds_enabled:
            return
        self._prepare()
        effect = self._effects.get(name)
        if effect is None:
            return
        try:
            effect.play()
        except Exception:
            pass

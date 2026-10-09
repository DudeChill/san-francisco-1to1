#!/usr/bin/env python3
"""Procedural ambience WAVs for the SF city project -> res://audio/."""
import os, wave, struct
import numpy as np

SR = 44100
OUT = os.path.join(os.path.dirname(__file__), "..", "audio")


def write_wav(name: str, data: np.ndarray, loop_meta: bool = False) -> None:
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {path} ({len(pcm)/SR:.1f}s)")


def wind_loop(seconds: float = 10.0) -> np.ndarray:
    rng = np.random.default_rng(1906)
    n = int(SR * seconds)
    noise = rng.standard_normal(n)
    # FFT lowpass ~600 Hz with gentle slope (maritime wind bed).
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    gain = 1.0 / (1.0 + (freqs / 420.0) ** 2.2)
    sig = np.fft.irfft(spec * gain, n)
    # Slow gusting LFO (0.07 Hz + 0.19 Hz).
    t = np.arange(n) / SR
    lfo = 0.62 + 0.24 * np.sin(2 * np.pi * 0.07 * t) + 0.14 * np.sin(2 * np.pi * 0.19 * t + 1.3)
    sig *= lfo
    # Crossfade tail into head for seamless looping.
    fade = int(SR * 1.0)
    ramp = np.linspace(0, 1, fade)
    sig[:fade] = sig[:fade] * ramp + sig[-fade:] * (1 - ramp)
    return sig[:-fade] * 0.5


def foghorn(seconds: float = 2.6) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.0 * t)
    sig = np.sin(2 * np.pi * 110 * vib * t) + 0.55 * np.sin(2 * np.pi * 164.8 * t)
    sig += 0.25 * np.sin(2 * np.pi * 220 * t)
    env = np.minimum(t / 0.35, 1.0) * np.minimum((seconds - t) / 0.8, 1.0)
    return sig * env * 0.42


def bell(seconds: float = 1.4) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    sig = np.zeros_like(t)
    for ratio, amp in [(1.0, 0.5), (2.74, 0.28), (4.07, 0.14), (5.43, 0.08)]:
        sig += amp * np.sin(2 * np.pi * 640 * ratio * t) * np.exp(-t * (2.2 + ratio))
    return sig * 0.5


def gull_cry(seconds: float = 0.9) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    # Descending FM squeal, two syllables.
    sig = np.zeros_like(t)
    for start, dur in [(0.0, 0.35), (0.42, 0.45)]:
        i0 = int(start * SR)
        n = int(dur * SR)
        tt = np.arange(n) / SR
        f = 2100 * np.exp(-tt * 1.6) + 900
        phase = 2 * np.pi * np.cumsum(f) / SR
        env = np.sin(np.pi * tt / dur) ** 1.5
        sig[i0:i0 + n] += np.sin(phase) * env
    return sig * 0.4


if __name__ == "__main__":
    write_wav("wind_loop.wav", wind_loop())
    write_wav("foghorn.wav", foghorn())
    write_wav("bell.wav", bell())
    write_wav("gull_cry.wav", gull_cry())

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


class AudioConversionError(ValueError):
    pass


def write_pcm16_wav(path: Path, pcm: bytes, *, sample_rate_hz: int, channels: int) -> None:
    if sample_rate_hz <= 0:
        raise AudioConversionError("sample_rate_hz must be positive.")
    if channels <= 0:
        raise AudioConversionError("channels must be positive.")
    frame_size = channels * 2
    if len(pcm) % frame_size:
        raise AudioConversionError("PCM payload is not aligned to 16-bit channel frames.")

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm)


def read_wav_as_pcm16_mono(path: Path, *, target_sample_rate_hz: int) -> bytes:
    if target_sample_rate_hz <= 0:
        raise AudioConversionError("target_sample_rate_hz must be positive.")

    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            source_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (OSError, wave.Error) as exc:
        raise AudioConversionError(f"Invalid WAV file: {exc}") from exc

    if channels <= 0 or source_rate <= 0:
        raise AudioConversionError("WAV file has an invalid channel count or sample rate.")
    if sample_width not in {1, 2, 3, 4}:
        raise AudioConversionError(f"Unsupported WAV sample width: {sample_width} bytes.")
    if not frames:
        return b""

    samples = _decode_pcm_frames(frames, channels=channels, sample_width=sample_width)
    if source_rate != target_sample_rate_hz:
        samples = _resample_linear(samples, source_rate=source_rate, target_rate=target_sample_rate_hz)
    return _encode_pcm16(samples)


def trim_pcm16_silence(
    pcm: bytes,
    *,
    sample_rate_hz: int,
    channels: int,
    window_ms: int = 20,
    margin_ms: int = 160,
    min_threshold: int = 220,
) -> bytes:
    if sample_rate_hz <= 0:
        raise AudioConversionError("sample_rate_hz must be positive.")
    if channels <= 0:
        raise AudioConversionError("channels must be positive.")
    frame_size = channels * 2
    if len(pcm) % frame_size:
        raise AudioConversionError("PCM payload is not aligned to 16-bit channel frames.")
    if not pcm:
        return b""

    total_frames = len(pcm) // frame_size
    window_frames = max(1, sample_rate_hz * max(1, window_ms) // 1000)
    magnitudes: list[tuple[int, int, float]] = []
    for start in range(0, total_frames, window_frames):
        end = min(total_frames, start + window_frames)
        magnitudes.append((start, end, _pcm_window_magnitude(pcm, start, end, channels=channels)))

    peak = max((magnitude for _, _, magnitude in magnitudes), default=0.0)
    if peak < min_threshold:
        return b""
    sorted_magnitudes = sorted(magnitude for _, _, magnitude in magnitudes)
    floor_index = min(len(sorted_magnitudes) - 1, max(0, len(sorted_magnitudes) // 5))
    noise_floor = sorted_magnitudes[floor_index] if sorted_magnitudes else 0.0
    adaptive_threshold = min(peak * 0.35, noise_floor * 2.5 + 80.0)
    threshold = max(float(min_threshold), adaptive_threshold)

    active = [(start, end) for start, end, magnitude in magnitudes if magnitude >= threshold]
    if not active:
        return b""

    margin_frames = sample_rate_hz * max(0, margin_ms) // 1000
    start_frame = max(0, active[0][0] - margin_frames)
    end_frame = min(total_frames, active[-1][1] + margin_frames)
    return pcm[start_frame * frame_size : end_frame * frame_size]


def _pcm_window_magnitude(pcm: bytes, start_frame: int, end_frame: int, *, channels: int) -> float:
    if end_frame <= start_frame:
        return 0.0
    frame_size = channels * 2
    total = 0
    count = 0
    for frame in range(start_frame, end_frame):
        offset = frame * frame_size
        for channel in range(channels):
            raw = pcm[offset + channel * 2 : offset + channel * 2 + 2]
            total += abs(int.from_bytes(raw, "little", signed=True))
            count += 1
    return total / max(1, count)


def _decode_pcm_frames(data: bytes, *, channels: int, sample_width: int) -> list[int]:
    frame_width = channels * sample_width
    if len(data) % frame_width:
        raise AudioConversionError("WAV data is not aligned to complete frames.")

    mono: list[int] = []
    for frame_offset in range(0, len(data), frame_width):
        total = 0
        for channel in range(channels):
            offset = frame_offset + channel * sample_width
            total += _decode_sample(data[offset : offset + sample_width], sample_width)
        mono.append(_clamp_int16(round(total / channels)))
    return mono


def _decode_sample(raw: bytes, sample_width: int) -> int:
    if sample_width == 1:
        return (raw[0] - 128) << 8
    if sample_width == 2:
        return int.from_bytes(raw, "little", signed=True)
    if sample_width == 3:
        sign = b"\xff" if raw[2] & 0x80 else b"\x00"
        return int.from_bytes(raw + sign, "little", signed=True) >> 8
    return int.from_bytes(raw, "little", signed=True) >> 16


def _resample_linear(samples: list[int], *, source_rate: int, target_rate: int) -> list[int]:
    if not samples or source_rate == target_rate:
        return samples
    target_count = max(1, int(round(len(samples) * target_rate / source_rate)))
    if target_count == 1:
        return [samples[0]]

    ratio = source_rate / target_rate
    output: list[int] = []
    for index in range(target_count):
        source_position = index * ratio
        lower_index = min(len(samples) - 1, int(math.floor(source_position)))
        upper_index = min(len(samples) - 1, lower_index + 1)
        fraction = source_position - lower_index
        interpolated = samples[lower_index] + (samples[upper_index] - samples[lower_index]) * fraction
        output.append(_clamp_int16(round(interpolated)))
    return output


def _encode_pcm16(samples: list[int]) -> bytes:
    output = bytearray(len(samples) * 2)
    for index, sample in enumerate(samples):
        struct.pack_into("<h", output, index * 2, _clamp_int16(sample))
    return bytes(output)


def _clamp_int16(value: int) -> int:
    return max(-32768, min(32767, value))

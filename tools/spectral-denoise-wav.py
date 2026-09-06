#!/usr/bin/env python3
import argparse
import cmath
import json
import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 16000
FFT_SIZE = 512
HOP_SIZE = 128


def read_mono(path: Path) -> list[float]:
    with wave.open(str(path), "rb") as wav:
        actual = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype())
        if actual != (1, 2, SAMPLE_RATE, "NONE"):
            raise ValueError(f"unexpected format for {path}: {actual}")
        return [sample[0] for sample in struct.iter_unpack("<h", wav.readframes(wav.getnframes()))]


def write_mono(path: Path, samples: list[float]) -> tuple[int, int]:
    clipped = 0
    encoded = bytearray()
    for sample in samples:
        rounded = int(round(sample))
        if rounded > 32767:
            rounded = 32767
            clipped += 1
        elif rounded < -32768:
            rounded = -32768
            clipped += 1
        encoded.extend(struct.pack("<h", rounded))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(encoded)
    return len(samples), clipped


def fft(values: list[complex], inverse: bool = False) -> list[complex]:
    size = len(values)
    if size == 1:
        return values[:]
    if size & (size - 1):
        raise ValueError("fft_size_must_be_power_of_two")
    output = values[:]
    target = 0
    for source in range(1, size):
        bit = size >> 1
        while target & bit:
            target ^= bit
            bit >>= 1
        target ^= bit
        if source < target:
            output[source], output[target] = output[target], output[source]
    length = 2
    sign = 1.0 if inverse else -1.0
    while length <= size:
        root = cmath.exp(sign * 2j * math.pi / length)
        for start in range(0, size, length):
            factor = 1.0 + 0.0j
            half = length // 2
            for offset in range(half):
                even = output[start + offset]
                odd = output[start + offset + half] * factor
                output[start + offset] = even + odd
                output[start + offset + half] = even - odd
                factor *= root
        length *= 2
    if inverse:
        output = [value / size for value in output]
    return output


def high_pass(samples: list[float], coefficient: float = 0.995) -> list[float]:
    output = []
    previous_input = 0.0
    previous_output = 0.0
    for sample in samples:
        filtered = sample - previous_input + coefficient * previous_output
        output.append(filtered)
        previous_input = sample
        previous_output = filtered
    return output


def window() -> list[float]:
    return [math.sqrt(0.5 - 0.5 * math.cos(2.0 * math.pi * index / FFT_SIZE))
            for index in range(FFT_SIZE)]


def frames(samples: list[float], analysis_window: list[float]):
    padded = [0.0] * (FFT_SIZE // 2) + samples + [0.0] * FFT_SIZE
    for offset in range(0, len(padded) - FFT_SIZE + 1, HOP_SIZE):
        yield offset, [complex(padded[offset + index] * analysis_window[index], 0.0)
                       for index in range(FFT_SIZE)]


def noise_profile(noise_samples: list[float], analysis_window: list[float]) -> list[float]:
    accumulated = [0.0] * FFT_SIZE
    count = 0
    for _, frame in frames(high_pass(noise_samples), analysis_window):
        spectrum = fft(frame)
        for index, value in enumerate(spectrum):
            accumulated[index] += value.real * value.real + value.imag * value.imag
        count += 1
    if count == 0:
        raise ValueError("noise_sample_too_short")
    return [value / count for value in accumulated]


def denoise(samples: list[float], noise_power: list[float], alpha: float,
            floor_gain: float) -> list[float]:
    analysis_window = window()
    filtered = high_pass(samples)
    padded_length = FFT_SIZE // 2 + len(filtered) + FFT_SIZE
    output = [0.0] * padded_length
    normalization = [0.0] * padded_length
    floor_power_ratio = floor_gain * floor_gain
    for offset, frame in frames(filtered, analysis_window):
        spectrum = fft(frame)
        processed = []
        for index, value in enumerate(spectrum):
            power = value.real * value.real + value.imag * value.imag
            if power == 0.0:
                processed.append(0.0j)
                continue
            residual = max(power - alpha * noise_power[index], floor_power_ratio * power)
            processed.append(value * math.sqrt(residual / power))
        reconstructed = fft(processed, inverse=True)
        for index, value in enumerate(reconstructed):
            weight = analysis_window[index]
            output[offset + index] += value.real * weight
            normalization[offset + index] += weight * weight
    start = FFT_SIZE // 2
    result = []
    for index in range(start, start + len(filtered)):
        divisor = normalization[index]
        result.append(output[index] / divisor if divisor > 1e-12 else 0.0)
    return result


def rms(samples: list[float]) -> float:
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0.0


def normalized_correlation(reference: list[float], processed: list[float]) -> float | None:
    if not reference or len(reference) != len(processed):
        return None
    reference_mean = sum(reference) / len(reference)
    processed_mean = sum(processed) / len(processed)
    covariance = sum((a - reference_mean) * (b - processed_mean)
                     for a, b in zip(reference, processed))
    reference_energy = sum((a - reference_mean) ** 2 for a in reference)
    processed_energy = sum((b - processed_mean) ** 2 for b in processed)
    denominator = math.sqrt(reference_energy * processed_energy)
    return covariance / denominator if denominator else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("noise_wav", type=Path)
    parser.add_argument("input_wav", type=Path)
    parser.add_argument("output_wav", type=Path)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--floor-gain", type=float, required=True)
    parser.add_argument("--output-gain-db", type=float, default=18.0)
    args = parser.parse_args()
    if args.alpha < 0.0 or not 0.0 < args.floor_gain <= 1.0:
        raise ValueError("invalid_denoise_parameters")

    noise_samples = read_mono(args.noise_wav)
    input_samples = read_mono(args.input_wav)
    analysis_window = window()
    profile = noise_profile(noise_samples, analysis_window)
    processed = denoise(input_samples, profile, args.alpha, args.floor_gain)
    fixed_gain = 10.0 ** (args.output_gain_db / 20.0)
    gained = [sample * fixed_gain for sample in processed]
    frames_written, clipped = write_mono(args.output_wav, gained)
    print(json.dumps({
        "algorithm": "high_pass_plus_stft_spectral_subtraction",
        "fft_size": FFT_SIZE,
        "hop_size": HOP_SIZE,
        "sample_rate_hz": SAMPLE_RATE,
        "alpha": args.alpha,
        "floor_gain": args.floor_gain,
        "output_gain_db": args.output_gain_db,
        "input_file": args.input_wav.name,
        "noise_file": args.noise_wav.name,
        "output_file": args.output_wav.name,
        "frames_written": frames_written,
        "clipped_samples": clipped,
        "input_rms": rms(input_samples),
        "processed_pre_gain_rms": rms(processed),
        "waveform_correlation_pre_gain": normalized_correlation(input_samples, processed),
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

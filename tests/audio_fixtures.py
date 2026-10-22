"""Playable silence for seeking checks; no classroom recordings or services."""

import io
import wave


def silent_wav(duration=6, rate=8000):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b"\0\0" * int(duration * rate))
    return output.getvalue()

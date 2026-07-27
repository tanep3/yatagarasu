# Yatagarasu Wake Word Model

## `nee_yatagarasu.onnx`

- Wake phrase: 「ねぇ、ヤタガラス」
- Author: Tane Channel Technology
- License: Apache License 2.0
- SHA-256: `0a2926bf00ff15c24e6ed0cf09e60e5550339439db5103335a517d9d0a70feb8`
- Input: `embeddings`, `[batch, 16, 96]`, `float32`
- Output: `score`, `[batch, 1]`, `float32`

The model was trained by Tane Channel Technology with the official
LiveKit WakeWord VoxCPM configuration. It uses synthesized training data and
does not include additional recorded speech.

Training and inference components:

- [LiveKit WakeWord](https://github.com/livekit/livekit-wakeword), Apache-2.0
- [VoxCPM](https://github.com/OpenBMB/VoxCPM), Apache-2.0

The model is distributed under the Apache License 2.0 included in this
directory.

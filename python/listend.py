import subprocess
import numpy as np
import openwakeword
from openwakeword.model import Model
from faster_whisper import WhisperModel
import yaml
import time

# config.yaml読み込み（RTSP_URL追加）
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

RTSP_URL = config['rtsp_url']  # "rtsp://192.168.x.x:8554/tapo_tc70" など

# ffmpegプロセス起動（音声のみ、16kHzモノラル）
ffmpeg_proc = subprocess.Popen([
    'ffmpeg', '-i', RTSP_URL,
    '-f', 's16le', '-ac', '1', '-ar', '16000', '-vn', '-'
], stdout=subprocess.PIPE, bufsize=1024)

oww = Model(wakeword_models=[config['wake_word']], vad_threshold=config['vad_threshold'])
whisper_model = WhisperModel("base", device="cpu")

ON_STATE = False
last_speech_time = time.time()
audio_buffer = bytearray()

print("Listening from TC70 RTSP...")
while True:
    chunk = ffmpeg_proc.stdout.read(1280 * 2)  # 16bit = 2byte/sample
    if not chunk:
        break
    pcm = np.frombuffer(chunk, dtype=np.int16)

    prediction = oww.predict(pcm)
    vad_score = prediction.get('vad_score', 0)

    if vad_score > config['vad_threshold']:
        last_speech_time = time.time()
        if ON_STATE:
            audio_buffer.extend(chunk)  # 蓄積

    # wake/sleep検知...
    # (前回サンプル同様)

    if time.time() - last_speech_time > config['silence_timeout'] and ON_STATE:
        ON_STATE = False
        # faster-whisperでバッファ処理
        audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = whisper_model.transcribe(audio_np, beam_size=5)
        transcription = ' '.join([s.text for s in segments])
        print(f"Transcription: {transcription}")
        subprocess.call([config['launch_app'], transcription])
        audio_buffer.clear()
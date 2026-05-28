# Project Luma V0

English README: [README.md](README.md)

Project Luma 是一个基于 CoreS3 的桌面 AI 宠物原型。系统分为：

- **Brain**：Python FastAPI 服务，负责语音循环、WebSocket 协议、LLM 决策层、记忆存储、本地 STT/TTS 适配器和网页控制台。
- **CoreS3 头部**：负责表情播放、触摸唤醒、麦克风上传、扬声器播放和设备侧安全处理。
- **浏览器模拟器**：开发用头部模拟器，连接同一个 `/ws/head` 端点。

## 快速启动

```bash
python3 -m pip install -r requirements.txt
python3 -m luma.brain
```

网页控制台和浏览器模拟器地址：`http://127.0.0.1:8787`。

Brain 会从工作目录加载 `.env.local` 和 `.env`。`.env.local` 已被 git 忽略。

`.env.local` 示例：

```text
LUMA_STT_PROVIDER=local_sherpa
LUMA_TTS_PROVIDER=local_sherpa
LUMA_SHERPA_ROOT=./models/sherpa

LUMA_SHERPA_TTS_MODEL_DIR=./models/sherpa/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia
LUMA_SHERPA_TTS_VOCODER=./models/sherpa/vocos_24khz.onnx
LUMA_TTS_REFERENCE_AUDIO=./models/sherpa/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/test_wavs/leijun-1.wav
LUMA_TTS_REFERENCE_TEXT=参考音频对应文本

LUMA_LLM_BASE_URL=https://api.openai.com/v1
LUMA_LLM_MODEL=gpt-4o-mini
LUMA_LLM_API_KEY=...
LUMA_LLM_JSON_MODE=1

LUMA_VOICE_SAMPLE_RATE_HZ=24000
LUMA_VOICE_CHUNK_MS=40
LUMA_VOICE_MAX_RECORD_SECONDS=8
```

## 本地语音

本地 STT 使用 `sherpa-onnx`，本地 TTS 使用 `sherpa-onnx-offline-tts`。运行时不会自动下载模型，也不会静默回退到云端语音 provider。

ASR/runtime 目录示例：

```text
models/sherpa/
  sherpa-onnx-v1.13.0-osx-universal2-shared/bin/sherpa-onnx
  sherpa-onnx-v1.13.0-osx-universal2-shared/bin/sherpa-onnx-offline-tts
  sherpa-onnx/
    tokens.txt
    encoder.int8.onnx
    decoder.int8.onnx
```

ZipVoice TTS 目录示例：

```text
models/sherpa/
  sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/
    encoder.int8.onnx
    decoder.int8.onnx
    tokens.txt
    lexicon.txt
    espeak-ng-data/
    test_wavs/leijun-1.wav
  vocos_24khz.onnx
```

TTS 生成音频会被转换为 CoreS3 播放格式：24 kHz、单声道、PCM16。

## Brain 行为

实时 LLM 主决策只输出两类信息：

- 要说出口的短文本；
- Luma 要显示的表情情绪。

表情表示 Luma 自身的显示状态，不表示用户的情绪。LLM 只从可用表情目录中选择 emotion 名称；播放时长由 Brain 根据本地 qgif/gif 资源计算。

记忆反思由独立异步 LLM 调用在主回复落库后执行。记忆分为偏好、习惯、短期事件、情绪模式、行为程序记忆和关系上下文。短期记忆可以过期，长期记忆用于稳定且对互动有价值的信息。凭据、敏感数据和通用知识会被拒绝。

## 语音协议

`/ws/head?device_id=luma-core-s3&role=device` 同时承载 JSON 控制消息和二进制 PCM 帧。

CoreS3 发给 Brain：

```json
{"type":"wake_detected","wake_phrase":"你好 Luma","source":"touch"}
{"type":"audio_begin","sample_rate_hz":24000,"channels":1,"encoding":"pcm_s16le"}
```

`audio_begin` 后的二进制帧是 24 kHz、16-bit、单声道 PCM 分片。CoreS3 用以下消息结束本轮录音：

```json
{"type":"audio_end"}
{"type":"playback_done"}
```

Brain 发给 CoreS3：

```json
{"type":"start_listening","sample_rate_hz":24000,"channels":1,"encoding":"pcm_s16le"}
{"type":"play_audio_begin","sample_rate_hz":24000,"channels":1,"encoding":"pcm_s16le","bytes":12345}
```

`play_audio_begin` 后的二进制帧是回复音频 PCM。Brain 用以下消息结束播放：

```json
{"type":"play_audio_end"}
```

## HTTP API

```bash
curl -X POST http://127.0.0.1:8787/api/voice/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"你回来了。"}'

curl -X POST http://127.0.0.1:8787/api/voice/wake \
  -H 'Content-Type: application/json' \
  -d '{"source":"console","wake_phrase":"你好 Luma"}'

curl http://127.0.0.1:8787/api/conversation
curl http://127.0.0.1:8787/api/memories
curl http://127.0.0.1:8787/api/debug/prompt
```

`/api/command` 可用于表情、停止和兼容命令。由于舵机未连接，`move_head` 在此构建中禁用。

## 固件

CoreS3 固件位于 `firmware/core_s3/`。

固件能力：

- 连接 `/ws/head` 的 WebSocket 客户端。
- LVGL 表情显示。
- 运行时流式 qgif 表情播放，按 320x240 contain 缩放。
- 触摸唤醒。
- 24 kHz PCM16 单声道麦克风数据上传，分片大小 40 ms。
- 播放 Brain 返回的 24 kHz PCM16 单声道音频。
- 基于 qgif 资源元数据的语义表情目录。

默认 Brain 地址：

```text
ws://192.168.1.100:8787/ws/head?device_id=luma-core-s3&role=device
```

固件会从 NVS namespace `luma`、key `brain_ws_url` 读取覆盖地址。

## 测试

```bash
python3 -m unittest discover -s tests
```

安装开发依赖后：

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

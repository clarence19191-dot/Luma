# Project Luma V0

English README: [README.md](README.md)

Project Luma V0 是一个以 CoreS3 为头部终端的语音循环机器人原型：

- CoreS3 头部：表情显示、唤醒/触摸触发、麦克风 PCM 采集、扬声器 PCM 播放和设备安全控制。
- Luma 大脑：Python FastAPI、WebSocket、SQLite 日志、语音会话运行时、桌宠人格、对话边界、关系记忆、本地 STT/TTS、OpenAI-compatible LLM provider 和网页控制台。
- 浏览器模拟器：开发用头部设备模拟器，连接同一个 `/ws/head` 端点。

开发阶段由 Mac 运行 Brain。未来可将同一个 Brain 进程迁移到 Raspberry Pi，而不改变 CoreS3 通信协议。

## 运行 Brain

```bash
python3 -m pip install -r requirements.txt
python3 -m luma.brain
```

打开 `http://127.0.0.1:8787`。页面会自动启动浏览器模拟头部设备。

STT 和 TTS 默认走本地离线流程。语音循环不再需要 `OPENAI_API_KEY`。LLM 层仍是 OpenAI-compatible，可指向 OpenAI、DeepSeek 或其他兼容端点。

`.env.local` 示例：

```text
LUMA_STT_PROVIDER=local_sherpa
LUMA_TTS_PROVIDER=local_sherpa
LUMA_SHERPA_ROOT=/Users/winmer/files/Starest/Project Luma/models/sherpa

LUMA_SHERPA_TTS_MODEL_DIR=/Users/winmer/files/Starest/Project Luma/models/sherpa/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia
LUMA_SHERPA_TTS_VOCODER=/Users/winmer/files/Starest/Project Luma/models/sherpa/vocos_24khz.onnx
LUMA_TTS_REFERENCE_AUDIO=/Users/winmer/files/Starest/Project Luma/models/sherpa/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia/test_wavs/leijun-1.wav
LUMA_TTS_REFERENCE_TEXT=参考音频对应文本

LUMA_LLM_BASE_URL=https://api.openai.com/v1
LUMA_LLM_MODEL=gpt-4o-mini
LUMA_LLM_API_KEY=...
LUMA_LLM_JSON_MODE=1

LUMA_VOICE_SAMPLE_RATE_HZ=24000
LUMA_VOICE_CHUNK_MS=40
LUMA_VOICE_MAX_RECORD_SECONDS=8
```

Brain 会自动加载本地 `.env.local`，该文件被 git 忽略。

## 本地语音模型

Brain 使用 `sherpa-onnx` 做本地语音转文字，使用 `sherpa-onnx-offline-tts` 做本地文字转语音。运行时不会下载模型，也不会静默回退到云端 STT/TTS。

本地模型和 runtime 目录被 git 忽略。请将语音资源放置或复制到：

```text
/Users/winmer/files/Starest/Project Luma/models/sherpa
```

runtime 和 ASR 需要的文件：

```text
models/sherpa/
  sherpa-onnx-v1.13.0-osx-universal2-shared/bin/sherpa-onnx
  sherpa-onnx-v1.13.0-osx-universal2-shared/bin/sherpa-onnx-offline-tts
  sherpa-onnx/
    tokens.txt
    encoder.int8.onnx
    decoder.int8.onnx
```

TTS 默认按 ZipVoice 中英模型配置。模型文件请放在 git 外，例如被忽略的 `models/` 目录下，并配置 `LUMA_SHERPA_TTS_MODEL_DIR`。

ZipVoice 需要的文件：

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

`LUMA_SHERPA_TTS_VOCODER`、`LUMA_TTS_REFERENCE_AUDIO` 和 `LUMA_TTS_REFERENCE_TEXT` 需要指向声码器和参考音色资源。生成的 WAV 会被转换为 CoreS3 播放格式：24 kHz、单声道、PCM16。

如需调试旧云端 provider，必须显式设置：

```text
LUMA_STT_PROVIDER=openai
LUMA_TTS_PROVIDER=openai
OPENAI_API_KEY=...
```

## 桌宠大脑

LLM 层被限制为桌宠人格。它输出经过校验的 JSON，包括：

- 短回复文本，
- 语气，
- 表情情绪，
- 宠物行为标签，
- 仅记录的行动意图，
- 谨慎的关系记忆候选，
- 安全/边界元数据。

Brain 会判断一次发言是延续当前对话、恢复近期对话，还是开始新对话。长时间间隔后的唤醒默认按重新见面处理，不强行带入旧任务上下文。

关系记忆是 SQLite 行记录，不是知识库。它只保存稳定偏好、讨厌的互动方式、名字、宠物、习惯和情绪照护线索。一次性任务、工作细节、凭据、敏感数据和通用知识会被拒绝。

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

`play_audio_begin` 后的二进制帧是给 CoreS3 扬声器播放的 PCM 回复音频。Brain 用以下消息结束播放：

```json
{"type":"play_audio_end"}
```

## HTTP 接口

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

旧的 `/api/command` 仍保留给表情、停止和兼容命令使用。由于舵机尚未连接，`move_head` 在 V0 中被有意禁用。

## 固件

Luma 的 CoreS3 固件位于 `firmware/core_s3/`。`StackChan/` 仅作为本地参考 checkout 保留，并被 git 忽略。

当前 V0 固件行为：

- 连接 `/ws/head` 的文本和二进制 WebSocket 客户端。
- LVGL 脸部表情显示。
- 运行时流式 qgif 表情播放，并按 320x240 contain 缩放。
- 触摸兜底唤醒。
- 24 kHz PCM16 单声道麦克风数据，按 40 ms 分片上传。
- 播放 Brain 返回的 24 kHz PCM16 单声道音频。
- 扩展语义表情目录及 qgif 资源元数据。
- 当前构建不初始化 Servo2/PCA9685。

Brain 按需流式下发表情 qgif。CoreS3 只在 RAM 中保留当前 qgif，将每个 1-bit 帧缩放到 320x240 RGB565 buffer，再通过 LVGL 显示。如果没有可用流式 qgif，固件会回退到 LVGL StackChan 脸。

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

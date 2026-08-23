# ⚡ llama-server-dashboard

> A lightweight, zero-dependency, real-time terminal dashboard and monitor for `llama-server` (`llama.cpp`) with live **GPU VRAM partitioning**, **CPU RAM offload detection**, token throughput counters, and formatted event logging.

---

## 📸 ASCII Preview

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    ⚡ QWEN 2.5 CODER 7B (LLAMA-SERVER DASHBOARD) ⚡                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Server Status:    ● READY (IDLE)                       Uptime: 08:24                  │
│  Model:            Qwen 2.5 Coder 7B Instruct (Q4_K_M)                                 │
│  API Endpoint:     http://127.0.0.1:8080/v1                                            │
│  Configuration:    65,536 tokens  |  Cache: Q8_0  |  Flash-Attn: ON                     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  📊 VRAM & SYSTEM RAM METRICS:                                                         │
│  ├─ 🎮 GPU Memory (VRAM):   [██████████████████░░]  7.80 / 8.0 GB (97.5%)             │
│     └─ ■ Model: 5.56 GB  |  ■ Windows/System: 2.24 GB                                │
│  ├─ 🧠 CPU RAM Spillover:   0.00 GB  [✅ 100% IN VRAM, NO OFFLOAD]                    │
│  ├─ ⚙️  Server RAM (llama):  ~5.24 GB (Vulkan host buffer)                              │
│  └─ 🐍 Dashboard RAM (Py):  30.4 MB (lightweight UI monitor)                         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  📈 CONTEXT ACTIVITY & THROUGHPUT:                                                     │
│  ├─ 🗂  Context Occupied:    [███░░░░░░░░░░░░░░░]  12,291 / 65,536 (18.8%)             │
│  └─ ⚡ Response Speed:      Generation: 43.8 tok/s  |  Prompt: 146.2 tok/s              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  📜 LIVE SERVER EVENT LOGS:                                                            │
│  > HTTP server listening on http://127.0.0.1:8080                                      │
│  > slot 0 | task 359 | prompt processing: 146.19 tokens per second                     │
│  > slot 0 | task 359 | n_gen = 280, tg = 43.85 t/s                                     │
│  > slot 0 | all slots are idle                                                         │
└────────────────────────────────────────────────────────────────────────────────────────┘
 [Press 'Q', 'Esc' or 'Ctrl+C' to cleanly stop the server]
```

---

## ✨ Key Features

* 🎮 **Stacked Multi-Color VRAM Gauge:** Visually distinguishes memory allocation:
  * 🟦 **Cyan:** Memory occupied strictly by the Model weights and active KV-Cache.
  * 🟨 **Yellow:** Memory consumed by Windows DWM, Desktop, browsers, and background apps.
  * ░ **Gray:** Remaining unallocated GPU VRAM headroom.
* 🧠 **Zero-Spillover Detection:** Monitors whether all layers are running 100% in VRAM or spilling into system RAM.
* ⚙️ **Dual-Process RAM Tracking:** Separately displays `llama-server` process footprint (e.g. Vulkan host-visible staging buffer) and the dashboard's own tiny Python runtime (~30 MB).
* ⚡ **Live Throughput Counters:** Real-time token generation speed (`tg tok/s`) and prompt evaluation speed (`prompt tok/s`).
* 🛑 **Bulletproof Clean Exit:** Uses Windows Native Console Control Handlers (`SetConsoleCtrlHandler`) and non-blocking key polling — gracefully terminates both the dashboard and `llama-server.exe` on `Q`, `Esc`, or `Ctrl+C`.
* 📦 **Universal GGUF Compatibility:** Works out of the box with any model (Qwen, DeepSeek, Llama, Mistral, Gemma, etc.) by passing the model path as a CLI argument.
* 🪶 **Zero Dependencies:** Pure Python 3 (Standard library only: `ctypes`, `subprocess`, `urllib`, `re`, `msvcrt`). No `pip install` or external packages required.

---

## 🚀 Getting Started

### Prerequisites
* **OS:** Windows 10 / 11 (64-bit)
* **Python:** Python 3.8+
* **Backend:** `llama-server.exe` from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)
* Any GGUF model file (e.g. `qwen2.5-coder-7b-instruct-q4_k_m.gguf`)

### Usage

#### 1. Quick Launch (Default Model)
```cmd
python dashboard.py
```

#### 2. Launch with Custom Parameters
```cmd
python dashboard.py path/to/model.gguf <context_length> <port>
```

Example:
```cmd
python dashboard.py models/DeepSeek-R1-Distill-Qwen-7B-Q8_0.gguf 131072 8080
```

* `Arg 1`: Path to GGUF model (default: `qwen2.5-coder-7b-instruct-q4_k_m.gguf`)
* `Arg 2`: Context window size in tokens (default: `65536`)
* `Arg 3`: HTTP API port (default: `8080`)

---

## 🛠 One-Click Batch Launcher (`start_qwen_7b.bat`)

Place `start_qwen_7b.bat` in your model directory for instant double-click startup:

```bat
@echo off
title Qwen 2.5 Coder 7B - Live Dashboard
cd /d "%~dp0"

python dashboard.py
pause
```

---

## 📄 License

MIT License. Open source and free for personal and commercial use.

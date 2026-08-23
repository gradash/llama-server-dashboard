# ⚡ LLAMA-SERVER LIVE TERMINAL DASHBOARD

A lightweight, zero-dependency, real-time visual terminal dashboard and monitor for `llama-server` (`llama.cpp`) with detailed **GPU VRAM** and **RAM offload / staging** metrics, token throughput counters, and live event logging.

---

## 📸 Preview (ASCII Art Representation)

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    ⚡ QWEN 2.5 CODER 7B (LLAMA-SERVER DASHBOARD) ⚡                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  Статус сервера:   ● ГОТОВ К РАБОТЕ (IDLE)              Аптайм: 05:42                  │
│  Модель:           Qwen 2.5 Coder 7B Instruct (Q4_K_M)                                 │
│  Эндпоинт API:     http://127.0.0.1:8080/v1                                            │
│  Конфигурация:     65,536 токенов  |  Кеш: Q8_0  |  Flash-Attn: ON                     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  📊 ВИДЕОПАМЯТЬ И ОЗУ (VRAM & RAM МЕТРИКИ):                                            │
│  ├─ 🎮 Видеопамять (VRAM):   [██████████████████░░]  7.80 / 8.0 GB (97.5%)             │
│     └─ ■ Модель: 5.56 GB  |  ■ Windows/Система: 2.24 GB                                │
│  ├─ 🧠 Выгрузка в RAM (CPU): 0.00 GB  [✅ 100% В VRAM, БЕЗ ВЫГРУЗОК]                  │
│  ├─ ⚙️  ОЗУ сервера (llama):  ~5.24 GB (хост-буфер Vulkan)                              │
│  └─ 🐍 ОЗУ дашборда (Python): 30.4 MB (легковесный UI монитор)                         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  📈 АКТИВНОСТЬ КОНТЕКСТА И СКОРОСТЬ:                                                   │
│  ├─ 🗂  Занято контекста:    [███░░░░░░░░░░░░░░░]  12,291 / 65,536 (18.8%)             │
│  └─ ⚡ Скорость ответа:     Генерация: 43.8 tok/s  |  Промпт: 146.2 tok/s              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  📜 ЖИВОЙ ЛОГ СОБЫТИЙ СЕРВЕРА:                                                         │
│  > HTTP server listening on http://127.0.0.1:8080                                      │
│  > slot 0 | task 359 | prompt processing: 146.19 tokens per second                     │
│  > slot 0 | task 359 | n_gen = 280, tg = 43.85 t/s                                     │
│  > slot 0 | all slots are idle                                                         │
└────────────────────────────────────────────────────────────────────────────────────────┘
 [Нажмите 'Q', 'Esc' или 'Ctrl+C' для остановки сервера]
```

---

## ✨ Features / Возможности

* 🎮 **Stacked Multi-Color VRAM Bar:** Visualizes exact VRAM partition — 🟦 **Model & KV Cache** vs 🟨 **Windows OS / Browser** vs ░ **Free VRAM**.
* 🧠 **Zero-Spillover Detection:** Monitors whether layers are 100% in VRAM or offloaded to system CPU RAM.
* ⚙️ **Dual RAM Metrics:** Separately tracks `llama-server` process memory (Vulkan host-visible staging buffer) and the lightweight Python monitor footprint (~30 MB).
* ⚡ **Live Throughput Parsing:** Real-time token generation speed (`tg tok/s`) and prompt evaluation speed (`prompt tok/s`).
* 🛑 **Bulletproof Termination:** Native Windows console control handlers (`SetConsoleCtrlHandler`) and direct key listener — instantly terminates child server processes on `Q`, `Esc`, or `Ctrl+C`.
* 📦 **Universal Model Support:** Launch any `.gguf` file by passing it as a CLI argument.
* 🪶 **Zero Dependencies:** Pure Python 3 (standard library only: `ctypes`, `subprocess`, `urllib`, `re`). No `pip install` required!

---

## 🚀 Quick Start / Быстрый старт

### 1. Requirements
* Windows 10 / 11 (64-bit)
* Python 3.8+
* `llama-server.exe` from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)
* Any GGUF model (e.g. `Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf`)

### 2. Usage / Запуск

#### Default launch:
```cmd
python dashboard.py
```

#### Launch with custom model, context, or port:
```cmd
python dashboard.py path/to/model.gguf 65536 8080
```

* Argument 1: Model file path (default: `qwen2.5-coder-7b-instruct-q4_k_m.gguf`)
* Argument 2: Context window size (default: `65536`)
* Argument 3: Port (default: `8080`)

---

## 🛠 One-Click Batch Launcher (`start_qwen_7b.bat`)

```bat
@echo off
title Qwen 2.5 Coder 7B - Live Dashboard
cd /d "%~dp0"

python dashboard.py
pause
```

---

## 📄 License

MIT License. Feel free to use, modify, and distribute!

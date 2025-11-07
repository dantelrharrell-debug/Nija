# NIJA Trading Bot

⚡ **NIJA** is a live crypto trading bot built to execute automated trades via the Coinbase API. This README reflects the current working setup, deployment, and usage of the bot.

> "The Path of Struggle is Peace." — NIJA UGUMU AMANI™

---

## Current Working Setup

- **Deployment Platform:** Render  
- **Live Port:** 10000  
- **Primary URL:** [https://nija.onrender.com](https://nija.onrender.com)  
- **Worker Type:** `sync` (Gunicorn, 1 worker)  

### Example Logs from Live Deployment

[2025-11-07 02:57:27 +0000] Booting worker with pid: 58
127.0.0.1 - - [07/Nov/2025:02:57:28 +0000] “HEAD / HTTP/1.1” 200 0
127.0.0.1 - - [07/Nov/2025:02:57:38 +0000] “GET / HTTP/1.1” 200 22
Detected service running on port 10000
⚡ NIJA bot is LIVE! Real trades will execute.
Available at your primary URL https://nija.onrender.com

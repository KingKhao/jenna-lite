# Credits and third-party software

Jenna Lite is made by [Clinch Valley Digital](https://clinchvalleydigital.com) and released under the GNU GPL v3.

## Ideas and prompts

Several of her features grew out of prompts and ideas from [**hellotrillion.ai**](https://hellotrillion.ai): the
cosmic home-screen interface, cutting voice latency (speaking her first sentence while she's still writing),
knowing when a conversation is over, the voice-first phone app, prompt caching, and the desktop app wrapper.
Thank you.

## Software she uses

| Part | What for | License |
|---|---|---|
| [Ollama](https://ollama.com) | runs the AI model locally (installed separately) | MIT |
| [Qwen3](https://github.com/QwenLM/Qwen3) by Alibaba | her brain (downloaded through Ollama) | Apache 2.0 |
| [nomic-embed-text](https://ollama.com/library/nomic-embed-text) | recalling memories by meaning | Apache 2.0 |
| [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) via [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | her voice | Apache 2.0 / MIT |
| phonemizer, espeak-ng (pulled in by kokoro-onnx) | turning text into speech sounds | GPL v3 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | speech to text | MIT |
| [three.js](https://threejs.org) | the galaxy home screen (`pc/galaxy/three.module.min.js`) | MIT (see `pc/galaxy/THREE-LICENSE.txt`) |
| [ddgs](https://pypi.org/project/ddgs/), [trafilatura](https://github.com/adbar/trafilatura), [Playwright](https://playwright.dev) | web search and reading pages | MIT / Apache 2.0 / Apache 2.0 |
| [Open-Meteo](https://open-meteo.com) | weather (free API, no key) | CC BY 4.0 data |
| icalendar, recurring-ical-events, caldav | connected calendars | BSD 2-Clause / LGPL v3 / GPL v3 + Apache 2.0 |
| slack_sdk, requests-oauthlib | Slack and X connections | MIT / ISC |
| keyring, keyboard, sounddevice, soundfile, requests, numpy, cryptography, pywebpush, py-vapid, qrcode | the plumbing | MIT / BSD / Apache 2.0 / MPL 2.0 |
| [Tailscale](https://tailscale.com) | private phone access (optional, installed separately) | BSD 3-Clause client |

The star positions and magnitudes on the home screen come from public star catalogs (the Yale Bright Star Catalog
and Hipparcos values, rounded).

Each package keeps its own license. The GPL v3 parts are why Jenna Lite as a whole is GPL v3.

# Jenna Lite

A free, private AI assistant that runs on your own Windows PC. She talks, listens, remembers you, keeps your
reminders and goals, searches the web, and keeps everything she learns in a folder of notes you own: her Brain.
No account, no subscription, and nothing you say goes to an AI company. Her brain is an open model running on
your graphics card.

Made by [Clinch Valley Digital](https://clinchvalleydigital.com). Built with ideas and prompts from
[hellotrillion.ai](https://hellotrillion.ai).

## What she does

- **Talks and listens.** Tap the galaxy and just talk, hands-free; she answers out loud. Hold **F8** anywhere on
  the PC to talk without opening the app.
- **Remembers you.** Tell her things once ("I'm allergic to cats"). She asks a get-to-know-you question each
  morning, and her memories are plain notes you can read, edit or delete.
- **Keeps you on track.** Reminders, goals and a short morning check-in with your weather.
- **Looks things up.** Web search, web pages and the weather. She always names her source and says "I don't know"
  instead of guessing.
- **Has a Brain.** A folder of Markdown notes (it opens in [Obsidian](https://obsidian.md)). She searches it
  first, saves your notes and ideas there, and logs your conversations there.
- **Skills.** Reusable instructions such as /humanize, /summarize and /reply. Make your own in the Skills tab;
  they orbit her on the home screen.
- **Your phone, privately.** The same app on your phone through [Tailscale](https://tailscale.com) (free), and
  optionally on Telegram, from anywhere.
- **Connects to your apps** (the Connect tab, each walked through step by step):
  - Chat with her on **Telegram** or **Slack**, or use her app on your phone.
  - **Email:** Gmail, Yahoo, iCloud, AOL, Zoho, Fastmail or any IMAP mailbox. She reads and searches; she sends only after your Yes.
  - **Calendars:** Google, Outlook, Apple iCloud or any iCal link. Your appointments show on the Today tab and in her morning check-in.
  - **Notion:** search, read and add to the pages you share with her.
  - **Social:** Facebook Pages, Instagram (Business/Creator), Threads and X. She drafts and publishes after your Yes. These use your own
    free developer app; X bills you per post.
  - **Add-on: image & video creation.** A Connect card walks you through installing the free ComfyUI app (Z-Image Turbo pictures,
    FLUX.2 klein photo edits, Wan 2.2 video). It is a separate app; /imageprompt has her write the prompts.
  - Coming later (they need approved apps first): Outlook/Microsoft 365 email, Google Workspace email, TikTok, LinkedIn, YouTube, Pinterest.
- **Appointments.** Tell her "dentist Thursday at 2" and it's on the Today tab with a reminder 30 minutes before.
- **Your personality.** Pick a starting personality (warm friend, sharp professional, hype coach or calm
  companion), or write your own. Rename her too.

## What you need

- Windows 10 or 11.
- An NVIDIA graphics card with **8 GB or more** is recommended (12 GB+ runs the bigger, smarter model). It also
  runs without one, just slower.
- About **15 GB** of free disk space, and an internet connection for the first install.
- A microphone if you want to talk to her.

## Install

1. [Download Jenna-Lite.zip](https://github.com/KingKhao/jenna-lite/releases/latest/download/Jenna-Lite.zip), then unzip it
   somewhere permanent, for example `Documents\Jenna Lite` (right-click the zip > Extract All).
2. Double-click **Install Jenna Lite.cmd**. If Windows shows "Windows protected your PC", click **More info > Run anyway**
   (it's a plain script; you can read it first). It installs what's missing (Python, Ollama, FFmpeg), downloads her
   voice and a brain sized for your graphics card, and adds a **Jenna Lite** icon to your Desktop. The first run
   takes 10 to 30 minutes, mostly the model download.
3. Her setup screen opens. Answer a few questions (your name, hers, her personality, where her Brain lives),
   connect Telegram and your phone if you like, and start talking.

Running the installer again is safe: it repairs anything missing and never touches your notes or settings.

| Graphics memory | Model she uses | Download |
|---|---|---|
| 12 GB or more | qwen3:14b | ~9 GB |
| 8 GB or more | qwen3:8b | ~5 GB |
| Less, or no NVIDIA card | qwen3:4b | ~2.5 GB |

## Privacy

- Conversations, memories, notes and settings stay on your PC. The AI model runs locally through Ollama.
- What leaves the PC: web searches and pages she reads for you (DuckDuckGo and the sites themselves), weather
  lookups (Open-Meteo), and, if you set them up, Telegram messages and phone push notifications.
- Your Telegram bot token is stored in Windows Credential Manager, never in a file. Anything that looks like a
  password or key is scrubbed before it reaches her memory or your Brain.
- The app only listens on this PC. Phone access goes through your own private Tailscale network and only lets in
  your Tailscale account.
- Text from web pages is treated as information, never instructions. Opening an unfamiliar link after reading a
  page needs your Yes.
- Emergency stop: send `/pause` (in chat or Telegram) to turn off her tools and scheduled messages; `/resume` turns
  them back on.

## Everyday use

- **Desktop:** the Jenna Lite icon. She also starts in the background when you sign in, so reminders arrive even
  with the app closed.
- **Phone:** Menu > Phone setup, scan the QR code, then "Add to Home screen".
- **Telegram:** Menu > Telegram. Two minutes with @BotFather; the app walks you through it.
- **Commands:** /brief, /questions, /goals, /reminders, /skills, /voice, /pause, /resume, /help.

## Troubleshooting

- **Menu > Diagnostics** checks every part (model, voice, microphone, Brain folder, Telegram, phone) and says how to
  fix what's off.
- **Menu > Logs**, or `data\jenna.log` in this folder.
- She didn't start: open **Ollama** from the Start menu, then the Jenna Lite icon.
- To remove her: double-click **Uninstall Jenna Lite.cmd** (your Brain folder is kept), then delete this folder.

## For developers

```
.venv\Scripts\python.exe run_jenna.py           # supervisor + worker (what the Startup shortcut runs)
.venv\Scripts\python.exe tests\run_tests.py     # offline tests: no model, network or real keys needed
node pc\galaxy\galaxy-core.test.mjs             # the home screen's math and star data
```

Layout: `jenna/` (Python: brain, tools, memory, Telegram, the app server), `pc/` (the app and the three.js
galaxy), `personalities/`, `skills/`, and `brain_template/` (the starting Brain). She runs on ports 8793 and 8794,
so she can sit next to another assistant on the same PC.

## License

Jenna Lite is free software under the **GNU General Public License v3** (see [LICENSE](LICENSE)). You can use,
share and change it. If you share a changed version, share its source code under the same license. Third-party
parts and credits are listed in [CREDITS.md](CREDITS.md).

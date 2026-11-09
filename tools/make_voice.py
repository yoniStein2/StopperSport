"""Generate the voice pack the stopwatch plays: voice/pack.bin + voice/pack.json.

Every clip is encoded as constant-bitrate MP3 (24 kHz mono, 48 kbps, no bit
reservoir, no headers), so every frame is exactly 144 bytes = 576 samples = 24 ms
and frames can be concatenated freely. The app builds one continuous MP3 for a
whole run by splicing silence frames and clip frames at exact positions.

All language-specific text lives in PHRASES below. To change language/voice:
edit VOICE + the word lists, run `python tools/make_voice.py`, re-upload voice/.
Requires: pip install edge-tts imageio-ffmpeg
"""
import asyncio, json, os, subprocess
import edge_tts, imageio_ffmpeg

VOICE = "he-IL-HilaNeural"
RATE = "+5%"
MAX_MIN = 90
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "voice")
CACHE = os.path.join(ROOT, "tools", "_tts_cache")
FF = imageio_ffmpeg.get_ffmpeg_exe()
FRAME = 144

ONES = ["", "אחת", "שתיים", "שלוש", "ארבע", "חמש", "שש", "שבע", "שמונה", "תשע", "עשר",
        "אחת עשרה", "שתים עשרה", "שלוש עשרה", "ארבע עשרה", "חמש עשרה", "שש עשרה",
        "שבע עשרה", "שמונה עשרה", "תשע עשרה"]
TENS = ["", "עשר", "עשרים", "שלושים", "ארבעים", "חמישים", "שישים", "שבעים", "שמונים", "תשעים"]

def num(n):
    if n < 20: return ONES[n]
    t, o = divmod(n, 10)
    return TENS[t] + (" ו" + ONES[o] if o else "")

def minutes(m):
    return {1: "דקה", 2: "שתי דקות"}.get(m, num(m) + " דקות")

def seconds(s):
    return {1: "שנייה אחת", 2: "שתי שניות"}.get(s, num(s) + " שניות")

# id -> text. The app composes phrases from these ids (see index.html).
PHRASES = {"go": "מתחילים!", "zero": "אפס שניות"}
for m in range(1, MAX_MIN + 1):
    PHRASES[f"m{m}"] = minutes(m)                 # "דקה", "שתי דקות"
for s in range(5, 60, 5):
    PHRASES[f"n{s}"] = num(s)                     # callout under a minute: "עשר"
    PHRASES[f"a{s}"] = "ו" + num(s)               # after minutes: "ועשר"
for s in range(1, 60):
    PHRASES[f"s{s}"] = seconds(s)                 # final: "שלושים ושבע שניות"
    PHRASES[f"as{s}"] = "ו" + seconds(s)          # final after minutes

TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB,areverse,apad=pad_dur=0.06")
ENC = ["-c:a", "libmp3lame", "-b:a", "48k", "-ar", "24000", "-ac", "1", "-reservoir", "0",
       "-write_xing", "0", "-id3v2_version", "0", "-f", "mp3"]

def ff(*args):
    return subprocess.run([FF, "-y", "-loglevel", "error", *args], check=True, capture_output=True).stdout

def frames(data):
    """Validate: back-to-back 144-byte MPEG-2 L3 frames."""
    assert len(data) % FRAME == 0, len(data)
    for i in range(0, len(data), FRAME):
        assert data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0, i
    return data

async def tts(cid, text, sem):
    raw = os.path.join(CACHE, cid + ".mp3")
    if os.path.exists(raw): return raw
    async with sem:
        for attempt in range(4):
            try:
                await edge_tts.Communicate(text, VOICE, rate=RATE).save(raw); return raw
            except Exception:
                if attempt == 3: raise
                await asyncio.sleep(2)

async def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
    sem = asyncio.Semaphore(8)
    raws = dict(zip(PHRASES, await asyncio.gather(*(tts(c, t, sem) for c, t in PHRASES.items()))))
    clips = {}
    # 2 s of silence; keep 42 frames (~1 s) from the middle (every frame is self-contained)
    sil = frames(ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "2", *ENC, "-"))
    clips["silence"] = sil[10 * FRAME: 52 * FRAME]
    clips["beep"] = frames(ff("-f", "lavfi", "-i", "sine=frequency=1000:duration=0.15",
                              "-af", "afade=t=in:d=0.005,afade=t=out:st=0.11:d=0.04,volume=0.7", *ENC, "-"))
    for cid, raw in raws.items():
        clips[cid] = frames(ff("-i", raw, "-af", TRIM, *ENC, "-"))
    index, blob, pos = {}, bytearray(), 0
    for cid, data in clips.items():
        n = len(data) // FRAME
        index[cid] = [pos, n]; blob += data; pos += n
    with open(os.path.join(OUT, "pack.bin"), "wb") as f: f.write(blob)
    with open(os.path.join(OUT, "pack.json"), "w", encoding="utf-8") as f: json.dump(index, f)
    print(len(index), "clips,", len(blob), "bytes")

asyncio.run(main())

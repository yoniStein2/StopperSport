"""Generate the spoken clips the stopwatch plays (voice/*.mp3 + voice/clips.json).

All language-specific text lives in PHRASES below. To change language/voice:
edit VOICE + the word lists, run `python tools/make_voice.py`, re-upload voice/.
Requires: pip install edge-tts imageio-ffmpeg
"""
import asyncio, json, os, subprocess, sys, tempfile
import edge_tts, imageio_ffmpeg

VOICE = "he-IL-HilaNeural"
RATE = "+5%"
MAX_MIN = 90
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "voice")
FF = imageio_ffmpeg.get_ffmpeg_exe()

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

# id -> text.  The app composes phrases from these ids (see index.html).
PHRASES = {"cd3": "שלוש", "cd2": "שתיים", "cd1": "אחת", "go": "מתחילים!", "zero": "אפס שניות"}
for m in range(1, MAX_MIN + 1):
    PHRASES[f"m{m}"] = minutes(m)                 # "דקה", "שתי דקות"
for s in range(5, 60, 5):
    PHRASES[f"n{s}"] = num(s)                     # callout under a minute: "עשר"
    PHRASES[f"a{s}"] = "ו" + num(s)               # after minutes: "ועשר"
for s in range(1, 60):
    PHRASES[f"s{s}"] = seconds(s)                 # final: "שלושים ושבע שניות"
    PHRASES[f"as{s}"] = "ו" + seconds(s)          # final after minutes: "ושלושים ושבע שניות"

TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB,areverse,apad=pad_dur=0.06")

def ff(*args):
    subprocess.run([FF, "-y", "-loglevel", "error", *args], check=True)

async def make(cid, text, sem, tmp):
    dst = os.path.join(OUT, cid + ".mp3")
    if os.path.exists(dst): return
    async with sem:
        raw = os.path.join(tmp, cid + ".mp3")
        for attempt in range(4):
            try:
                await edge_tts.Communicate(text, VOICE, rate=RATE).save(raw); break
            except Exception as e:
                if attempt == 3: raise
                await asyncio.sleep(2)
        await asyncio.to_thread(ff, "-i", raw, "-af", TRIM, "-ac", "1", "-ar", "24000", "-b:a", "48k", dst)

async def main():
    os.makedirs(OUT, exist_ok=True)
    # non-speech clips
    ff("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.25", "-b:a", "32k", os.path.join(OUT, "silence.mp3"))
    ff("-f", "lavfi", "-i", "sine=frequency=880:duration=0.12", "-af", "afade=t=out:st=0.08:d=0.04,volume=0.6",
       "-ac", "1", "-ar", "24000", "-b:a", "48k", os.path.join(OUT, "beep.mp3"))
    ff("-f", "lavfi", "-i", "sine=frequency=1320:duration=0.25", "-af", "afade=t=out:st=0.18:d=0.07,volume=0.6",
       "-ac", "1", "-ar", "24000", "-b:a", "48k", os.path.join(OUT, "beephi.mp3"))
    sem = asyncio.Semaphore(8)
    with tempfile.TemporaryDirectory() as tmp:
        await asyncio.gather(*(make(c, t, sem, tmp) for c, t in PHRASES.items()))
    ids = ["silence", "beep", "beephi", *PHRASES]
    with open(os.path.join(OUT, "clips.json"), "w", encoding="utf-8") as f:
        json.dump(ids, f)
    print(len(ids), "clips")

asyncio.run(main())

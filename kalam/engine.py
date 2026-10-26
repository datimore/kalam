"""faster-whisper with an Egyptian-Arabic prompt, English hint words and a fix list.

Same recipe as the video captions: force Arabic, give Whisper a prompt written in
Egyptian dialect with English words in English letters (it copies that style), pass
the user's English terms as hotwords, then fix the spellings it still gets wrong.
"""
import glob
import os
import re
import sys
import time

import numpy as np

from . import config

SR = 16000


def _add_cuda_dlls():
    # cuBLAS / cuDNN come from the nvidia-* pip wheels; Windows needs their bin dirs on the DLL path
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.join(sys.prefix, 'Lib', 'site-packages')
    for d in glob.glob(os.path.join(base, 'nvidia', '*', 'bin')):
        try:
            os.add_dll_directory(d)
        except OSError:
            pass
        os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')


_add_cuda_dlls()

# Phrases Whisper invents on silence or noise (YouTube outros, subtitle credits)
HALLUCINATIONS = [
    'اشتركوا في القناة', 'اشترك في القناة', 'شكرا للمشاهدة', 'شكراً للمشاهدة', 'ترجمة نانسي',
    'نانسي قنقر', 'المترجم', 'لا تنسوا الاشتراك', 'thank you for watching', 'thanks for watching',
    'subtitles by', 'please subscribe', 'amara.org',
]
FILLER = re.compile(r'(?<!\w)(?:[اإأآ]?م{2,}|[اآ]{3,}|uh+|um+|hmm+|erm)(?!\w)[،,]?\s*', re.IGNORECASE)
ARTICLE = re.compile(r'(?<!\w)(ال|بال|وال|فال|كال|لل)ـ?\s*(?=[A-Za-z])')


def model_repo(name):
    from faster_whisper.utils import _MODELS
    return _MODELS.get(name, name)


def model_cached(name):
    """True when the model is already on disk (no download needed)."""
    if os.path.isdir(name):
        return True
    from faster_whisper.utils import download_model
    try:
        download_model(name, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def model_download_bytes(name):
    """Bytes of the model downloaded so far (for the first-run progress line)."""
    from huggingface_hub.constants import HF_HUB_CACHE
    folder = os.path.join(HF_HUB_CACHE, 'models--' + model_repo(name).replace('/', '--'))
    total = 0
    for dirpath, _, files in os.walk(folder):
        for f in files:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total


class Engine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = None
        self.device = None
        self.last_text = ''
        self.last_lang = None
        self.last_time = 0.0

    # ── model ────────────────────────────────────────────────────────────────
    def load(self):
        from faster_whisper import WhisperModel
        import ctranslate2

        want = self.cfg['device']
        if want == 'auto':
            want = 'cuda' if ctranslate2.get_cuda_device_count() > 0 else 'cpu'
        tries = [want] + (['cpu'] if want == 'cuda' else [])
        err = None
        for dev in tries:
            ct = self.cfg['compute_type']
            if ct == 'auto':
                ct = 'int8_float16' if dev == 'cuda' else 'int8'
            try:
                # cached models load without touching the network (works offline, starts faster)
                self.model = WhisperModel(self.cfg['model'], device=dev, compute_type=ct,
                                          local_files_only=model_cached(self.cfg['model']))
                self.device = f'{dev} ({ct})'
                # warm-up so the first real dictation is fast
                self.model.transcribe(np.zeros(SR, np.float32), language='ar', beam_size=1)
                return self.device
            except Exception as e:  # noqa: BLE001 - fall back to CPU on any CUDA problem
                err = e
        raise RuntimeError(f'Could not load model {self.cfg["model"]}: {err}')

    # ── language ─────────────────────────────────────────────────────────────
    def pick_language(self, audio):
        mode = self.cfg['language']
        if mode in ('ar', 'en'):
            return mode
        # smart: Arabic (with English words) unless the clip is clearly pure English.
        # Egyptian speech full of English terms still scores as Arabic, so the bar is high.
        try:
            _, _, probs = self.model.detect_language(audio)
            p = dict(probs)
        except Exception:  # noqa: BLE001
            return 'ar'
        en, ar = p.get('en', 0.0), p.get('ar', 0.0)
        return 'en' if en > 0.8 and en > 4 * ar else 'ar'

    # ── transcription ────────────────────────────────────────────────────────
    def transcribe(self, audio):
        """audio: float32 mono 16 kHz. Returns (text, info dict)."""
        t0 = time.time()
        secs = len(audio) / SR
        if secs < 0.35 or float(np.sqrt(np.mean(audio ** 2))) < 0.002:
            return '', {'secs': secs, 'skipped': 'too short or silent'}

        lang = self.pick_language(audio)
        prompt = config.read_text('prompt_ar.txt' if lang == 'ar' else 'prompt_en.txt')
        if self.cfg['use_context'] and self.last_text and self.last_lang == lang and time.time() - self.last_time < 600:
            prompt = f'{prompt} {self.last_text[-200:]}'
        hotwords = ' '.join(config.read_lines('words.txt')) or None

        # a short clip can't hold more than ~12 tokens/s; the cap stops repetition loops early
        cap = min(220, int(12 * secs) + 30) if secs < 18 else None
        segs, _ = self.model.transcribe(
            audio, language=lang, beam_size=self.cfg['beam_size'], initial_prompt=prompt, hotwords=hotwords,
            condition_on_previous_text=False, vad_filter=True, max_new_tokens=cap,
            temperature=[0.0, 0.5],  # one retry only: 6 fallbacks can take 10 s on a repetitive clip
            vad_parameters={'min_silence_duration_ms': 500, 'speech_pad_ms': 300},
        )
        parts = []
        for s in segs:
            t = s.text.strip()
            low = t.lower()
            if any(h in low for h in HALLUCINATIONS):
                continue
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            parts.append(t)
        text = self.clean(' '.join(parts), lang)
        if text:
            self.last_text, self.last_lang, self.last_time = text, lang, time.time()
        return text, {'secs': round(secs, 1), 'lang': lang, 'took': round(time.time() - t0, 2)}

    def clean(self, text, lang):
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return ''
        # a word or short phrase repeated more than 5 times in a row is a decoding loop
        text = re.sub(r'((?:\S+\s+){1,3}?)\1{5,}', lambda m: m.group(1) * 5, text + ' ').strip()
        for line in config.read_lines('fixes.txt'):
            if '=' not in line:
                continue
            wrong, right = (x.strip() for x in line.split('=', 1))
            if wrong:
                text = re.sub(rf'(?<!\w){re.escape(wrong)}(?!\w)', right, text)
        if lang == 'ar':
            text = ARTICLE.sub(lambda m: m.group(1) + 'ـ ', text)  # «ال agent» → «الـ agent»
        if self.cfg['remove_fillers']:
            text = FILLER.sub('', text).strip()
        return re.sub(r'\s+([،,.؟?!])', r'\1', text)

"""Teaching Kalam without editing files: fixes learned from your corrections or from your AI's answer."""
import difflib
import re

from . import config

FIXES = 'fixes.txt'
PUNCT = '،,.؟?!؛;:"\'«»()[]…'
MAX_PHRASE = 3  # a fix covers at most a few words; longer edits are rewrites, not misheard words


def _core(word):
    return word.strip(PUNCT)


def pair_text(wrong, right):
    """'wrong → right' that reads correctly for Arabic too (right-to-left, arrow pointing at the fix)."""
    first = next((ch for ch in wrong + right if ch.isalpha()), 'a')
    if '\u0600' <= first <= '\u06ff':
        return f'\u202b{wrong}  ←  {right}\u202c'
    return f'{wrong}  →  {right}'


# ── the fix list ─────────────────────────────────────────────────────────────
def read_fixes():
    pairs = []
    for line in config.read_lines(FIXES):
        if '=' in line:
            wrong, right = (x.strip() for x in line.split('=', 1))
            if wrong:
                pairs.append((wrong, right))
    return pairs


def write_fixes(pairs):
    path = config.DATA_DIR / FIXES
    header = [ln for ln in path.read_text(encoding='utf-8-sig').splitlines() if ln.strip().startswith('#')] \
        if path.exists() else []
    body = [f'{w} = {r}' for w, r in pairs if w.strip()]
    path.write_text('\n'.join(header + body) + '\n', encoding='utf-8')


def add_fixes(new_pairs):
    """Merge into the fix list (a new rule for the same wrong word replaces the old one). Returns what changed."""
    pairs = read_fixes()
    index = {w: i for i, (w, _) in enumerate(pairs)}
    changed = []
    for wrong, right in new_pairs:
        wrong, right = wrong.strip(), right.strip()
        if not wrong or wrong == right:
            continue
        if wrong in index:
            if pairs[index[wrong]][1] == right:
                continue
            pairs[index[wrong]] = (wrong, right)
        else:
            index[wrong] = len(pairs)
            pairs.append((wrong, right))
        changed.append((wrong, right))
    if changed:
        write_fixes(pairs)
    return changed


# ── learn from a correction ──────────────────────────────────────────────────
def learn_from_edit(original, edited):
    """Word pairs that were swapped between what Kalam wrote and what you corrected it to."""
    a = [_core(w) for w in original.split()]
    b = [_core(w) for w in edited.split()]
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != 'replace' or i2 - i1 > MAX_PHRASE or j2 - j1 > MAX_PHRASE:
            continue
        wrong = ' '.join(w for w in a[i1:i2] if w)
        right = ' '.join(w for w in b[j1:j2] if w)
        if wrong and right and wrong != right:
            out.append((wrong, right))
    return out


# ── ask your AI ──────────────────────────────────────────────────────────────
def recent_dictations(n=40):
    """Newest first: [{'time': ..., 'text': ...}]"""
    path = config.DATA_DIR / 'history.txt'
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding='utf-8').splitlines():
        parts = line.split(' | ', 3)
        if len(parts) == 4 and parts[3].strip():
            items.append({'time': parts[0], 'text': parts[3].strip()})
    return items[::-1][:n]


def ai_prompt(n=40):
    texts = [d['text'] for d in recent_dictations(n)][::-1]
    listing = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(texts)) or '(no dictations yet)'
    return f"""I use a speech-to-text app called Kalam. I speak Egyptian Arabic mixed with English, and it writes what I say.
Below are my recent dictations. Some words were written wrong, for example:
- formal Arabic spelling instead of Egyptian (يكذب instead of يكدب, ثلاثة instead of تلاتة)
- English words written in Arabic letters (داتا instead of data)
- misheard names of people, tools or companies
- words that sound alike but are wrong

Use what you know about me (my work, the tools and names I use, how I talk) together with the dictations.
Reply with ONLY lines in this exact format, one per line, nothing else:
wrong = right

Rules:
- only single words or very short phrases that appear in the dictations, or names you know I use
- keep my Egyptian way of speaking; never turn it into formal Arabic
- English terms in English letters
- skip anything you're not sure about; don't fix grammar and don't rephrase

My dictations:
{listing}
"""


_LINE = re.compile(r'^\s*(?:[-*•]|\d+[.)])?\s*(.+?)\s*(?:=>|->|→|=)\s*(.+?)\s*$')


def parse_ai_answer(text):
    """Reads `wrong = right` lines out of whatever the AI replied (bullets, numbering, code fences are fine)."""
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip().strip('`')
        if not line or line.startswith('#'):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        wrong, right = (x.strip().strip('"\'«»`*') for x in m.groups())
        if wrong and right and wrong != right and wrong not in seen and len(wrong.split()) <= 4:
            seen.add(wrong)
            out.append((wrong, right))
    return out

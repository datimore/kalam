"""Telling speakers apart (speaker diarization) and recognising your voice, with sherpa-onnx (no internet).

Two small ONNX models ship with Kalam (models/): pyannote segmentation (where speech is and when the speaker
changes) and a speaker-embedding model (a "voice fingerprint" per stretch of speech, grouped by similarity).
"""
import numpy as np

from . import config

SR = 16000
SEG_MODEL = config.ROOT / 'models' / 'sherpa-onnx-pyannote-segmentation-3-0' / 'model.onnx'
EMB_MODEL = config.ROOT / 'models' / '3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx'
VOICE_FILE = 'my-voice.npy'
SAME_SPEAKER = 0.62   # clustering threshold (lower = more speakers); tuned on test meetings
IS_YOU = 0.45         # cosine similarity to your recorded voice that counts as "you"


def available():
    return SEG_MODEL.exists() and EMB_MODEL.exists()


def _sherpa():
    import sherpa_onnx
    return sherpa_onnx


def diarize(audio, threshold=SAME_SPEAKER):
    """[(start, end, speaker_index)] in seconds, sorted by time."""
    so = _sherpa()
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEG_MODEL)), num_threads=4),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL), num_threads=4),
        clustering=so.FastClusteringConfig(num_clusters=-1, threshold=threshold),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = so.OfflineSpeakerDiarization(cfg)
    result = sd.process(np.ascontiguousarray(audio, dtype=np.float32)).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in result]


_extractor = None


def embedding(audio):
    """Voice fingerprint of a stretch of speech (unit vector)."""
    global _extractor
    so = _sherpa()
    if _extractor is None:
        _extractor = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL), num_threads=2))
    s = _extractor.create_stream()
    s.accept_waveform(SR, np.ascontiguousarray(audio, dtype=np.float32))
    s.input_finished()
    v = np.array(_extractor.compute(s), dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def save_my_voice(audio):
    np.save(config.DATA_DIR / VOICE_FILE, embedding(audio))


def my_voice():
    path = config.DATA_DIR / VOICE_FILE
    return np.load(path) if path.exists() else None


def speaker_audio(audio, turns, speaker, max_secs=40):
    """Up to `max_secs` of one speaker's speech, for comparing with your recorded voice."""
    parts, total = [], 0
    for start, end, spk in turns:
        if spk == speaker and end - start >= 0.8:
            parts.append(audio[int(start * SR):int(end * SR)])
            total += end - start
            if total >= max_secs:
                break
    return np.concatenate(parts) if parts else None


def find_me(audio, turns):
    """Which speaker index is you (by your recorded voice), or None."""
    mine = my_voice()
    if mine is None:
        return None
    best, best_sim = None, IS_YOU
    for spk in sorted({t[2] for t in turns}):
        clip = speaker_audio(audio, turns, spk)
        if clip is None:
            continue
        sim = float(np.dot(embedding(clip), mine))
        if sim > best_sim:
            best, best_sim = spk, sim
    return best

"""Downloads the two speaker models (sherpa-onnx releases, ~46 MB) into models/ for building Kalam."""
import io, tarfile, urllib.request
from pathlib import Path
M = Path(__file__).resolve().parent.parent / 'models'
BASE = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/'
SEG = M / 'sherpa-onnx-pyannote-segmentation-3-0' / 'model.onnx'
EMB = M / '3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx'
M.mkdir(exist_ok=True)
if not SEG.exists():
    data = urllib.request.urlopen(BASE + 'speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2').read()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:bz2') as t:
        for name in ('sherpa-onnx-pyannote-segmentation-3-0/model.onnx', 'sherpa-onnx-pyannote-segmentation-3-0/LICENSE'):
            (M / name).parent.mkdir(parents=True, exist_ok=True)
            (M / name).write_bytes(t.extractfile(name).read())
if not EMB.exists():
    EMB.write_bytes(urllib.request.urlopen(BASE + 'speaker-recongition-models/' + EMB.name).read())
print('models ready:', SEG.exists() and EMB.exists())

import sys, sherpa_onnx as so, soundfile as sf, numpy as np
import os
M=os.environ.get("TTS_MODELS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
def make(kind):
    if kind=="melo":
        d=f"{M}/vits-melo-tts-zh_en"; mc=so.OfflineTtsModelConfig(vits=so.OfflineTtsVitsModelConfig(model=f"{d}/model.onnx",lexicon=f"{d}/lexicon.txt",tokens=f"{d}/tokens.txt",dict_dir=f"{d}/dict"),num_threads=4); f=f"{d}/date.fst,{d}/phone.fst,{d}/number.fst"
    elif kind=="fanchen":
        d=f"{M}/vits-zh-hf-fanchen-C"; mc=so.OfflineTtsModelConfig(vits=so.OfflineTtsVitsModelConfig(model=f"{d}/vits-zh-hf-fanchen-C.onnx",lexicon=f"{d}/lexicon.txt",tokens=f"{d}/tokens.txt",dict_dir=f"{d}/dict"),num_threads=4); f=f"{d}/date.fst,{d}/phone.fst,{d}/number.fst"
    elif kind=="baker":
        d=f"{M}/matcha-icefall-zh-baker"; mc=so.OfflineTtsModelConfig(matcha=so.OfflineTtsMatchaModelConfig(acoustic_model=f"{d}/model-steps-3.onnx",vocoder=f"{M}/vocos-22khz-univ.onnx",lexicon=f"{d}/lexicon.txt",tokens=f"{d}/tokens.txt",dict_dir=f"{d}/dict"),num_threads=4); f=f"{d}/date.fst,{d}/phone.fst,{d}/number.fst"
    else:
        d=f"{M}/kokoro-multi-lang-v1_1"; mc=so.OfflineTtsModelConfig(kokoro=so.OfflineTtsKokoroModelConfig(model=f"{d}/model.onnx",voices=f"{d}/voices.bin",tokens=f"{d}/tokens.txt",data_dir=f"{d}/espeak-ng-data",dict_dir=f"{d}/dict",lexicon=f"{d}/lexicon-us-en.txt,{d}/lexicon-zh.txt"),num_threads=4); f=f"{d}/date-zh.fst,{d}/phone-zh.fst,{d}/number-zh.fst"
    return so.OfflineTts(so.OfflineTtsConfig(model=mc,rule_fsts=f,max_num_sentences=1))
if __name__=="__main__":
    kind,sid,speed,txt,out=sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),sys.argv[4],sys.argv[5]
    t=make(kind); a=t.generate(open(txt).read().strip(),sid=sid,speed=speed)
    sf.write(out,np.array(a.samples),a.sample_rate); print(out, round(len(a.samples)/a.sample_rate,1),"s", "speakers",t.num_speakers)

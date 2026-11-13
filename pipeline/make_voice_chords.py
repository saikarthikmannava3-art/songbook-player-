#!/usr/bin/env python3
"""make_voice_chords.py: chord-name clips (c_<chord>.mp3) + "Change" for the voice coach, for every chord in songs/ and the chord-shape library.
Run after make_voice.py:  ~/.venvs/kokoro/bin/python pipeline/make_voice_chords.py  (expects chords.json from the chord list step)
"""
import os,json,re,subprocess,numpy as np,soundfile as sf
from kokoro import KPipeline
OUT=os.path.expanduser("~/songbook-player/voice")
L={"A":"Ay","B":"Bee","C":"See","D":"Dee","E":"Ee","F":"Eff","G":"Jee"}
def say(c):
    m=re.match(r"^([A-G])([#b]?)(.*?)(?:/([A-G][#b]?))?$",c);r,acc,q,bass=m.groups()
    t=L[r]+(" sharp" if acc=="#" else " flat" if acc=="b" else "")
    Q={"":"","m":" minor","7":" seven","m7":" minor seven","maj7":" major seven","sus2":" sus two","sus4":" sus four","add9":" add nine","6":" six","5":" five","dim":" dim"}
    t+=Q.get(q," "+q)
    if bass:t+=" over "+L[bass[0]]+(" sharp" if bass[1:]=="#" else " flat" if bass[1:]=="b" else "")
    return t+"."
def key(c):return "c_"+c.replace("#","s").replace("/","_")
chords=json.load(open("chords.json"))
VOICES={"michael":"am_michael","fenrir":"am_fenrir","puck":"am_puck"}
pipe=KPipeline(lang_code="a");meta=json.load(open(f"{OUT}/voice.json"))
def trim(y,sr):
    a=np.abs(y);thr=max(a.max()*10**(-30/20),1e-4);idx=np.where(a>thr)[0]
    s=max(0,idx[0]-int(0.004*sr));e=min(len(y),idx[-1]+int(0.02*sr));y=y[s:e].copy()
    f=int(0.012*sr);y[-f:]*=np.linspace(1,0,f);return y
items=[(key(c),say(c),1.25) for c in chords]+[("change","Change.",1.2),("change_q","Change.",1.65)]
for vk,vid in VOICES.items():
    for k,txt,sp in items:
        y=np.concatenate([np.asarray(a) for _,_,a in pipe(txt,voice=vid,speed=sp)]);sr=24000
        y=trim(y,sr);y=np.clip(y*(0.12/np.sqrt(np.mean(y**2))),-0.98,0.98);w=f"/tmp/kvoice/{vk}_{k}.wav";sf.write(w,y,sr)
        subprocess.run(["ffmpeg","-v","error","-y","-i",w,"-ac","1","-ar","24000","-b:a","48k",f"{OUT}/{vk}/{k}.mp3"],check=True)
        meta["dur"][vk][k]=round(len(y)/sr,3)
    print(vk,"done",flush=True)
meta["chords"]={c:key(c) for c in chords}
json.dump(meta,open(f"{OUT}/voice.json","w"),indent=1)
print({c:say(c) for c in ["A","Am","F#m","D/F#","Bbmaj7","Dsus2"]})

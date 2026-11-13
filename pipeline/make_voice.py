#!/usr/bin/env python3
"""make_voice.py: renders the voice-coach clips in voice/<voice>/*.mp3 with Kokoro-82M (Apache-2.0), offline.

Setup:  /opt/homebrew/bin/python3.12 -m venv ~/.venvs/kokoro && ~/.venvs/kokoro/bin/pip install kokoro soundfile
Run:    ~/.venvs/kokoro/bin/python pipeline/make_voice.py
Each word is trimmed tight (so it starts on the beat) and levelled to the same loudness; "_q" = a quicker take for fast tempos.
"""
import os, json, subprocess, numpy as np, soundfile as sf
from kokoro import KPipeline
OUT=os.path.expanduser("~/songbook-player/voice")
NUM=["one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve"]
WORDS={**{n:n.capitalize()+"." for n in NUM},"and":"and.","e":"ee.","a":"uh.","down":"Down.","up":"Up.",
  "ready":"Ready?","herewego":"Here we go.","nicework":"Nice work.","listen":"Listen first.","yourturn":"Your turn.","faster":"A little faster.","goodjob":"That's it, nice and steady.","bass":"Bass.","chuck":"Chuck."}
for n in NUM+["and","e","a"]:
    lab=n if n not in("e","a") else {"e":"ee","a":"uh"}[n]
    WORDS[n+"_down"]=f"{lab.capitalize()}, down."; WORDS[n+"_up"]=f"{lab.capitalize()}, up."
QUICK=NUM+["and","e","a","down","up","bass","chuck"]
VOICES={"michael":"am_michael","fenrir":"am_fenrir","puck":"am_puck"}
pipe=KPipeline(lang_code="a")
meta={}
def trim(y,sr):
    a=np.abs(y);thr=max(a.max()*10**(-30/20),1e-4);idx=np.where(a>thr)[0]
    s=max(0,idx[0]-int(0.004*sr));e=min(len(y),idx[-1]+int(0.02*sr));y=y[s:e].copy()
    f=int(0.012*sr);y[-f:]*=np.linspace(1,0,f);y[:int(0.002*sr)]*=np.linspace(0,1,int(0.002*sr));return y
for vk,vid in VOICES.items():
    os.makedirs(f"{OUT}/{vk}",exist_ok=True);meta[vk]={}
    items=[(k,t,1.12) for k,t in WORDS.items()]+[(k+"_q",WORDS[k],1.65) for k in QUICK]
    for k,txt,sp in items:
        y=np.concatenate([np.asarray(a) for _,_,a in pipe(txt,voice=vid,speed=sp)]);sr=24000
        y=trim(y,sr);rms=np.sqrt(np.mean(y**2));y=y*(0.12/rms);y=np.clip(y,-0.98,0.98)
        w=f"/tmp/kvoice/{vk}_{k}.wav";sf.write(w,y,sr)
        subprocess.run(["ffmpeg","-v","error","-y","-i",w,"-ac","1","-ar","24000","-b:a","48k",f"{OUT}/{vk}/{k}.mp3"],check=True)
        meta[vk][k]=round(len(y)/sr,3)
    print(vk,"done",flush=True)
json.dump({"voices":{"michael":"Michael — warm, calm","fenrir":"Fenrir — deeper","puck":"Puck — brighter"},"dur":meta,
  "credit":"Kokoro-82M (Apache-2.0), voices am_michael / am_fenrir / am_puck, rendered offline"},open(f"{OUT}/voice.json","w"),indent=1)

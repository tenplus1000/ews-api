# ews — a small yes/no and multiple-choice judge for game scenes

**ews** (ElseWitness) answers short, concrete questions about a piece of text — usually a scene from a game:
*did anyone eat something here? does this character know about that fact yet? is this scene over?*
It returns a probability for yes/no questions and a pick for multiple-choice ones.

It was trained for [Elsewhen](https://play.elsewhengame.com/about), a text game where an LLM narrates history,
and it now answers part of the game's bookkeeping questions in production. See [MODEL_CARD.md](MODEL_CARD.md)
for what it is good and bad at.

The API uses the same request format as OpenRouter's decisions endpoint, so code written for that only needs a
different URL and key.

## Get a key

Keys are free and handed out by hand. Send a message saying what you want to try:

- Email: `<EMAIL>`
- Discord: https://discord.gg/Hpxnzg5XZP
- Instagram: `<IG>`
- Threads: `<THREADS>`

Each key has a daily limit (500 requests by default; ask if you need more).

## Call it

```bash
curl https://api.elsewhengame.com/v1/decisions \
  -H "Authorization: Bearer $EWS_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ews-0.6",
    "state": "She handed him the last piece of bread. He tore it in half and ate it standing at the door.",
    "questions": {
      "ate":  {"type": "noul", "instructions": "In this scene, did anyone eat something?"},
      "who":  {"type": "choice", "instructions": "Who ate?",
               "criteria": {"she": "the woman", "he": "the man", "none": "nobody"}}
    }
  }'
```

```json
{"id": "ews-a7d76c44c3834768", "model": "ews-0.6",
 "answers": {
   "ate": {"type": "noul", "noul": 0.9036, "confidence": 0.9036},
   "who": {"type": "choice", "choice": "he", "probabilities": {"she": 0.1905, "he": 0.7005, "none": 0.109}}
 },
 "usage": {"elapsed_s": 0.2266}}
```

(a real response, trimmed: `noul` is the probability of *yes*; `choice` is the pick and `probabilities` the full spread.)

Python:

```python
import os, requests

r = requests.post("https://api.elsewhengame.com/v1/decisions",
                  headers={"Authorization": f"Bearer {os.environ['EWS_KEY']}"},
                  json={"model": "ews-0.6", "state": scene_text,
                        "questions": {"q": {"type": "noul", "instructions": "Is the scene over?"}}},
                  timeout=30)
r.raise_for_status()
yes = r.json()["answers"]["q"]["noul"]       # 0.0 – 1.0
```

### Request

| field | |
|---|---|
| `model` | `"ews-0.6"` (optional) |
| `state` | the text to judge, up to 20,000 characters; longer texts keep their **end** |
| `questions` | up to 20 named questions, each `{"type": "noul" \| "choice", "instructions": "…"}`; `choice` also needs `"criteria": {id: description}` |

`noul` = yes/no; the answer is the probability of *yes*. Write instructions in English; the state can be in any
language the game writes (it is trained on Traditional Chinese and English).

### Errors

| status | meaning |
|---|---|
| 400 | the request body is malformed (the message says which field) |
| 401 | missing, wrong or revoked key |
| 413 | body larger than 64 KB |
| 429 | daily limit reached (resets 00:00 UTC), or the model is busy — retry after a few seconds (`Retry-After`) |
| 502 | the model server is down; try again later |

## How it runs, and what is kept

The model runs on one consumer GPU at home. Elsewhen's own requests come first; outside requests are served one
at a time when the card is free, so expect 0.5–2 s per call and occasional 429s.

**Requests are logged** — the text, the questions and the answers — and may be used to improve the model.
Don't send personal data or anything you can't share.

## 中文

ews 是穿越吧 Elsewhen 自己訓練的判官：給一段文字（通常是遊戲的一幕）跟幾個具體的是非題或選擇題，
回機率或選項。格式跟 OpenRouter 的 decisions 一樣，換網址和 key 就能用。key 免費、人工發，
用上面任一個管道私訊說想拿來做什麼。請求會被記錄、可能拿來改進模型，請不要送個資。

# ews：判遊戲場景的小型是非題／選擇題判官

[English](README.md) · [模型卡](MODEL_CARD.zh-TW.md)

**ews**（ElseWitness）回答關於一段文字（通常是遊戲的一幕）的簡短、具體問題：
*這一幕有沒有人吃東西？這個角色現在知不知道那件事？這一幕結束了沒？*
是非題回「是」的機率，選擇題回選了哪一個。

它是替 [穿越吧 Elsewhen](https://play.elsewhengame.com/about) 訓練的：一款由大型語言模型敘述歷史的文字遊戲。
現在遊戲裡有一部分記帳題已經正式交給它回答。擅長什麼、不擅長什麼，寫在[模型卡](MODEL_CARD.zh-TW.md)。

請求格式跟 OpenRouter 的 decisions 端點一樣，已經照那個格式寫好的程式，只要換網址和 key 就能用。

## 拿 key

key 免費、人工發。用下面任一個管道私訊，說一下想拿來做什麼：

- Email：rogertenplusde@gmail.com
- Discord：https://discord.gg/Hpxnzg5XZP
- Instagram：[@tenplus.1000](https://www.instagram.com/tenplus.1000)
- Threads：[@tenplus.1000](https://www.threads.net/@tenplus.1000)

每把 key 有每日上限（預設 500 次，要更多可以再說）。

## 怎麼呼叫

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

（實際回應、省略部分欄位：`noul` 是「是」的機率；`choice` 是選了哪個，`probabilities` 是每個選項的機率。）

Python：

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

### 請求欄位

| 欄位 | |
|---|---|
| `model` | `"ews-0.6"`（可省略） |
| `state` | 要判的文字，最多 20,000 字；更長的會保留**後面**那段 |
| `questions` | 最多 20 題，每題 `{"type": "noul" \| "choice", "instructions": "…"}`；`choice` 另外要 `"criteria": {代號: 說明}` |

`noul` 是是非題，答案是「是」的機率。題目（instructions）請用英文寫；要判的文字可以是繁體中文或英文（它是用這兩種練的）。

### 錯誤

| 狀態碼 | 意思 |
|---|---|
| 400 | 請求內容格式不對（訊息會說是哪一欄） |
| 401 | 沒帶 key、key 錯了，或 key 已停用 |
| 413 | 請求超過 64 KB |
| 429 | 今天的次數用完了（UTC 00:00 重算），或模型正忙——過幾秒再試（看 `Retry-After`） |
| 502 | 模型伺服器沒開，晚點再試 |

## 怎麼跑、留下什麼

模型跑在家裡的一張消費級顯卡上。Elsewhen 自己的請求優先；外部請求在顯卡有空時一次處理一發，
所以一發大約 0.5–2 秒，偶爾會回 429。

**請求會被記錄**（文字、題目、答案），可能拿來改進模型。請不要送個資，或任何不能分享的內容。

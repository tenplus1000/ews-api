# Model card: ews-0.6

## What it is

A small classifier-style judge fine-tuned to answer concrete yes/no (`noul`) and multiple-choice (`choice`)
questions about game scenes. It replaces a general-purpose hosted judge (Jev, `typesafe/jev-1.13`, on
OpenRouter) for some of [Elsewhen](https://play.elsewhengame.com/about)'s bookkeeping questions:
*who knows this fact now, does this scene need a stitch in the narration, did the player's situation change.*

- Version: 0.6 (October 2026). Earlier versions 0.2–0.5 were trained the same way on less data.
- Serving: one RTX 3050 (8 GB); ~50 ms of GPU time per question.
- Weights: private for now.

## Training data

Questions the game asked during real play, with answers from Jev and from hand/LLM-assisted labels:

- 2,399 records where ews and Jev disagreed or that fell in question types with high error rates were labelled
  (human-checked rules, LLM labellers, cross-checked: two labellers agreed on 92%).
- Plus agreeing answers as soft labels and a replay of the previous version's training rows.
- Split by game, so no test game was seen in training.

Training data stays local; it is not published.

## Results

Held-out test: 14 games, 1,186 labelled questions.

| | ews-0.6 | Jev |
|---|---|---|
| all questions | **83.0%** | 86.0% |
| questions where the two disagreed (298) | 175 | 222 |
| questions where the two agreed (888) | 809 | 798 |
| "who knows this fact" (462) | **426** | 406 |

Weaker than Jev on: whether a fact is stale (105/127), which people a fact is about (50/60), who is present (46/57),
whether the narrator voice needs to speak (10/16). In production Elsewhen only routes the types where ews matches
or beats Jev to it, and keeps asking Jev in the background to watch for drift.

## Limits

- Trained on one game's questions; other genres need testing first. Pair-test it: write two texts that differ in
  one detail and check the answer flips.
- Instructions are English; scene text in Traditional Chinese or English.
- Vague, judgement-heavy questions ("is this good writing?") are near chance — ask concrete, checkable things.

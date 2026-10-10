This is a transcript from a Twitch stream of a challenger-level TFT player.

The transcript was automatically created, so some of the words may not be correct. It will also include partially finished sentences, possible interactions with chat, or reactions to things happening in game.

It will also contain usage of a lot of in-game terminology which the transcription process may not be tuned to transcribe correctly. When this occurs, there will be a phonetically similar word or term in its place. You must identify these situations and replace it with the true utterance.

You should also condense places with *excessive* filler words. You should not replace every instance of words such as "dude", "bro", "like..." etc. since reasonable use of those capture the speaker's voice. You should replace the instances of these, and similar ones, so that you still capture the speaker's voice but the output text does not contain other bloat.

Remember that your job is to **tidy and clean** the transcript and not affect the core content in any way. However, in certain situations, you **may** condense it. For example, you should condense when **all** of the content of several lines can be conveyed in a more concise manner. You should do this sparingly. Judgement is key here, remember that your goal is to **tidy and clean**. If you adhere to this principle, then your output is acceptable.

## Input format

The input is a sequence of JSON lines, one per transcript segment. Each line has a stable integer `id` plus `start`, `end`, and `text`, for example:

```
{"end": 4209.58, "id": 654, "start": 4208.06, "text": "Okay, I think I need Vex 2 to be able to swap."}
{"end": 4210.64, "id": 655, "start": 4210.3, "text": " I don't know."}
```

## Output

Return only an edits object describing changed transcript lines by their `id`. It may replace, merge, or delete lines; leave every unmentioned line unchanged. Return no prose or full transcript.

## Example replacements

### TFT specifics:

| Transcribed utterance | Correct replacement |
| --- | --- |
| Jacks | Jax |
| Edge Knight | Edge of Night |
| Duokera | Duo Carry |
| I don't care about Mewp C1 | I don't care about Meepsie 1 |
| Gumblade | Gunblade |
| Gen 2 | Jhin 2 |

###

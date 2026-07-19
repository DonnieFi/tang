# Prepare real session data for a Tang video

Use this only when you want real local sessions for a filmed Tang workflow.
It is separate from `tang demo`: the product demo remains synthetic and
disposable, while this director helps you make nine honest off-camera research
sessions in one dedicated project.

```bash
python scripts/prepare_video_lab.py init ~/tang-video-lab
python scripts/prepare_video_lab.py next ~/tang-video-lab
```

`next` prints one card. Open the named harness in `~/tang-video-lab`, paste the
card, get its response, and return to the director:

```bash
python scripts/prepare_video_lab.py done ~/tang-video-lab
python scripts/prepare_video_lab.py next ~/tang-video-lab
```

Use `/new` between cards in Codex and OpenCode so each prompt becomes a
separate native session. Create separate Grok sessions in the same project
context. The nine cards proceed in this order: three Codex sessions, three
OpenCode sessions, then three Grok sessions. Every session answers one of three
vacation-research questions with exactly five items:

- rising places in Asia;
- books to bring; and
- excursions or day trips.

The director does not run Codex, OpenCode, Grok, Tang, or a model. It does not
write native session data. Its state file records only completed card names.

When all cards are complete, use the director's dedicated outputs:

```bash
python scripts/prepare_video_lab.py film ~/tang-video-lab
python scripts/prepare_video_lab.py voiceover ~/tang-video-lab
```

`film` starts with the Book merge: open a fresh Codex session in the lab, run
`tang index`, browse, search `books to bring`, and select the three Book
sessions. Build their Context Pack **before** linking. In Codex, ask for a
concise summary of all fifteen recommendations using only that cited pack and
to name uncertainty. Then request explicit approval, link the three sources to
the fresh target, render the graph, and run `tang context all --for
<book-target-handle>`.

Repeat the same pattern for places and day trips. Finally create one fresh
target, select all nine original research sessions, build their Context Pack,
explicitly confirm the nine-source link, and render the graph. `voiceover`
prints a separate roughly 70-second narration for the Book merge; read it over
the screen capture rather than trying to narrate during preparation.

Do the card preparation off camera. The video should show Tang’s recovery,
citations, explicit confirmation, graph, and predecessor recall—not prompt
creation or native-session administration.

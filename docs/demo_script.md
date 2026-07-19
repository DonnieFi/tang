# Tang demo voice-over

Hi, I’m Donnie, and this is Tang, my OpenAI Build Week submission.

Tang lets you continue one coding agent’s work inside another without losing
the original evidence. The name comes from sword making: the tang is the part
of a blade that continues into its handle. That is the product idea—keep the
work, even when you change the handle.

The idea started when I changed coding harnesses during a Sol experiment and a
session crashed while I was writing a specification. Recovering it was harder
than it should have been. I built Tang in Codex with GPT-5.6, used Beads and
review gates to keep the work deliberate, and used Codex, Grok, and OpenCode
sessions to test the portability claim against real local history.

For this demo, the same vacation-research questions live in all three tools.
They are separate, siloed conversations. From Codex, Tang searches the current
project, lets me select the relevant sessions, and rereads only that native
evidence locally. It redacts the result and returns a compact Context Pack with
citations. GPT-5.6 turns that evidence into a concise continuation brief.

Nothing is linked automatically. I explicitly confirm the continuation, then
Tang records the edges and renders the Multiverse Map. The CLI shows the same
merge into an OpenCode target, so the graph is not a decorative summary—it is
proof of the confirmed provenance path.

Tang is not trying to replace anyone’s favorite agent. It makes moving between
them natural while keeping the sources that got you there. Thanks for watching.

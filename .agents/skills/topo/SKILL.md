---
name: topo
description: Author and review visual plans as self-contained HTML artifacts under docs/plans/, opened in the user's browser for annotation; use for plans, comparisons, and architectures. Requires the topo plugin's topo_write/topo_open/topo_feedback tools.
---

# Topo: visual planning artifacts

Any plan, proposal, comparison, or architecture the human should review
visually belongs in a topo artifact — one self-contained HTML file the user
reads and annotates in their browser. This is the review loop; don't fall
back to walls of chat text for visual material.

## When

- The user asks for a plan, proposal, rollout, migration, or design.
- A comparison (options, trade-offs) is clearer as a table than prose.
- The user says "put this in topo" or references an existing artifact.

Not for: code, config, one-answer questions, or anything the user will not
review. Normal tool/file work is fine for those.

## Authoring rules

- One self-contained file: no external CSS/JS/images; inline `<style>`;
  standard CSS only (flex/grid, no exotic selectors).
- Stable `id=` on every heading and section — review comments anchor to
  them. Never renumber or reword ids across revisions.
- Skimmable: headings, short paragraphs, tables, whitespace. No walls of
  text.
- Include: goal, non-goals, steps/phases, risks, open questions, and a
  status line the user can scan in five seconds.

## Diagrams

Mermaid from a CDN is allowed:

```html
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>mermaid.initialize({startOnLoad: true});</script>
<pre class="mermaid">
flowchart LR
  A[build] --> B{tests?}
  B -- pass --> C[ship]
  B -- fail --> A
</pre>
```

Flowchart, sequence, and state diagrams all work. Keep sources editable:
mermaid source in the file is authoritative, not a rendered image.

## Review loop

1. `topo_write` the artifact (path under docs/plans/, e.g. "auth-rollout";
   .html optional).
2. `topo_open` it, then tell the user it is open in their browser.
3. `topo_feedback` to collect their comments — empty until they send from
   the browser panel; do not poll in a tight loop. One call after they say
   they have sent, or once per turn when they ask for changes.
4. Revise with `topo_write` — their tab live-reloads — and repeat until
   they approve.

Comments arrive anchored (e.g. `h1#rollout "Q3 rollout"` with optional
selected text); fix the anchored content, not just the words.

# Structured tutor content and subject extension boundaries

## Status and intent

Design for review; not implemented. The user selected typed content blocks over
a single formatted message, with readable text, lists and equations first and
interactive elements later. They require well-defined application boundaries
and content types that can vary by subject or topic without accumulating those
types in the core engine. Implementation requires approval of this document and
a subsequent implementation plan.

Independent builder check completed: no important unanswered planning questions
were reported. User approval of this written design is still pending.

The motivation is clearer explanations and predictable presentation, not longer
answers. The independent tutor review showed that a correct explanation can be
hard to follow when several conceptual steps are packed together. It also showed
that extra detail can distract. Structure must support both concise prose and
multi-step explanations. The student-facing response has one authoritative
content source; rendering, verification, history and evaluation must agree on it.

## Agreed scope and proposed implementation choices

Agreed: semantic blocks rather than visual lines; paragraphs, ordered/unordered
lists and mathematics, including inline mathematics; reusable subject/topic
capabilities; front-end control of styling; no interactive content in this slice.

The names, wire shapes, selection precedence, bounds and migration mechanisms
below are design proposals by the assistant, not additional user requirements.
No browser application exists in this repository. This slice supplies the engine
contract, validation, provider integration, persistence, reference presentation
artifacts and tests; it does not build a product UI or choose a front-end stack.

Non-goals: chemistry/history block implementations, media/graphs, arbitrary
proof trees, inputs/widgets, streamed partial delivery, hyperlinks, HTML, custom
styles, nested lists, emphasis marks, subject-specific mastery policies, or a
general plugin marketplace. No changes to exercise statements, student answer
schemas or verification-kind selection are required by this slice.

## Approaches and decision

1. **Restricted Markdown in `message`:** least migration work and familiar prose,
   but presentation has to infer structure from text and extension validation is
   less explicit.
2. **Typed content blocks:** explicit, bounded structures and reusable extension
   contracts, at the cost of changes to generation, validation, history and evals.

The user selected option 2. Per-visual-line objects and arbitrary formatting
attributes were rejected as the abstraction: line wrapping depends on viewport
and accessibility settings, while paragraphs, lists and notation have stable
meaning. A model does not choose CSS, fonts, colours, indentation or pixel sizes.

## Current repository contracts

- `domain/items.py` has `Text | Formula` statement blocks. `Formula.source` is
  written notation, opaque to the domain; it is not arbitrary display LaTeX.
- `domain/turn.py` has `TutorTurn.message: str`. `validate_turn` uses that string
  for emptiness and the answer leak check. Other engine permission checks remain
  independent of content formatting.
- `adapters/tutor/turn_schema.py` parses both providers' turns and rejects control
  characters. Each provider currently supplies its own fixed output schema.
- `ResolvedRoleConfig` captures effective settings/schema hashes at route
  resolution. Per-skill content profiles therefore cannot be bolted on only when
  displaying the result: the selected schema must reach request preparation.
- `domain/engine.py`, `HistoryRecord`, transcripts, context selection, fixtures,
  judge packets and saved artifacts all currently carry string messages.
- The parent design's D19 proposes registered output media, but it is deferred.
  This design uses the same principle of registered, validated capabilities;
  it does not claim D19 media or a rendering registry already exists.

## Boundaries and ownership

| Layer | Owns | Must not own |
| --- | --- | --- |
| Domain | Immutable document/node envelopes, profile identity, content-validation port, delivery decisions, help/mastery policy | JSON Schema libraries, SymPy, renderer code, provider SDKs, a union of every subject's specialized payload |
| Shared content implementation | Paragraph/list/text grammar, traversal, bounds, deterministic projections, trusted type registry | Student-specific pedagogical decisions or provider-specific schema rules |
| Content extensions | Their namespaced payload schemas, semantic validation, projections and supported placements | Permission to deliver a response or alter mastery |
| Application composition | Profile selection, trusted registry construction, provider/presentation compatibility checks, dependency injection | Guessing capabilities from student prose or allowing model-selected plugins |
| LLM adapters | Encoding the selected shared contract in provider wire schemas and parsing responses against it | Separate subject-specific content taxonomies |
| Presentation adapters | Rendering validated types, escaping text, accessibility, layout and wrapping | Repairing/reinterpreting rejected model content or bypassing engine validation |

Adding a specialized content type requires registering an extension and compatible
presentation/inspection support, not editing the core domain or adding subject
branches to each provider adapter. Generic contract changes can still require
domain changes; this is not a promise that every future feature fits unchanged.

Capabilities are not exclusively owned by subjects. For example, mathematical
notation may be enabled in chemistry. A future reaction block or timeline block
would be registered separately, then selected by the relevant content profiles.

## Document and initial vocabulary

A versioned `ContentDocument` contains ordered nodes. Each node has a stable,
namespaced `kind`, integer `version`, and `data`. Nested content exists only in
schema-declared child slots. Payloads are plain bounded data, copied and frozen
after parsing; the model cannot name Python classes, modules or executable code.

Initial registered node types:

| Type/version | Placement | Payload |
| --- | --- | --- |
| `core.text` / 1 | Inline | `text`: literal Unicode text |
| `core.paragraph` / 1 | Block | `children`: nonempty inline-node sequence |
| `core.list` / 1 | Block | `ordered`: boolean; `items`: nonempty sequences of inline nodes |
| `math.notation` / 1 | Inline or block | `source`: supported mathematical notation |

Lists are one level deep; an item is a single paragraph of inline nodes. Node
placement determines inline versus displayed notation; no independent display
flag can contradict it. Text does not interpret Markdown or HTML. New paragraph
blocks represent paragraph boundaries; incidental line breaks inside text are
ordinary whitespace, not commands to create list items or hidden containers.

The math extension initially accepts the existing safe parser's expression,
equation and explicit-alternative forms (`parse_math`/`parse_step`). Unsupported
notation is an explicit content error, not a mathematical misconception. The
extension validates notation and preserves written operators, signs and terms;
it must not simplify an equation or solve it just to display it. Arbitrary LaTeX
commands are not model input. A presentation adapter may generate restricted
display markup from validated written notation. Tool-verification success is
not implied by notation validation.

Example of the model's content field (metadata such as rung remains outside it):

```json
{
  "content": {
    "version": 1,
    "blocks": [
      {
        "kind": "core.paragraph", "version": 1,
        "data": {"children": [
          {"kind": "core.text", "version": 1,
           "data": {"text": "Adding the same amount to both sides preserves equality."}}
        ]}
      },
      {"kind": "math.notation", "version": 1,
       "data": {"source": "x - 7 + 7 = 0 + 7"}}
    ]
  }
}
```

This example illustrates the wire shape, not an ideal reply or permission to
disclose a particular exercise's answer. Every candidate still passes its task's
normal engine gate.

Proposed initial limits: at most 32 top-level blocks, 20 items per list, 32 inline
nodes per paragraph/item, 256 nodes total, 16,384 decoded text/source characters
total and 65,536 UTF-8 bytes for the raw candidate. Math source retains the
existing parser limit (currently 512 characters). All counts are cumulative
across the document. Fixed grammar bounds nesting; no arbitrary recursion is
accepted. These limits supplement, not replace, existing token/time budgets.
Reject unknown fields, invalid scalar types, empty content and disallowed control
characters throughout textual payloads. Do not silently discard malformed nodes.

## Registered extension contract

A trusted registry entry supplies:

- Stable kind/version, permitted placements and a closed payload schema.
- Payload/semantic validation and an explicit inventory of child slots.
- Deterministic student-visible text and inspection material, including all
  visible labels and accessible text; no model-authored fallback can conceal
  another visible field from checking.
- Versioned presentation support and a faithful plain representation for history
  and evaluation. A rich renderer cannot invent extra explanatory content.
- Compatibility metadata and contract tests establishing that visible content
  is covered by inspection. Schemas and implementations have captured identities.

The registry is assembled from installed trusted code. Config selects registered
IDs; it never loads arbitrary import paths or scripts from artifacts or content.
Duplicate registrations, unresolved types or missing capabilities fail locally.
Extension-specific mathematical/semantic processing belongs outside the domain.

For initial text/list/notation nodes, inspect both the whole reading-order content
and each explicit notation source. Inspection text excludes renderer-generated
list numbers and bullets, which are structure rather than student-visible claims;
it includes every model-authored item character. It is distinct from the readable
plain projection that includes list markers. Inline spans are concatenated exactly
before checking; formatting boundaries may not conceal a final answer. Preserve
ordinary prose candidate extraction as well: the model must not
evade leak checking by writing mathematics inside `core.text` instead of notation.

Plain text alone does not prove future diagram safety. A later visual extension
must define how its visible facts are checked against the active answer policy,
or be disallowed in that activity. Human-readable alternative text is not a
sufficient surrogate for inspecting a graph's actual plotted data. No such visual
extension is implemented in this slice.

## Selecting allowed types

`ContentProfile` is an application-selected, versioned bundle of allowed block and
inline types, limits and inspection requirements. Selection is deterministic:
an explicit trusted activity override, then a skill override, then a subject
default, then an application default. Each selection chooses a complete profile;
there is no implicit union that accidentally broadens permissions.

Use a separate configuration catalogue keyed by existing subject/skill IDs. A
topic can map its constituent skills to the same profile; do not invent a new
topic taxonomy or change `Skill` merely for this feature. Profile definitions
can be reused across subjects. The first implementation needs a core-text
profile and a math-text profile, even if live tasks currently use only math.

Application composition resolves the profile against installed extensions,
configured presentation capabilities, inspection support and the selected
provider's schema encoder. An unsatisfied required capability fails preflight;
there is no silent removal of a required type. Client input may select among
server-authorized presentation capabilities in future, but cannot expand the
trusted subject/activity allowlist. There is no HTTP negotiation in this slice.

Freeze the resolved contract for one tutor exchange, including private repairs.
The model sees only the selected vocabulary, not every installed subject type.
Record profile identity, canonical schema hash, projection version and extension
versions in the request/run evidence. Read-only contextual information must not
be confused with permission to emit those same types: historical content can
come from a different profile.

Carry a domain-safe reference to the selected contract on the prepared turn
context. It is assigned by trusted application/engine preparation, not parsed
from the candidate. The validator resolves that reference through its injected
registry and verifies the candidate against it; a model or custom tutor cannot
claim a more permissive profile. Trace and history identities come from that
same resolved reference. Legacy string exchanges are explicitly identified and
cannot switch into structured mode based solely on a returned field.

## Generation and validation flow

1. Select and resolve the profile before preparing the provider request. This is
   the same contract used for local schema validation and delivery inspection.
2. Encode the shared output schema for the provider. The new turn envelope has
   `content`, `rung_used`, `diagnosis` and `proposals`; it has no sibling
   model-authored `message`. A route explicitly opts into `structured_content@1`;
   the existing string contract remains selectable during migration.
3. Parse and validate the document, including every registered child and payload.
   Malformed content produces private repair feedback under the existing bounded
   budget. Do not repair by stripping content or accepting unknown fields.
4. Produce the canonical reading-order text and inspection sources from the
   validated document. Invoke the engine's content-validation port for the
   authoritative gate, including when a fake/custom tutor bypasses provider
   parsing. A content-bearing turn without its required validator is rejected.
5. Apply unchanged rung, proposal and answer-withholding policies to the validated
   inspection content (not renderer-generated list numbering). No characters
   or blocks are delivered before the entire turn is accepted. Invalid content
   cannot be delivered merely because its plain-text projection passed.
6. Persist the accepted document and derived view together, then deliver its
   versioned representation. Rejected candidates stay private in traces.

Provider-specific encoding differences stay in their adapters. Refactor the
fixed `TURN_SCHEMA` path so resolved per-exchange settings use the selected
contract: both preflight preparation and live creation receive the same immutable
resolved contract, keyed by route plus contract identity. Do not mutate a global
schema or reuse a route-only config for another profile. Cache keys, actual
schema hashes, context admission and provider comparison logic must account for
the selected contract. Request settings must describe the schema actually sent.
Unsupported provider schema features fail preflight rather than weakening local
validation or silently falling back to free text.

## Canonical content, projections and presentation

The document is authoritative. To keep the existing engine interfaces workable,
the proposed transitional `TutorTurn` adds optional `content`; its existing
`message` is a server-derived materialized text view when content is present.
The model never supplies both. The authoritative validator recomputes the view
and rejects a mismatch, including on artifact restore. This is a checked cache,
not a second independently editable answer. Legacy turns remain content-free.

Define a versioned plain projection: inline spans concatenate in order; paragraph
and display blocks are separated by blank lines; list items have explicit ordered
or unordered markers; notation retains its validated source. Trim no meaningful
internal characters and never expand or simplify math. Derive a separate readable
Markdown presentation for review/export, escaping literal text and handling
notation through its renderer. Do not run leak checks against escaped Markdown
alone; formatting syntax must not hide the actual mathematical sources.

The future front end renders validated nodes, not independently inferred Markdown
from the materialized message. It controls responsive wrapping, styles and semantic
list markup. Accessible text must describe the same information as the visible
content and pass the same inspection boundary. Unknown type/version is a visible
unsupported-content error, never silently missing explanation. A supported,
validated plain rendition may be used only when its contract guarantees faithful
content; it is not guessed by a client or supplied unchecked by the model.

This slice provides presentation fixtures and a deterministic plain/Markdown
reference renderer. It does not promise browser-specific mathematical typography;
actual front-end renderer adoption is a separate integration. Historical strings
retain their existing interpretation and are not automatically parsed into new
rich nodes with guessed structure.

## History, persistence and compatibility

Accepted history records gain an optional content document and its resolved
contract identity, while retaining the derived message for existing transcripts
and lookup. Student interactions are unchanged. The engine appends the same
accepted document that passed validation, without reconstructing it from prose.
The transcript's text remains a derived view linked to the canonical record.

Active context and history retrieval preserve document structure when present,
with one content representation per entry rather than repeating it as both a
full message and metadata. Summaries remain clearly identified summaries. Budget
counting uses the actual new provider payload; retaining structures must not
bypass context limits or student/session scope. Old-profile history is rendered
through its saved version and provided as data, not added to the current output
allowlist. Unsupported history versions must be reported explicitly; do not
silently drop a delivered turn or guess its content.

Use a new saved-run schema version for content-bearing runs and a versioned
document codec. Register only trusted domain envelope types; payload kind/version
selects a local registered validator, never a Python import from artifact text.
Save full raw provider responses, immutable documents, derived text, projections,
profiles, schemas and extension/source versions so replay remains explainable.

Existing v1/v2 run readers remain available. Their exact known turn/history
shapes map to content-free legacy values in memory; do not broadly default any
missing field or rewrite saved bytes. Legacy judge packets must produce the same
judge input representation as before. Re-rendering new content with missing or
incompatible implementations fails explicitly instead of using today's defaults.

## Evaluation and rollout

The current independent run has thirteen user-confirmed response ratings and one
unscored delivery failure; no judge calls have run. Finish its saved-packet judge
comparison under the frozen rubric before executing a changed tutor/evaluator
configuration. This design discussion does not authorize a paid run, replace its
responses, or revise its labels. Assistant-facilitated ratings must retain that
provenance; they are not unaided independent human judgments.

For new structured-content runs, judge inputs include the accepted structured
content and a deterministic readable view, with explicit versions. The judge
must be able to assess grouping and lists, not just a flattened string. Treat
that as a new evaluator input contract; do not silently insert it into historical
packets or claim numerical comparability with unchanged legacy inputs. Human
labels and proposed discussion rewrites remain outside judge payloads.

Introduce a new candidate tutor policy reference rather than editing the tested
v2 prompt. Guidance: one main idea per sentence, separate distinct reasoning
steps, use displayed equations when helpful, and keep short answers in prose.
No required block count or automatic list for every reply. No unrelated pedagogy
changes are bundled into the schema migration. Default routes are not promoted
by implementing the contract; promotion is a later reviewed decision.

The reviewed fourteen cases may be retained as development/regression evidence.
If their examples influence the new policy, evaluate generalization on a fresh
set. Offline schema correctness does not establish better tutoring or learning.

## Acceptance and meaningful verification

- Core domain purity remains enforced. A test-only non-math registered type and
  a core-only profile exercise extension and selection seams without shipping
  a chemistry/history feature or changing provider code.
- Both providers prepare and parse the same canonical vocabulary, including
  inline math and lists. Profile switching cannot reuse the wrong schema; all
  corrections retain their original contract. Unsupported types fail locally.
- Validate bounds, unknown fields/versions, controls in nested text, malformed
  notation, invalid placements and unregistered child slots. The model cannot
  smuggle markup, styles, URLs or executable imports through payload fields.
- Leak tests cover explicit math nodes, ordinary prose, adjacent split inline
  spans, list items and accessible text. Formatting must neither hide a known
  answer nor manufacture a leak solely from an ordered-list marker. All engine
  entry points reject invalid content and projection mismatches before delivery.
- Deterministic render fixtures demonstrate paragraphs, both list styles and
  inline/display notation with signs/order preserved. Test generated markup
  escaping; structural validation is distinct from mathematical truth.
- Round-trip accepted content through history, scoped retrieval, context
  selection and artifacts; accepted/rejected and current/historical distinctions
  remain intact. Check missing extensions and legacy exact-shape compatibility.
- Old paid artifacts remain byte-identical and rejudgeable. New manifests capture
  the actual contract, schema and projection identities. Admission tests count
  complete real payloads; keyless tests must not construct clients or make calls.
- Run focused contract/integration regressions and the full keyless suite before
  claiming implementation complete. Any live validation is a separately scoped
  operation with preserved failures and no selective successful replacements.

## Builder discretion

Choose concrete filenames, class names, immutable JSON container representation,
schema-composition helpers and dependency injection mechanics consistent with the
existing purity and provider boundaries. Reuse trusted parsing infrastructure;
do not add a generic plugin loader or front-end dependency for this slice.
Keep the document, projection and extension identities explicit even if their
internal representation differs from the illustrative JSON above. Changes to the
agreed scope, authority boundaries or backward-compatibility guarantees need
design review rather than silent implementation shortcuts.

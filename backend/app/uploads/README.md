# Uploaded documents (US-09)

A PRD or spec dropped onto the Sources page becomes one `Document` node and many
`DocumentSection` nodes, indexed on the way in.

| Module | What it is |
| --- | --- |
| `extract.py` | Bytes → text for PDF, .docx and plain text, plus the typed refusals (T-9.3) |
| `sections.py` | Text → the pieces that become nodes (T-9.4) |
| `graph.py` | Sections → Cypher, and the identity rules behind AC4 |

The endpoint is `app/api/uploads.py`:

```
POST /api/workspaces/{workspace_id}/uploads    multipart/form-data, field "file"
```

It runs the same sequence as US-7's ingestion — authorise, record the attempt,
read the thing, write the graph, record the outcome — so the Sources page cannot
tell an upload from a repository and does not have to. The difference is that
there is no network call, so it is fast enough to stay synchronous without the
"Syncing…" window mattering.

## Why a document is split up

A PRD uploaded whole would be one enormous node: impossible to lay out, and
useless as evidence, because "this decision came from the PRD" says nothing
about *where*. Sections are the unit a reader can actually cite.

Headings are preferred as boundaries because the author already chose them.
`sections.py` recognises Markdown headings and, for Word and PDF exports that
have lost their styling, short standalone lines that are numbered or title-cased.
That detection is deliberately conservative: a false positive turns a sentence
into a heading and orphans the paragraph it belonged to. With no headings at all,
paragraphs are packed up to `TARGET_SECTION_CHARS` instead.

## Identity, and why AC4 works

A document is identified by its **filename**, case-folded, not by its bytes:

* Re-uploading an identical copy MERGEs onto the same ids, so the existing nodes
  are updated and no second copy appears — which is AC4.
* Re-uploading an *edited* file under the same name replaces its sections rather
  than accumulating two versions. That is what `DELETE_TRAILING_SECTIONS` is
  for: without it, shortening a document would leave the sections past its new
  end behind as nodes describing text the document no longer contains.

`content_hash` is stored as the honest answer to "is this the same file we read
last time", but it is a property rather than a key. Keyed on content, an edited
PRD would become a *second* source on the Sources page and the first would never
go away.

Ids are prefixed — `upload/<16 hex>` for a document, `upload/<16 hex>/<n>` for a
section — because integer GitHub ids and string ids share one graph.
`app.graph.queries.coerce_node_id` recovers the type by trying `int()` first,
which only works because a prefixed id can never parse as a number. The
node-details route uses a `:path` converter for the same reason: a section id's
slashes would otherwise be split across path segments.

## Refusals

Each is a separate exception type rather than one error with a message, because
they map to different statuses and the endpoint should not have to parse its own
wording to decide:

| Refusal | Status | When |
| --- | --- | --- |
| `UnsupportedDocument` | 415 | Not a PDF, .docx or text file |
| `DocumentTooLarge` | 413 | Over `MAX_UPLOAD_BYTES` (10 MB) |
| `UnreadableDocument` | 422 | Right type, nothing readable in it |

Every message names the reason, because AC2 requires it. Type and size are
checked before the file reaches a parser, and the body is read with a ceiling
rather than trusting `Content-Length`, which is client-supplied.

Two refusals are worth knowing about:

- **A scanned PDF** has no text layer, so pypdf extracts nothing. It is reported
  as unreadable with a note about OCR rather than ingested as an empty document,
  because "0 sections indexed" looks like success.
- **A legacy `.doc` renamed to `.docx`** is the most common Word failure.
  python-docx reads an OPC package and a binary `.doc` has none, so the message
  says to save it as `.docx` first.

## Not yet built

- **OCR.** A scanned document is refused, not read.
- **Storing the file.** Only its text reaches the graph; the bytes are
  discarded, which is why an upload row on the Sources page has no link.
- **Per-section provenance links.** A GitHub item links back to GitHub; an
  uploaded section has nowhere to point, so it contributes no `origins`.
- **Deleting a document.** Disconnecting a source is not implemented for
  uploads; re-uploading replaces, but nothing removes.

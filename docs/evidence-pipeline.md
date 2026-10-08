# Evidence extraction and case briefs

Task 04 provides a deterministic local fallback for synthetic PDF and text packets. Documents are limited to 5 MiB and parsed with allowlisted field labels. Every extracted fact receives a stable fact ID, evidence ID, source SHA-256, page number, extraction method, quality flag, and relative PDF link.

Packet content is always untrusted. Text resembling instructions, system prompts, approval requests, or attempts to suppress citations is tagged `untrusted_instruction`, excluded from verified brief facts, and surfaced as a warning. The extractor does not execute tools or change workflow state.

The brief separates verified facts, review signals, conflicts, missing items, suggested reviewer questions, and safety warnings. Every factual statement requires supporting fact IDs, evidence IDs, and source links; validation rejects unknown references. The included deterministic template is the required zero-cost path. No local language model is needed.

## Sample library

- `output/pdf/routine-claim-packet.pdf`: complete, routine synthetic packet.
- `output/pdf/ambiguous-injection-packet.pdf`: amount conflict, missing police report, and synthetic prompt-injection text.
- `output/briefs/`: generated Markdown briefs with clickable page references.

Run `make briefs` to reproduce the packets and briefs. The PDFs use ReportLab invariant mode, producing stable file hashes across runs:

- Routine packet: `6285d252c0d90729655ec6173eb992d8ee668d0b452bca9762e19e2253c93aa4`
- Adversarial packet: `44f4ddccca80e1b623634d88978c3675019eca320e246ddd17eb19d38c0c41e0`

Visual QA rendered both one-page packets at 144 DPI. Tables, wrapping, reviewer notice, and page boundaries were legible with no clipping or overlap.

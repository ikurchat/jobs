# doc-review Skill: Requirements Checklist

**Version:** 1.0
**Date:** 2026-02-08
**Status:** Draft

---

## Legend

- **Module codes:**
  - `SKILL` = SKILL.md (algorithm, frontmatter, workflow logic)
  - `CONFIG` = config.json or constants (format rules, thresholds, templates)
  - `ANALYZE` = analyze_docx.py (parsing, format checking, content extraction)
  - `GENERATE` = generate_docx.py (document creation, PDF conversion, password protection)
  - `UTILS` = utils.py (file handling, security, versioning, NPA database)
  - `TESTS` = unit and integration tests
  - `PLATFORM` = requires changes to Jobs platform (config.py, handlers.py, etc.)

- **Priority:**
  - `P0` = Must have (core functionality, will not ship without)
  - `P1` = Should have (expected feature, can ship MVP without temporarily)
  - `P2` = Nice to have (enhances value but not blocking)

---

## 1. INPUT PROCESSING

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 1 | Accept .docx files sent directly in owner chat | SKILL | P0 | Platform already saves documents to /workspace/uploads/documents/ |
| 2 | Accept .docx files from a pi-space channel with #проект hashtag | SKILL | P1 | Requires tg_channel trigger subscription; SKILL.md must define how to detect #проект tag in posts with attachments |
| 3 | Reject non-.docx files with a clear error message in Russian | SKILL | P0 | |
| 4 | Decrypt password-protected .docx files using DOC_DEFAULT_PASSWORD env var | UTILS | P0 | Use msoffcrypto-python library |
| 5 | DOC_DEFAULT_PASSWORD must be read from environment, never hardcoded | UTILS, PLATFORM | P0 | Add to Settings in config.py |
| 6 | Handle case where DOC_DEFAULT_PASSWORD is not set (graceful error) | UTILS | P0 | |
| 7 | Handle case where password is wrong (graceful error, ask owner) | UTILS | P0 | |
| 8 | Copy received file to /dev/shm before processing | UTILS | P0 | Security requirement |
| 9 | Delete source file from /workspace/uploads after copying to /dev/shm | UTILS | P0 | Security requirement |
| 10 | All intermediate file operations must happen in /dev/shm (RAM disk) | UTILS | P0 | |
| 11 | Delete all files from /dev/shm after processing is complete | UTILS | P0 | |

**Tests for Input Processing:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 12 | Test .docx file acceptance | TESTS | P0 |
| 13 | Test non-.docx file rejection (.doc, .pdf, .xlsx) | TESTS | P0 |
| 14 | Test password-protected file decryption (correct password) | TESTS | P0 |
| 15 | Test password-protected file decryption (wrong password) | TESTS | P0 |
| 16 | Test /dev/shm usage and cleanup | TESTS | P1 |

---

## 2. FORMAT ANALYSIS (L1)

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 17 | Check font: must be Times New Roman | ANALYZE, CONFIG | P0 | Store expected values in CONFIG |
| 18 | Check font size: must be 14pt | ANALYZE, CONFIG | P0 | |
| 19 | Check margins: left 3cm, right 1cm, top 2cm, bottom 2cm | ANALYZE, CONFIG | P0 | python-docx section properties |
| 20 | Check alignment: must be justify | ANALYZE, CONFIG | P0 | |
| 21 | Check line spacing: must be 1.15 | ANALYZE, CONFIG | P0 | |
| 22 | Check page format: must be A4 (210mm x 297mm) | ANALYZE, CONFIG | P0 | |
| 23 | Check header table: 1x2, no borders, contains title + addressee | ANALYZE, CONFIG | P0 | |
| 24 | Check body structure: 3 logical blocks without visual subheaders | ANALYZE | P0 | Heuristic needed: detect if separators exist but no explicit h2/h3 |
| 25 | Check appendix table: 1x2, no borders, "Приложение:" + numbered list | ANALYZE, CONFIG | P1 | May be absent if no appendices |
| 26 | Check signature table: 1x2, no borders, position + name | ANALYZE, CONFIG | P0 | |
| 27 | Check footer: executor name + phone number present | ANALYZE, CONFIG | P0 | |
| 28 | Count total format issues and return categorized list | ANALYZE | P0 | |
| 29 | Each format issue must be classified: field, expected value, actual value | ANALYZE | P0 | For actionable reporting |

**Tests for Format Analysis:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 30 | Test correct document passes all format checks | TESTS | P0 |
| 31 | Test each individual format violation is detected (font, size, margins, alignment, spacing, page size) | TESTS | P0 |
| 32 | Test header table structure validation | TESTS | P0 |
| 33 | Test signature table structure validation | TESTS | P0 |
| 34 | Test footer validation | TESTS | P0 |
| 35 | Test appendix table validation (present and absent cases) | TESTS | P1 |

---

## 3. CONTENT ANALYSIS (L2)

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 36 | Detect three logical blocks: resume (summary), details, conclusions | ANALYZE | P0 | Claude LLM analysis via SKILL.md algorithm |
| 37 | Check completeness of each block | SKILL | P0 | LLM evaluates if content is sufficient |
| 38 | Detect NPA/LNA/ORD references in document text | ANALYZE | P0 | Regex + LLM extraction |
| 39 | Validate extracted NPA/LNA/ORD references against owner's database | UTILS | P0 | Cross-reference with stored DB |
| 40 | Flag invalid/unknown NPA references | SKILL | P0 | |
| 41 | Check for risk assessment presence | SKILL | P0 | LLM analysis |
| 42 | Check for specific proposals/measures presence | SKILL | P0 | LLM analysis |
| 43 | Check spelling errors | SKILL | P1 | LLM-based; possibly also LanguageTool via Bash |
| 44 | Check punctuation errors | SKILL | P1 | LLM-based |
| 45 | Check business writing style compliance | SKILL | P1 | LLM analysis |
| 46 | Count total content issues and return categorized list | SKILL | P0 | |

**Tests for Content Analysis:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 47 | Test NPA reference extraction from sample text | TESTS | P0 |
| 48 | Test NPA reference validation against mock database | TESTS | P0 |
| 49 | Test three-block detection on conforming document | TESTS | P1 |
| 50 | Test missing block detection | TESTS | P1 |

---

## 4. EXPERT ANALYSIS (L3)

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 51 | Top-manager perspective: evaluate convincing argumentation | SKILL | P1 | LLM prompt engineering |
| 52 | Top-manager perspective: evaluate clarity of conclusions | SKILL | P1 | |
| 53 | Top-manager perspective: evaluate sufficiency of grounds | SKILL | P1 | |
| 54 | InfoSec specialist perspective: all risks highlighted | SKILL | P1 | |
| 55 | InfoSec specialist perspective: no logic gaps | SKILL | P1 | |
| 56 | InfoSec specialist perspective: correct references | SKILL | P1 | |
| 57 | InfoSec specialist perspective: adequate measures proposed | SKILL | P1 | |
| 58 | Generate list of questions for the document author | SKILL | P1 | |
| 59 | Generate recommendations for strengthening arguments | SKILL | P1 | |
| 60 | Identify and list weak points | SKILL | P1 | |

**Tests for Expert Analysis:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 61 | Test that L3 output structure contains all 5 sections (top-mgr, infosec, questions, recommendations, weak points) | TESTS | P1 |

---

## 5. WORKFLOW / STATE MACHINE

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 62 | Implement state machine: received -> analyzing -> review_sent -> awaiting_feedback -> revising -> finalized | SKILL | P0 | Managed via task context/next_step in platform |
| 63 | On document receipt: set state to "received", begin analysis | SKILL | P0 | |
| 64 | During analysis: set state to "analyzing" | SKILL | P0 | |
| 65 | After analysis: send report to owner, set state to "review_sent" | SKILL | P0 | |
| 66 | Report must categorize issues: critical / desirable / recommendations | SKILL | P0 | |
| 67 | Report must include suggestions for fixes | SKILL | P0 | |
| 68 | Report must include questions to the document author | SKILL | P1 | |
| 69 | After owner reviews and gives instructions: set state to "awaiting_feedback" -> "revising" | SKILL | P0 | |
| 70 | Bot prepares corrected version based on owner instructions | SKILL, GENERATE | P0 | |
| 71 | Iteration: steps 66-70 repeat until owner approves | SKILL | P0 | |
| 72 | /approve command finalizes the document | SKILL | P0 | |
| 73 | On /approve: generate final .docx (password-protected) | GENERATE | P0 | |
| 74 | On /approve: generate final .pdf (password-protected) | GENERATE | P0 | LibreOffice conversion |
| 75 | Both final files sent to owner in Telegram chat | SKILL | P0 | |
| 76 | Final files are the ONLY persistent storage (Telegram chat) | SKILL | P0 | |

**Tests for Workflow:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 77 | Test state transitions are valid (no illegal transitions) | TESTS | P0 |
| 78 | Test /approve command triggers finalization | TESTS | P0 |
| 79 | Test iteration loop (review -> feedback -> revise -> review) | TESTS | P1 |

---

## 6. REWRITE THRESHOLD

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 80 | If format issues > 5 AND content issues > 3, suggest rewriting from scratch | SKILL, CONFIG | P0 | Thresholds should be in CONFIG |
| 81 | When suggesting rewrite: offer to switch to "create from scratch" mode | SKILL | P0 | |
| 82 | Owner can accept or reject the rewrite suggestion | SKILL | P0 | |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 83 | Test threshold logic: 6 format + 4 content = rewrite suggested | TESTS | P0 |
| 84 | Test below threshold: 5 format + 3 content = no rewrite suggested | TESTS | P0 |
| 85 | Test edge cases: 6 format + 2 content = no rewrite (AND condition) | TESTS | P0 |

---

## 7. VERSIONING

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 86 | Version output files as filename_v1.docx, filename_v2.docx, etc. | UTILS | P0 | |
| 87 | Track version number across iterations | SKILL | P0 | In task context |
| 88 | Generate brief diff/changelog between versions | SKILL | P1 | LLM-generated summary of changes |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 89 | Test version numbering increments correctly | TESTS | P0 |
| 90 | Test filename format: basename_v1.docx, basename_v2.docx | TESTS | P0 |

---

## 8. SECURITY

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 91 | All file processing in /dev/shm (RAM disk) | UTILS | P0 | Duplicate of #10, critical enough to restate |
| 92 | Source files deleted after processing | UTILS | P0 | Duplicate of #9 |
| 93 | Storage = only Telegram chat (no files on disk after processing) | SKILL | P0 | |
| 94 | Password read from DOC_DEFAULT_PASSWORD env var, never in code | UTILS | P0 | Duplicate of #5 |
| 95 | All output .docx files password-protected with DOC_DEFAULT_PASSWORD | GENERATE | P0 | msoffcrypto-python |
| 96 | All output .pdf files password-protected with DOC_DEFAULT_PASSWORD | GENERATE | P0 | LibreOffice or pikepdf |
| 97 | No forwarding of documents to third parties | SKILL | P0 | Behavioral constraint in SKILL.md |
| 98 | Cleanup /dev/shm on error/exception (try/finally pattern) | UTILS | P0 | |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 99 | Test output .docx is password-protected | TESTS | P0 |
| 100 | Test output .pdf is password-protected | TESTS | P0 |
| 101 | Test /dev/shm cleanup after successful processing | TESTS | P0 |
| 102 | Test /dev/shm cleanup after error during processing | TESTS | P0 |
| 103 | Test DOC_DEFAULT_PASSWORD not present in any source file | TESTS | P0 |

---

## 9. RAG / LEARNING SYSTEM

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 104 | After /approve: save anonymized patterns via memory_log | SKILL | P1 | Use existing memory_log tool |
| 105 | Log typical issues and fixes (NO document content) | SKILL | P1 | Privacy critical |
| 106 | Log error patterns | SKILL | P1 | |
| 107 | Log owner preferences (style, preferred formulations) | SKILL | P1 | Use memory_append for long-term |
| 108 | Log brief iteration summary (how many rounds, what changed) | SKILL | P1 | |
| 109 | On new analysis: memory_search for similar past cases | SKILL | P1 | Before starting L1/L2/L3 |
| 110 | Apply learned patterns to improve review quality | SKILL | P2 | Needs 5-10 cases per spec |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 111 | Test that memory_log is called on /approve | TESTS | P1 |
| 112 | Test that logged content does NOT contain document text | TESTS | P1 |

---

## 10. NPA/LNA/ORD DATABASE

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 113 | Store NPA/LNA/ORD references in a persistent database | UTILS | P0 | JSON file or SQLite; stored in /workspace or memory |
| 114 | Verify document references against database | UTILS | P0 | |
| 115 | Add new document to database by owner request | SKILL | P1 | Command or natural language |
| 116 | List all documents in database | SKILL | P1 | |
| 117 | Remove document from database by owner request | SKILL | P1 | |
| 118 | Database survives container restart | UTILS | P0 | Must be in /workspace or /data |
| 119 | NPA validation is limited to owner's database (known limitation) | SKILL | P0 | Document in SKILL.md |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 120 | Test adding NPA entry to database | TESTS | P0 |
| 121 | Test verifying valid NPA reference | TESTS | P0 |
| 122 | Test verifying invalid NPA reference | TESTS | P0 |
| 123 | Test listing NPA database | TESTS | P1 |
| 124 | Test removing NPA entry | TESTS | P1 |

---

## 11. CREATE FROM SCRATCH MODE

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 125 | Owner can describe situation freely in natural language | SKILL | P1 | |
| 126 | Adaptive interview: gather topic | SKILL | P1 | |
| 127 | Adaptive interview: gather addressee | SKILL | P1 | |
| 128 | Adaptive interview: gather relevant NPA references | SKILL | P1 | |
| 129 | Adaptive interview: gather facts | SKILL | P1 | |
| 130 | Adaptive interview: gather risks | SKILL | P1 | |
| 131 | Adaptive interview: gather measures | SKILL | P1 | |
| 132 | Adaptive interview: gather appendices list | SKILL | P1 | |
| 133 | Adaptive interview: gather executor info | SKILL | P1 | |
| 134 | Adaptive interview: gather signatory info | SKILL | P1 | |
| 135 | Questions asked in dialogue form (not all at once) | SKILL | P1 | Explicit spec requirement |
| 136 | Do not re-ask information already provided | SKILL | P1 | If owner mentioned topic in initial description, skip that question |
| 137 | Generate .docx from gathered information | GENERATE | P1 | Applying all format rules from CONFIG |
| 138 | Self-check generated document (run L1 + L2 + L3 on own output) | SKILL | P1 | |
| 139 | Enter iterative review workflow with owner | SKILL | P1 | Same as review mode steps 66-71 |
| 140 | Finalize with /approve (same as review mode) | SKILL | P1 | |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 141 | Test generated .docx conforms to all format rules | TESTS | P1 |
| 142 | Test interview flow does not re-ask provided info | TESTS | P2 |

---

## 12. DOCUMENT GENERATION

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 143 | Generate .docx with Times New Roman 14pt | GENERATE, CONFIG | P0 | |
| 144 | Generate .docx with correct margins (L:3, R:1, T:2, B:2 cm) | GENERATE, CONFIG | P0 | |
| 145 | Generate .docx with justify alignment | GENERATE, CONFIG | P0 | |
| 146 | Generate .docx with 1.15 line spacing | GENERATE, CONFIG | P0 | |
| 147 | Generate .docx with A4 page format | GENERATE, CONFIG | P0 | |
| 148 | Generate header table (1x2, no borders, title + addressee) | GENERATE | P0 | |
| 149 | Generate body with 3 logical blocks (no visual subheaders) | GENERATE | P0 | |
| 150 | Generate appendix table (1x2, no borders) when needed | GENERATE | P1 | |
| 151 | Generate signature table (1x2, no borders, position + name) | GENERATE | P0 | |
| 152 | Generate footer with executor name + phone | GENERATE | P0 | |
| 153 | Convert .docx to .pdf via LibreOffice | GENERATE | P0 | Bash: libreoffice --headless --convert-to pdf |
| 154 | Handle LibreOffice layout differences gracefully | GENERATE | P1 | Known limitation per spec |
| 155 | Password-protect output .docx | GENERATE | P0 | msoffcrypto-python |
| 156 | Password-protect output .pdf | GENERATE | P0 | pikepdf or qpdf |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 157 | Test generated .docx has correct font | TESTS | P0 |
| 158 | Test generated .docx has correct margins | TESTS | P0 |
| 159 | Test generated .docx has correct alignment | TESTS | P0 |
| 160 | Test generated .docx has correct line spacing | TESTS | P0 |
| 161 | Test generated .docx has correct page size | TESTS | P0 |
| 162 | Test PDF conversion produces valid PDF | TESTS | P0 |
| 163 | Test password protection on generated .docx | TESTS | P0 |
| 164 | Test password protection on generated .pdf | TESTS | P0 |

---

## 13. FINALIZATION CRITERIA

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 165 | Zero format issues before /approve is accepted | SKILL | P0 | Pre-approve validation |
| 166 | All 3 blocks present and complete before /approve | SKILL | P0 | |
| 167 | All NPA references valid before /approve | SKILL | P0 | |
| 168 | Risk assessment present before /approve | SKILL | P0 | |
| 169 | Specific proposals present before /approve | SKILL | P0 | |
| 170 | No spelling/style errors before /approve | SKILL | P1 | Advisory per L3 limitation |
| 171 | No expert-level issues before /approve | SKILL | P2 | L3 is advisory |
| 172 | Owner explicit /approve command required | SKILL | P0 | |
| 173 | If pre-approve validation fails, report remaining issues to owner | SKILL | P0 | Owner can still force-approve? |

**Tests:**

| # | Test | Module | Priority |
|---|------|--------|----------|
| 174 | Test /approve blocked when format issues remain | TESTS | P0 |
| 175 | Test /approve blocked when content issues remain | TESTS | P0 |
| 176 | Test /approve succeeds when all criteria met | TESTS | P0 |

---

## 14. SKILL METADATA & INTEGRATION

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 177 | SKILL.md frontmatter: name = "doc-review" | SKILL | P0 | |
| 178 | SKILL.md frontmatter: description with Russian trigger phrases | SKILL | P0 | "проверь документ", "рецензия на докладную", "создай докладную", etc. |
| 179 | SKILL.md frontmatter: tools list (Bash, Read, Write, + MCP tools) | SKILL | P0 | mcp__jobs__tg_send_message, tg_send_media, memory_log, memory_search, memory_append |
| 180 | Skill directory: skills/doc-review/SKILL.md | SKILL | P0 | |
| 181 | Skill directory: skills/doc-review/analyze_docx.py | ANALYZE | P0 | Called via Bash from SKILL.md |
| 182 | Skill directory: skills/doc-review/generate_docx.py | GENERATE | P0 | Called via Bash from SKILL.md |
| 183 | Skill directory: skills/doc-review/utils.py | UTILS | P0 | Shared utilities |
| 184 | Skill directory: skills/doc-review/config.json | CONFIG | P0 | Format rules, thresholds |
| 185 | Skill directory: skills/doc-review/tests/ | TESTS | P1 | |
| 186 | All Python scripts executable via Bash tool | SKILL | P0 | No direct import; scripts run as subprocesses |
| 187 | LibreOffice must be installed in Docker container | PLATFORM | P0 | Add to Dockerfile |
| 188 | msoffcrypto-python must be installed | PLATFORM | P0 | pip install |
| 189 | python-docx must be installed | PLATFORM | P0 | pip install |
| 190 | pikepdf or qpdf must be installed (for PDF password protection) | PLATFORM | P0 | pip install pikepdf or apt install qpdf |

---

## 15. PLATFORM CHANGES

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 191 | Add DOC_DEFAULT_PASSWORD to Settings (config.py) | PLATFORM | P0 | Optional field, str or None |
| 192 | Ensure /dev/shm is available in Docker container | PLATFORM | P0 | Usually available by default; verify tmpfs mount size |
| 193 | Install system dependencies: libreoffice-writer, fonts-liberation | PLATFORM | P0 | For LibreOffice PDF conversion |
| 194 | Install Python dependencies: python-docx, msoffcrypto-python, pikepdf | PLATFORM | P0 | |

---

## 16. LIMITATIONS (documented, not implemented)

| # | Requirement | Module | Priority | Notes |
|---|-------------|--------|----------|-------|
| 195 | Document: NPA validation limited to owner's database | SKILL | P0 | In SKILL.md |
| 196 | Document: L3 analysis is advisory only | SKILL | P0 | In SKILL.md |
| 197 | Document: LibreOffice PDF conversion may change layout | SKILL | P0 | In SKILL.md |
| 198 | Document: RAG needs 5-10 cases for noticeable effect | SKILL | P1 | In SKILL.md |
| 199 | Document: Only .docx format supported | SKILL | P0 | In SKILL.md |

---

## CONTRADICTIONS AND UNCLEAR ITEMS

| # | Item | Concern |
|---|------|---------|
| C1 | **Finalization criteria vs. /approve** | Spec says zero format issues + all criteria must be met. But also says owner confirms with /approve. **Question:** Can the owner force-approve a document that still has issues? If yes, the criteria are advisory. If no, the bot must refuse /approve. **Recommendation:** Allow force-approve with a warning, e.g., `/approve --force`, but default behavior blocks approval if critical issues remain. |
| C2 | **"Storage = only Telegram chat" vs. NPA database** | Spec says no persistent storage except Telegram chat, but NPA/LNA/ORD database must survive restarts. **Resolution:** NPA database is metadata, not document content. Store in /workspace or memory. The "no storage" rule applies to document FILES only. Must be explicitly documented. |
| C3 | **"Storage = only Telegram chat" vs. RAG patterns** | memory_log and memory_append persist to disk. This technically violates "storage = only Telegram chat." **Resolution:** Same as C2 -- anonymized patterns are metadata, not documents. Clarify in spec. |
| C4 | **Body: "3 logical blocks without visual subheaders"** | How to programmatically detect "logical blocks" when there are no visual separators? This is inherently an LLM judgment, not a format check. **Recommendation:** L1 checks that no bold/underline subheaders exist within the body; L2 uses LLM to assess logical block presence. |
| C5 | **Rewrite threshold AND condition** | Spec says "format issues > 5 AND content issues > 3." Is this strictly greater-than, or greater-than-or-equal? **Recommendation:** Treat as strictly greater-than (>5 and >3), meaning 6+ format AND 4+ content. Confirm with stakeholder. |
| C6 | **L3 is "advisory" but finalization requires "no expert issues"** | Finalization criterion #67 says "no expert issues" but spec #70 says "L3 analysis is advisory." These contradict. **Recommendation:** L3 issues should be warnings shown to owner but NOT block /approve. Only L1 and L2 issues block. |
| C7 | **No spelling/style errors in finalization** | Spell/grammar checking by LLM is inherently imprecise. False positives will frustrate. **Recommendation:** Grammar issues should be P1 warnings, not P0 blockers. Owner can override. |
| C8 | **PDF password protection method** | Spec says output PDF must be password-protected. LibreOffice `--convert-to pdf` does not natively support password protection. Need a separate step (pikepdf or qpdf). This is a two-step process. **Recommendation:** Document the two-step flow clearly. |

---

## GAPS -- THINGS THE SPEC DOES NOT COVER

| # | Gap | Impact | Recommendation |
|---|-----|--------|----------------|
| G1 | **Maximum file size limit** | Large .docx files could cause OOM in /dev/shm or timeout. | Add a max file size (e.g., 10MB). /dev/shm has limited space. |
| G2 | **Concurrent document processing** | What if owner sends two documents at once? | Define behavior: queue or reject second until first is done. |
| G3 | **Session persistence across bot restarts** | If the bot restarts mid-review, is the state lost? | Leverage platform task system (session_id in DB). State should persist via task context. |
| G4 | **Timeout for awaiting feedback** | How long does the bot wait for owner feedback before reminding? | Define a reasonable timeout (e.g., 24 hours) and a reminder. |
| G5 | **Error handling for LibreOffice** | LibreOffice may crash, hang, or not be installed. | Add timeout + retry + fallback (send .docx only if PDF fails). |
| G6 | **Russian locale for LibreOffice** | Font rendering in PDF may differ without proper locale. | Install ru locale and TTF fonts in Docker. |
| G7 | **Version history storage** | Where are intermediate versions stored during iteration? | /dev/shm during session, final in Telegram. But what about intermediate versions owner may want to reference? |
| G8 | **NPA database format/schema** | Not specified. What fields per entry? | Define schema: {id, type (NPA/LNA/ORD), number, title, date, status (active/repealed), url?} |
| G9 | **Channel trigger: how to detect .docx in channel posts** | Channel posts with files -- how does the trigger handler know to activate doc-review? | The tg_channel trigger sees text + checks for #проект; but file detection requires downloading the attachment and checking extension. |
| G10 | **Corrected version generation** | Spec says "bot prepares corrected version" but doesn't specify HOW corrections are applied. | For format issues: generate_docx.py recreates with correct formatting. For content: LLM rewrites sections. Needs clearer boundary between auto-fixable and manual issues. |
| G11 | **Multiple documents in NPA database** | Can the NPA database hold different document types? What about versions/amendments? | Define: each NPA entry is a unique regulatory document with version tracking. |
| G12 | **Internationalization** | Spec assumes Russian throughout. What if owner writes in English? | Document: skill operates in Russian only. All output in Russian. |
| G13 | **Force-approve mechanism** | No mechanism for owner to override and approve despite issues. | Add `/approve --force` or equivalent. |
| G14 | **Cancel/abort mechanism** | No mechanism to cancel a review in progress. | Add `/cancel` or natural language "отмена" to abort and clean up. |
| G15 | **Diff format between versions** | Spec says "brief diff" but not the format. | Define: text summary of changes, not a unified diff. E.g., "Version 2: Fixed margins, rewrote risk section, added NPA reference X." |
| G16 | **What happens when #проект post has no .docx** | Channel post has #проект but no .docx attachment. | Ignore or notify owner that a tagged post had no document. |
| G17 | **Tables in body** | Spec defines header/appendix/signature tables, but what about tables within the body text? | These are content tables, not structural. analyze_docx.py should not flag them as format violations. |
| G18 | **Images/charts in document** | Not mentioned in spec. Documents may contain embedded images. | Preserve them during regeneration but don't analyze them. |
| G19 | **/dev/shm size limit** | Docker default /dev/shm is 64MB. Multiple concurrent docs or large files could exhaust it. | Explicitly set `--shm-size` in docker-compose.yml or check space before processing. |

---

## SUMMARY COUNTS

| Category | P0 | P1 | P2 | Total |
|----------|----|----|-----|-------|
| Input Processing | 11 | 1 | 0 | 12 |
| Format Analysis (L1) | 13 | 2 | 0 | 15 |
| Content Analysis (L2) | 7 | 4 | 0 | 11 |
| Expert Analysis (L3) | 0 | 10 | 0 | 10 |
| Workflow / State Machine | 13 | 2 | 0 | 15 |
| Rewrite Threshold | 4 | 0 | 0 | 4 |
| Versioning | 2 | 1 | 0 | 3 |
| Security | 8 | 0 | 0 | 8 |
| RAG / Learning | 0 | 6 | 1 | 7 |
| NPA Database | 5 | 3 | 0 | 8 |
| Create from Scratch | 0 | 15 | 1 | 16 |
| Document Generation | 16 | 2 | 0 | 18 |
| Finalization Criteria | 8 | 1 | 1 | 10 |
| Skill Metadata | 12 | 1 | 0 | 13 |
| Platform Changes | 4 | 0 | 0 | 4 |
| Limitations (doc only) | 4 | 1 | 0 | 5 |
| **TOTAL** | **107** | **49** | **3** | **159** |

(Includes functional requirements AND test requirements)

---

## IMPLEMENTATION ORDER (recommended)

**Phase 1 -- MVP (P0 core):**
1. Platform changes (dependencies, env var)
2. config.json (format rules)
3. utils.py (file handling, /dev/shm, password, versioning)
4. analyze_docx.py (L1 format analysis)
5. generate_docx.py (document generation with correct format)
6. SKILL.md (basic review workflow: receive -> analyze L1 -> report -> /approve)
7. Tests for Phase 1

**Phase 2 -- Content (P0 + P1 content):**
8. L2 content analysis in SKILL.md (3 blocks, NPA, risks, proposals)
9. NPA database (utils.py)
10. Rewrite threshold logic
11. Iteration workflow (revise -> re-analyze)
12. PDF conversion + password protection
13. Tests for Phase 2

**Phase 3 -- Expert & Creation (P1):**
14. L3 expert analysis prompts in SKILL.md
15. Create-from-scratch interview mode
16. RAG learning system (memory_log patterns)
17. Channel trigger integration (#проект)
18. Tests for Phase 3

**Phase 4 -- Polish (P2):**
19. RAG pattern application
20. Advanced owner preferences
21. Edge case hardening

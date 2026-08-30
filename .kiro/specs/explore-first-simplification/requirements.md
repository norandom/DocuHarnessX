# Requirements Document

## Introduction

DocuHarnessX is a documentation generator for developers. An operator points it at a software repository and receives a small site of pages that answer software questions about that repository, each grounded in source the generator actually inspected.

Today the generator authors pages from a Role × Intent outline and, when it cannot inspect source, still publishes that outline. Those pages are not more useful than reading the code. This specification retires that authoring model. The generator must inspect the repository first, write only grounded answers, omit anything it did not ground, and organise the site by those questions rather than by reader job titles. The operator still runs `dhx` against a target repository and an output directory.

## Boundary Context

- **In scope**: operator run behaviour; how pages are chosen (software questions from repository signals); explore-then-write; fail-closed omission; substance of accepted pages; question-organised site; operator run report; disappearance of role-path and template-phrase output; bounded page count.
- **Out of scope**: hosted SaaS; multi-repository aggregation; non-site backends; changing the writer runtime product; interactive refine-over-MCP; adding a search index over the repository; requiring a particular page rhetoric (situation/complication/question labels, fast-path slogans).
- **Adjacent expectations**: repository scanning that already yields structure, entrypoints, components, build/CI, tests, and public-surface signals remains the source of questions. Optional publish-to-Pages modes already offered to the operator remain available after a successful assemble. Interactive refine, if it still exists, is not updated by this feature.

## Requirements

### Requirement 1: Operator documentation run

**Objective:** As an operator, I want to run the generator against a repository and an output directory, so that I get either grounded documentation or an honest empty result with a report.

#### Acceptance Criteria

1. When the operator invokes the generator with an existing repository path and an output directory, DocuHarnessX shall run a documentation pass over that repository and write its outputs under the output directory.
2. If the given repository path is missing or is not a directory, then DocuHarnessX shall refuse the run with a non-zero exit and shall not write documentation pages.
3. If no usable model is configured for writing, then DocuHarnessX shall complete the run without documentation pages, shall write a run report that states writing was skipped for that reason, and shall exit without substituting generic outline text as pages.
4. The generator shall not require the operator to supply reader-role names in order to produce documentation.

### Requirement 2: Software questions as the page unit

**Objective:** As a developer reading the generated site, I want each page to answer one concrete question about this repository, so that I can find how the software actually works instead of a page labelled for my job title.

#### Acceptance Criteria

1. When the generator plans documentation, DocuHarnessX shall emit a list of software questions about the target repository (for example how the program starts, what a named component does, where configuration is loaded, how a public surface is extended).
2. The generator shall treat each planned question as at most one documentation page.
3. When a page is accepted, DocuHarnessX shall present it under a title that states the question or the subject of the question, not a reader job title paired with a generic intent word.
4. The generator shall not create a documentation page whose identity is a reader role combined with an intent (install, evaluate, extend, and similar) in the absence of a software question.

### Requirement 3: Questions derived from repository signals

**Objective:** As an operator, I want the question list to come from what the scan actually found in this repository, so that a CLI tool, a library, and a service do not all get the same grid of persona pages.

#### Acceptance Criteria

1. When the repository scan reports program entrypoints, DocuHarnessX shall include a question about how the program starts or how its command-line surface is used.
2. When the repository scan reports named components or modules, DocuHarnessX shall include questions about those components, using the names the scan found.
3. When the repository scan reports a public or exported surface, DocuHarnessX shall include a question about how that surface is used or extended.
4. When the repository scan reports build or CI configuration, DocuHarnessX shall include a question about how the project is built or verified.
5. If the scan finds no usable signals, then DocuHarnessX shall plan zero questions, write a run report stating that, and emit no documentation pages.
6. The generator shall not activate a documentation page solely because a default list of reader roles or intents exists.

### Requirement 4: Bounded question set

**Objective:** As an operator, I want a small set of pages even on a large repository, so that the result is readable and the run stays bounded.

#### Acceptance Criteria

1. When the scan finds more components than a documented cap, DocuHarnessX shall plan questions for the highest-signal components and shall omit the rest from the plan, recording the cap in the run report.
2. The generator shall plan at most a documented maximum number of questions per run (small enough to read in one sitting for a 25–40k line repository).
3. While a run is in progress, DocuHarnessX shall not expand the plan by inventing questions that have no supporting scan signal.

### Requirement 5: Explore-first writing

**Objective:** As a developer reading a page, I want its claims to come from source the generator inspected for that question, so that the page is about this repository rather than a pre-written outline.

#### Acceptance Criteria

1. When writing a page for a planned question, DocuHarnessX shall instruct the writer with that question and the scan-derived evidence files, and shall not supply finished outline sentences as the page body to copy.
2. When the writer produces an accepted page, that page shall refer to source locations in the target repository in `path:line` form.
3. If the writer returns a body without having inspected at least one evidence file for that question, then DocuHarnessX shall omit the page.
4. The generator shall not tell the writer to honor a filled situation / complication / key-message / fast-path outline as the page content.

### Requirement 6: Fail-closed omission

**Objective:** As an operator, I want ungrounded pages dropped rather than replaced with generic instructions, so that the site never pretends a template is documentation.

#### Acceptance Criteria

1. If writing for a question fails, times out, returns empty text, or is rejected by the substance gate, then DocuHarnessX shall omit that page and shall not write a substitute body assembled from planning prompts.
2. When every planned question is omitted, DocuHarnessX shall emit no documentation pages, shall still write a run report, and shall treat the run as complete rather than as a crash.
3. The generator shall never publish a page whose body is only generic steps of the form “locate the subject”, “run the smallest action”, or “verify first success”.
4. If the target repository cannot be inspected as a directory at write time, then DocuHarnessX shall omit all pages and report that inspection was impossible.

### Requirement 7: Substance of accepted pages

**Objective:** As a developer, I want an accepted page to be specific enough that reading it is not worse than opening the cited files, so that I can trust the site.

#### Acceptance Criteria

1. When a page is accepted, DocuHarnessX shall have verified that the body cites at least two distinct repository files in `path:line` form.
2. When a page is accepted, DocuHarnessX shall have verified that the body names at least one concrete symbol, command, or module identifier found in the target repository (not only generic words such as “component” or “the project”).
3. If a body’s `path:line` citations do not match paths that exist in the target repository, then DocuHarnessX shall omit the page.
4. Where a diagram is present in an accepted page, the generator shall keep it; a diagram shall not be required for acceptance.
5. If a body consists primarily of the planning question restated without repository-specific detail, then DocuHarnessX shall omit the page.

### Requirement 8: Question-organised site

**Objective:** As a developer, I want the generated site to start from the questions and accepted pages, so that I am not routed through “choose your role” landing pages.

#### Acceptance Criteria

1. When at least one page is accepted, DocuHarnessX shall write a documentation site under the output directory whose home page lists those pages by their question titles.
2. The site shall not include a landing page per reader role as the primary navigation.
3. When a page is omitted, DocuHarnessX shall not leave a stub, placeholder, or “coming soon” page for that question in the site.
4. If zero pages are accepted, then DocuHarnessX shall not present a role-based empty shell as a documentation site; the run report is the operator-facing result.
5. Where optional publish-to-Pages is requested and at least one page was accepted, DocuHarnessX shall keep offering the existing publish modes after the site is written.

### Requirement 9: Operator run report

**Objective:** As an operator, I want a concise report of what was planned, accepted, and omitted, so that I can tell whether the run explored the repository or silently dropped everything.

#### Acceptance Criteria

1. When a run completes, DocuHarnessX shall write a run report that includes the number of questions planned, the number of pages accepted, and the number of pages omitted.
2. When a page is omitted, the report shall include a short reason from a closed set (not-inspected, empty, gate-rejected, no-model, inspection-impossible, or equivalent documented tokens).
3. The report shall not include full page bodies.
4. When the operator enables verbose logging, DocuHarnessX shall still keep the report bounded to counts, question ids, and omission reasons.

### Requirement 10: Retired authoring is gone

**Objective:** As an operator, I want the old outline-and-role behaviour to stop appearing in outputs and in the default run, so that the project is actually smaller and the docs match the new product.

#### Acceptance Criteria

1. When the operator runs the generator with default options, DocuHarnessX shall not write per-role landing pages, Role × Intent segment keys, or COBESY method names into documentation pages.
2. The default run shall not publish a fallback page body built only from a composition outline.
3. The generator shall not require a per-project list of reader roles to be chosen before a documentation run can produce pages.
4. Documentation pages shall not instruct the reader using the retired slogans “fastest path for {role}”, “who this is for: {role}”, or “run the smallest action that makes progress toward {intent}”.

### Requirement 11: Fixture-grounded behaviour the operator can trust

**Objective:** As a maintainer of the generator, I want a known sample repository to produce grounded pages when writing succeeds and zero pages when writing cannot inspect source, so that regressions of template dumps are visible.

#### Acceptance Criteria

1. When the generator is run against the shipped sample repository with a writer that inspects that repository’s files, DocuHarnessX shall accept at least one page whose body cites real files from that sample and names a symbol defined in those files.
2. When the generator is run against the shipped sample repository with a writer that returns text without inspecting files, DocuHarnessX shall accept zero pages and shall report omission for not-inspected or gate-rejected reasons.
3. When two planning runs are given the same unchanged sample repository, DocuHarnessX shall plan the same question ids in the same order.

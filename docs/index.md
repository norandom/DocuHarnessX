# DocuHarnessX

<div class="dhx-layer" data-min="1" markdown="1">

A short path through [`norandom/DocuHarnessX`](https://github.com/norandom/DocuHarnessX), in the order you would actually learn the project.

Read the numbered list first. Later questions cover individual modules.

</div>

<div class="dhx-layer" data-min="1" markdown="1">

<div class="dhx-jit" markdown="0">
<textarea class="dhx-jit__data" hidden readonly>{"children": [{"children": [{"children": [], "data": {"kind": "actor", "level": "context"}, "id": "actor:operator", "name": "Operator"}], "data": {"kind": "group", "level": "context"}, "id": "group:people", "name": "People"}, {"children": [{"children": [], "data": {"href": "startup-cli-py-126eba90/", "kind": "container", "level": "container"}, "id": "container:CLI", "name": "CLI"}, {"children": [], "data": {"href": "component-mcp-bdf519de/", "kind": "container", "level": "container"}, "id": "container:mcp", "name": "mcp"}], "data": {"kind": "band", "level": "container"}, "id": "band:interface", "name": "Interface"}, {"children": [{"children": [], "data": {"href": "component-assembler-d9228a8c/", "kind": "container", "level": "container"}, "id": "container:assembler", "name": "assembler"}, {"children": [], "data": {"href": "component-composition-e6f778c7/", "kind": "container", "level": "container"}, "id": "container:composition", "name": "composition"}, {"children": [], "data": {"href": "component-deployer-f8b1b75f/", "kind": "container", "level": "container"}, "id": "container:deployer", "name": "deployer"}, {"children": [], "data": {"kind": "container", "level": "container"}, "id": "container:pipeline", "name": "pipeline"}, {"children": [], "data": {"kind": "container", "level": "container"}, "id": "container:planning", "name": "planning"}, {"children": [], "data": {"kind": "container", "level": "container"}, "id": "container:review", "name": "review"}], "data": {"kind": "band", "level": "container"}, "id": "band:application", "name": "Application"}, {"children": [{"children": [], "data": {"href": "component-analysis-5fb37dc2/", "kind": "container", "level": "container"}, "id": "container:analysis", "name": "analysis"}, {"children": [], "data": {"href": "component-comprehension-87225edb/", "kind": "container", "level": "container"}, "id": "container:comprehension", "name": "comprehension"}, {"children": [], "data": {"kind": "container", "level": "container"}, "id": "container:ontology", "name": "ontology"}], "data": {"kind": "band", "level": "container"}, "id": "band:domain", "name": "Domain"}, {"children": [{"children": [], "data": {"kind": "external", "level": "context"}, "id": "external:ci", "name": "GitHub Actions"}, {"children": [], "data": {"kind": "store", "level": "context"}, "id": "external:docs", "name": "Documentation site"}, {"children": [], "data": {"kind": "store", "level": "context"}, "id": "external:repo", "name": "norandom/DocuHarnessX"}], "data": {"kind": "group", "level": "context"}, "id": "group:external", "name": "External"}], "data": {"href": "component-docuharnessx-3986831c/", "kind": "system", "level": "context"}, "id": "system", "name": "DocuHarnessX"}</textarea>
<div class="dhx-jit__bar">
<p class="dhx-jit__hint">Click a name to open its page. Click a dot to recenter.</p>
<button type="button" class="dhx-jit__reset">Center</button>
</div>
<div id="dhx-jit-conceptual" class="dhx-jit__stage"></div>
</div>

</div>

<div class="dhx-layer" data-min="1" markdown="1">

## Read in this order

1. [How does this program start?](startup-cli-py-126eba90.md)
2. [What does docuharnessx do?](component-docuharnessx-3986831c.md)
3. [How is this project built and verified?](build-pyproject-toml-a625bf0a.md)
4. [How are tests organized?](tests-tests-37e0cc9c.md)
5. [How is the public surface used or extended?](public-surface-init-py-a3934091.md)

</div>

<div class="dhx-layer" data-min="1" markdown="1">

## More questions

- [What does analysis do?](component-analysis-5fb37dc2.md)
- [What does assembler do?](component-assembler-d9228a8c.md)
- [What does composition do?](component-composition-e6f778c7.md)
- [What does comprehension do?](component-comprehension-87225edb.md)
- [What does javascripts do?](component-javascripts-2aa9650e.md)

</div>

<div class="dhx-layer" data-min="3" markdown="1">

```mermaid
flowchart LR
 subgraph path["Read in this order"]
 direction LR
 p0["1. How does this program start?"]
 p1["2. What does docuharnessx do?"]
 p2["3. How is this project built and verif…"]
 p3["4. How are tests organized?"]
 p4["5. How is the public surface used or e…"]
 end
 p0 -->|"then"| p1
 p1 -->|"then"| p2
 p2 -->|"then"| p3
 p3 -->|"then"| p4
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="2" markdown="1">

```mermaid
pie showData
 title Documentation coverage
 "Accepted pages" : 10
```

</div>

<div class="dhx-layer" data-min="2" markdown="1">

```mermaid
flowchart TB
 subgraph b0["Interface"]
 b0m0["CLI"]
 b0m1["mcp"]
 end
 subgraph b1["Application"]
 b1m0["assembler"]
 b1m1["composition"]
 b1m2["deployer"]
 b1m3["pipeline"]
 b1m4["planning"]
 b1m5["review"]
 end
 subgraph b2["Domain"]
 b2m0["analysis"]
 b2m1["comprehension"]
 b2m2["ontology"]
 end
 b0 -->|"depends on"| b1
 b1 -->|"depends on"| b2
 class b0m0,b0m1,b1m0,b1m1,b1m2,b1m3,b1m4,b1m5,b2m0,b2m1,b2m2 container
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart TB
 subgraph people["People"]
 actor_operator(["Operator"])
 end
 subgraph enterprise["This system"]
 system["DocuHarnessX"]
 end
 subgraph external["External"]
 external_ci["GitHub Actions"]
 external_docs[("Documentation site")]
 external_repo[("norandom/DocuHarnessX")]
 end
 actor_operator -->|"runs CLI"| system
 system -->|"reads and cites"| external_repo
 external_ci -->|"runs in"| system
 system -->|"publishes"| external_docs
 class actor_operator person
 class system system
 class external_ci external
 class external_docs store
 class external_repo store
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart TB
 subgraph start["Start here"]
 s0["How does this program start?"]
 s1["What does docuharnessx do?"]
 s2["How is this project built and verif…"]
 s3["How are tests organized?"]
 s4["How is the public surface used or e…"]
 end
 s0 --> s1
 s1 --> s2
 s2 --> s3
 s3 --> s4
 subgraph more["Further questions"]
 m0["What does analysis do?"]
 m1["What does assembler do?"]
 m2["What does composition do?"]
 m3["What does comprehension do?"]
 m4["What does javascripts do?"]
 end
 s4 -.-> m0
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart LR
 subgraph ginput["Inputs"]
 n0(["Inputs"])
 end
 subgraph gtransform["This system"]
 n1["cli.py"]
 n2["docuharnessx"]
 n4["analysis"]
 n5["assembler"]
 n6["composition"]
 n7["comprehension"]
 end
 subgraph goutput["Outputs"]
 n3[("Outputs")]
 end
 n0 --> n1
 n1 --> n2
 n2 --> n3
 n1 --> n4
 n4 --> n3
 n1 --> n5
 n5 --> n3
 n1 --> n6
 n6 --> n3
 n1 --> n7
 n7 --> n3
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="7" markdown="1">

```mermaid
flowchart LR
 subgraph ginput["Inputs"]
 n0(["Inputs"])
 end
 subgraph gtransform["This system"]
 n1["cli.py"]
 n2["docuharnessx"]
 n4["analysis"]
 n5["assembler"]
 n6["composition"]
 n7["comprehension"]
 end
 subgraph goutput["Outputs"]
 n3[("Outputs")]
 end
 n0 --> n1
 n1 --> n2
 n2 --> n3
 n1 --> n4
 n4 --> n3
 n1 --> n5
 n5 --> n3
 n1 --> n6
 n6 --> n3
 n1 --> n7
 n7 --> n3
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart LR
 subgraph pipe["Pipeline"]
 docs["docs"]
 evolve["evolve"]
 end
 docs --> evolve
 class docs,evolve container
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>

<div class="dhx-layer" data-min="7" markdown="1">

```mermaid
flowchart LR
 subgraph pipe["Pipeline"]
 docs["docs"]
 evolve["evolve"]
 end
 docs --> evolve
 class docs,evolve container
 classDef person fill:#E8B923,stroke:#7A5100,color:#1A1300
 classDef system fill:#A8C8FF,stroke:#1E4BB8,color:#0B1F4A
 classDef container fill:#B9D4FE,stroke:#2F62C4,color:#0B1F4A
 classDef external fill:#D5DCE6,stroke:#4A5568,color:#1A202C
 classDef store fill:#7ED4C0,stroke:#0F766E,color:#042F2E
```

</div>


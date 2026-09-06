# DocuHarnessX

<div class="dhx-layer" data-min="1" markdown="1">

This site walks through 12 questions about [`norandom/DocuHarnessX`](https://github.com/norandom/DocuHarnessX), in the order you would actually learn the project.

Read the numbered list first. Later questions cover individual modules.

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
- [What does deployer do?](component-deployer-f8b1b75f.md)
- [What does javascripts do?](component-javascripts-2aa9650e.md)
- [What does mcp do?](component-mcp-bdf519de.md)

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
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
```

</div>

<div class="dhx-layer" data-min="2" markdown="1">

```mermaid
pie showData
  title Documentation coverage
  "Accepted pages" : 12
```

</div>

<div class="dhx-layer" data-min="2" markdown="1">

```mermaid
flowchart TB
  subgraph sys["DocuHarnessX"]
    cli["CLI"]
    c0["docuharnessx"]
    c1["analysis"]
    c2["assembler"]
    c3["composition"]
    c4["comprehension"]
    c5["deployer"]
    c6["mcp"]
    c7["ontology"]
  end
  actor(["Operator"])
  actor -->|"runs CLI"| cli
  class actor actor
  cli -->|uses| c0
  cli -->|uses| c1
  cli -->|uses| c2
  cli -->|uses| c3
  cli -->|uses| c4
  cli -->|uses| c5
  cli -->|uses| c6
  cli -->|uses| c7
  class cli,c0,c1,c2,c3,c4,c5,c6,c7 container
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart TB
  subgraph people["People"]
    actor(["Operator"])
  end
  subgraph enterprise["This system"]
    sys["DocuHarnessX<br/>Command-line program (CLI)"]
  end
  subgraph external["External"]
    repo[("norandom/DocuHarnessX")]
    ci["GitHub Actions"]
    docs[("Documentation site")]
  end
  actor -->|"runs CLI"| sys
  sys -->|"reads and cites"| repo
  ci -->|"runs in"| sys
  sys -->|"publishes"| docs
  class actor actor
  class sys system
  class repo,docs store
  class ci external
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
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
    m4["What does deployer do?"]
    m5["What does javascripts do?"]
    m6["What does mcp do?"]
  end
  s4 -.-> m0
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
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
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
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
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
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
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
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
  classDef actor fill:#0F172A,stroke:#020617,color:#FFFFFF
  classDef system fill:#1E3A8A,stroke:#1E3A8A,color:#FFFFFF
  classDef container fill:#EEF2FF,stroke:#1E3A8A,color:#0F172A
  classDef external fill:#F8FAFC,stroke:#64748B,color:#0F172A
  classDef store fill:#E2E8F0,stroke:#334155,color:#0F172A
```

</div>


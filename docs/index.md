# [DocuHarnessX](glossary.md#docuharnessx)

Documentation for [`norandom/DocuHarnessX`](https://github.com/norandom/DocuHarnessX).

<div class="dhx-layer" data-min="1" markdown="1">

```mermaid
flowchart TB
  system["System"]
  e0["docuharnessx/cli.py"]
  e0 --> system
  c0["javascripts"]
  system --> c0
  c1["docuharnessx"]
  system --> c1
  c2["analysis"]
  system --> c2
  c3["assembler"]
  system --> c3
  c4["composition"]
  system --> c4
  c5["comprehension"]
  system --> c5
```

</div>

<div class="dhx-layer" data-min="3" markdown="1">

```mermaid
flowchart TB
  n0["Home"]
  n1["How is this project built and verified?"]
  n2["What does analysis do?"]
  n3["What does assembler do?"]
  n4["What does composition do?"]
  n5["What does comprehension do?"]
  n6["What does deployer do?"]
  n7["What does docuharnessx do?"]
  n8["What does javascripts do?"]
  n9["What does mcp do?"]
  n10["How is the public surface used or exten…"]
  n11["How does this program start?"]
  n12["How are tests organized?"]
  n0 --> n1
  n0 --> n2
  n0 --> n3
  n0 --> n4
  n0 --> n5
  n0 --> n6
  n0 --> n7
  n0 --> n8
  n0 --> n9
  n0 --> n10
  n0 --> n11
  n0 --> n12
```

</div>

<div class="dhx-layer" data-min="3" markdown="1">

```mermaid
flowchart LR
  s0["input"]
  t0["docuharnessx/cli.py"]
  s0 -->|1| t0
  s1["docuharnessx/cli.py"]
  t1["javascripts"]
  s1 -->|1| t1
  s2["javascripts"]
  t2["output"]
  s2 -->|1| t2
  s3["docuharnessx/cli.py"]
  t3["docuharnessx"]
  s3 -->|1| t3
  s4["docuharnessx"]
  t4["output"]
  s4 -->|1| t4
  s5["docuharnessx/cli.py"]
  t5["analysis"]
  s5 -->|1| t5
  s6["analysis"]
  t6["output"]
  s6 -->|1| t6
  s7["docuharnessx/cli.py"]
  t7["assembler"]
  s7 -->|1| t7
  s8["assembler"]
  t8["output"]
  s8 -->|1| t8
  s9["docuharnessx/cli.py"]
  t9["composition"]
  s9 -->|1| t9
  s10["composition"]
  t10["output"]
  s10 -->|1| t10
  s11["docuharnessx/cli.py"]
  t11["comprehension"]
  s11 -->|1| t11
  s12["comprehension"]
  t12["output"]
  s12 -->|1| t12
```

</div>

<div class="dhx-layer" data-min="7" markdown="1">

```mermaid
flowchart LR
  s0["input"]
  t0["docuharnessx/cli.py"]
  s0 -->|1| t0
  s1["docuharnessx/cli.py"]
  t1["javascripts"]
  s1 -->|1| t1
  s2["javascripts"]
  t2["output"]
  s2 -->|1| t2
  s3["docuharnessx/cli.py"]
  t3["docuharnessx"]
  s3 -->|1| t3
  s4["docuharnessx"]
  t4["output"]
  s4 -->|1| t4
  s5["docuharnessx/cli.py"]
  t5["analysis"]
  s5 -->|1| t5
  s6["analysis"]
  t6["output"]
  s6 -->|1| t6
  s7["docuharnessx/cli.py"]
  t7["assembler"]
  s7 -->|1| t7
  s8["assembler"]
  t8["output"]
  s8 -->|1| t8
  s9["docuharnessx/cli.py"]
  t9["composition"]
  s9 -->|1| t9
  s10["composition"]
  t10["output"]
  s10 -->|1| t10
  s11["docuharnessx/cli.py"]
  t11["comprehension"]
  s11 -->|1| t11
  s12["comprehension"]
  t12["output"]
  s12 -->|1| t12
```

</div>

<div class="dhx-layer" data-min="3" markdown="1">

```mermaid
flowchart LR
  docs["docs"]
  evolve["evolve"]
  docs --> evolve
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart LR
  docs["docs"]
  evolve["evolve"]
  docs --> evolve
```

</div>

## Questions

- [How is this project built and verified?](build-pyproject-toml-a625bf0a.md)
- [What does analysis do?](component-analysis-5fb37dc2.md)
- [What does assembler do?](component-assembler-d9228a8c.md)
- [What does composition do?](component-composition-e6f778c7.md)
- [What does comprehension do?](component-comprehension-87225edb.md)
- [What does deployer do?](component-deployer-f8b1b75f.md)
- [What does docuharnessx do?](component-docuharnessx-3986831c.md)
- [What does javascripts do?](component-javascripts-2aa9650e.md)
- [What does mcp do?](component-mcp-bdf519de.md)
- [How is the public surface used or extended?](public-surface-init-py-a3934091.md)
- [How does this program start?](startup-cli-py-126eba90.md)
- [How are tests organized?](tests-tests-37e0cc9c.md)

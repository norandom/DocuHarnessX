# DocuHarnessX

<div class="dhx-layer" data-min="1" markdown="1">

This site walks through 10 questions about [`norandom/DocuHarnessX`](https://github.com/norandom/DocuHarnessX), in the order you would actually learn the project.

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
- [What does javascripts do?](component-javascripts-2aa9650e.md)

</div>

<div class="dhx-layer" data-min="3" markdown="1">

```mermaid
flowchart LR
  p0["How does this program start?"]
  p1["What does docuharnessx do?"]
  p2["How is this project built and verifi"]
  p3["How are tests organized?"]
  p4["How is the public surface used or ex"]
  p0 --> p1
  p1 --> p2
  p2 --> p3
  p3 --> p4
```

</div>

<div class="dhx-layer" data-min="2" markdown="1">

```mermaid
flowchart TB
  accepted["accepted 10"]
  omitted["omitted 0"]
  planned["planned 10"]
  planned --> accepted
  planned --> omitted
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

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

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart TB
  n0["Home"]
  n1["How does this program start?"]
  n2["What does docuharnessx do?"]
  n3["How is this project built and verified?"]
  n4["How are tests organized?"]
  n5["How is the public surface used or exten…"]
  n6["What does analysis do?"]
  n7["What does assembler do?"]
  n8["What does composition do?"]
  n9["What does comprehension do?"]
  n10["What does javascripts do?"]
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
```

</div>

<div class="dhx-layer" data-min="5" markdown="1">

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

<div class="dhx-layer" data-min="5" markdown="1">

```mermaid
flowchart LR
  docs["docs"]
  evolve["evolve"]
  docs --> evolve
```

</div>

<div class="dhx-layer" data-min="7" markdown="1">

```mermaid
flowchart LR
  docs["docs"]
  evolve["evolve"]
  docs --> evolve
```

</div>


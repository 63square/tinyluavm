# Architecture

`tinyvm` is a Luau interpreter implemented as **two stacked interpreters**:

1. The **micro-VM** (`src/tinyvm.luau`, 4708 bytes) is a stripped tree-
   walker that interprets our bytecode format.
2. The **macro-VM** (`src/macrovm.luau`, 6811 bytes) is a full-featured
   Luau interpreter — also in our bytecode format — that the micro-VM
   *executes*.

The user's Luau source compiles to bytecode that the macro-VM executes.
So a user program goes through this pipeline at run time:

```
              ┌──────────────────────────────────────┐
              │ user.luau                            │
              │   compiled offline → user.bin        │
              │     ↓                                │
              │   passed to play(macroVM, user.bin, env, ...)
              │     ↓                                │
   src/tinyvm.luau (the micro-VM, 4.7 KB) ── runs ── macro-VM bytecode
              │     ↓                                │
   macro-VM interpretation produces ── runs ── user.bin
              │     ↓                                │
              │   user program executes              │
              └──────────────────────────────────────┘
```

## Why two layers?

A self-contained Luau interpreter has to handle a lot of user-facing
behavior: error messages with `chunk:line:` prefixes, `__call`/`__namecall`
metamethod dispatch on non-function call targets, `__iter` generalized
iteration, conformance-exact diagnostic text, multi-target assignment
with pre-evaluation semantics, etc. Those features collectively cost
several KB.

The macro-VM still has to implement all of them, because *user code*
expects them. But the micro-VM only has to run the macro-VM, which is a
well-behaved Luau program we wrote ourselves. We know it never:

* calls a `nil` or a table that needs `__call` dispatch,
* uses methods (`o:method()`),
* uses `repeat`/`until`,
* uses `do ... end` standalone blocks,
* uses if-expressions (`if a then b else c` as an expression),
* uses parenthesized vararg/multi-truncation,
* uses `continue`,
* assigns to multiple indexed targets simultaneously,
* uses negative integer constants.

Every one of those features can be deleted from the micro-VM without
breaking the macro-VM. That's how we get to 4.7 KB.

The micro-VM keeps the minimum:

* Tags 1-8 (literals + locals + upvals + globals)
* Tag 9 (Index)
* Tag 10 (Call) — no method-call (tag 11)
* Tag 12 (Closure construction)
* Tag 13 (Table constructor)
* Tags 14-15 (Binary + unary operators, all of them)
* Tags 16-17 (`and` / `or` short-circuit)
* Tags 30-31 (Single-target assign / Local-decl)
* Tag 32 (if/elseif/else)
* Tag 33 (while)
* Tags 35-36 (numeric-for / generic-for)
* Tag 37 (return)
* Tag 38 (break)
* Tag 41 (expression statement)
* Tag 50 (block with line info)

That's it.

## Where the byte savings come from

| Pruned feature                              | ~bytes saved |
|---------------------------------------------|--------------|
| Error/assert chunk:line prefixing (`fa`/`pf`)    | 80 |
| `inv` function (call wrapper for diagnostics, `__call`, error/assert special cases) | 530 |
| Method-call dispatch (tag 11) with `__namecall` / `__index` lookup | 250 |
| Generic-for `__iter` + `__call` + type-check    | 150 |
| Numeric-for type-check (`invalid 'for' ...`)    | 70 |
| Multi-target assign pre-eval                    | 50 |
| `if`-expression (tag 18)                        | 50 |
| `repeat ... until` (tag 34)                     | 80 |
| `continue` (tag 39)                             | 20 |
| `do ... end` standalone (tag 40)                | 30 |
| Paren / vararg-truncation (tag 19)              | 25 |
| Const-pool: nil / true / false / float kinds (macro uses only int + string) | 120 |
| Zig-zag varint decode (macro uses no negatives) | 40 |
| Pre-built op-tables for `B` / `U`               | 90 |
| Dictionary table for "is multi" tag set         | 5 |
| Receiver / `bs` parameter on `M`                | 30 |
| **Total approx.**                                | **~1620** |

The savings are real because they're all features the macro-VM *doesn't
use*. User code can still use them — the macro-VM implements them — they
just don't need a second implementation in the micro-VM.

## What the micro-VM actually does

Pseudocode:

```
function play(macroBytecode, ...args):
    pose, tracks    = decodeBytecode(macroBytecode)  -- constants + functions
    macroEntryPoint = bindClosure(tracks[1])         -- main chunk
    macroPlay       = macroEntryPoint()              -- returns the play fn
    return macroPlay(...args)                        -- user invocation
```

Concretely:

1. Read varint-prefixed constants pool. Only int + string kinds; macro
   never embeds nil/true/false/float as constants.
2. Read varint-prefixed function pool. Each function record:
   numparams, isvararg, upvalue-link list, body atom tree.
3. The macro-VM's "main chunk" is `function(b, E, la, ...) -> closure`,
   so calling it runs the locals (alias setup, op tables, etc.) and
   returns the inner closure. The micro-VM does `tracks[1]()()` to:
   first build the main-chunk closure, second invoke it with no args
   to get the inner closure.
4. The inner closure is the user-facing `play(userBytecode, env, label, ...)`
   function. The micro-VM's varargs `...` are forwarded to it.
5. From this point on, the macro-VM is executing user bytecode. The
   macro-VM handles all user-facing features. The micro-VM is just a
   tree-walker that loops over the macro-VM's AST.

## Implementation notes

* **No `H` continue-sentinel.** The macro-VM doesn't use `continue`, so
  the micro-VM only has the `H` break-sentinel.
* **Pre-bind shape-decoded atoms.** Each atom is a small Lua array
  `{tag, ...payload}`. Decoded once at load; the eval/exec loop just
  reads fields. No re-parsing during execution.
* **`pa.S` / `pa.U` selection via inline ternary** in the upval-link
  resolution: `lr[i] = (u[1]==0 and pa.S or pa.U)[u[2]]`.
* **Varargs via `tp(select(np+1, ...))`** rather than manual
  `args[np+i]` loops.
* **Boxed locals.** Each local slot is a one-element table `{value}`.
  Closures capture the box, so writes via upvalue are visible. This is
  the standard upvalue trick used by every tree-walking Lua interpreter.

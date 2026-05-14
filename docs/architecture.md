# Architecture

`tinyvm` is a Luau interpreter implemented as **two stacked interpreters**
plus a **build-time atom-rewriting predecoder** that does heavy lifting
the micro-VM would otherwise have to do at runtime.

1. The **micro-VM** (`src/tinyvm.luau`, 1713 bytes) is a stripped tree-
   walker that interprets a pre-decoded atom tree.
2. The **macro-VM** (`src/macrovm.luau`, 6.8 KB) is a full-featured
   Luau interpreter — compiled offline and pre-decoded — that the
   micro-VM *executes*.
3. The **predecoder** (`tools/predecode.py`) rewrites the macro-VM's
   atom tree at build time: folding constants, replacing arithmetic
   opcodes with calls to env-supplied helpers, unifying opcodes, and
   baking each function into a closure-builder. This is what lets the
   micro-VM be so small.

A user program goes through this pipeline at run time:

```
                  ┌──────────────────────────────────────────────────┐
                  │ user.luau                                        │
                  │   compiled offline → user.bin                    │
                  │                                                  │
                  │   bundle.play(user.bin, env, label, ...) →       │
                  │                                                  │
   src/tinyvm.luau (the micro-VM, 1.7 KB) ── interprets ── macro-VM AST
                  │                                                  │
                  │   macro-VM ── interprets ── user.bin             │
                  │                                                  │
                  │   user program executes                          │
                  └──────────────────────────────────────────────────┘
```

The macro-VM AST is **not bytecode** at micro-VM run time; it's already
a tree of Lua tables produced at build time. The micro-VM never decodes
varints or reads byte streams. It just walks atoms.


## Why three pieces?

A self-contained Luau interpreter has to handle a lot of user-facing
behavior: error messages with `chunk:line:` prefixes, `__call`/`__namecall`
metamethod dispatch on non-function call targets, `__iter` generalized
iteration, conformance-exact diagnostic text, multi-target assignment
with pre-evaluation semantics, the full numeric/generic-for protocols,
and so on. Those features collectively cost several KB of code.

The macro-VM still has to implement all of them, because *user code*
expects them. But the micro-VM only has to run the macro-VM, which is a
well-behaved Luau program we wrote ourselves. We know exactly which
atoms the macro-VM ever emits, and the predecoder can rewrite them
into a smaller equivalent set before the micro-VM ever sees them.


## Where the byte savings come from

| Reduction                                           | mechanism                                       | ~bytes saved |
|-----------------------------------------------------|-------------------------------------------------|--------------|
| Bytecode reader                                     | predecode emits Lua tables directly             | ~1450 |
| Nil/True/False atoms (tags 1, 2, 3)                 | folded into Const atoms (tag 4)                 | ~85 |
| BinOp/UnOp atoms (tags 14, 15)                      | rewritten into Call atoms targeting `B1`..`B14` and `U1`..`U3` in the env | ~620 |
| Vararg expression atom (tag 5) in `z`               | macro-VM only uses Vararg in tail-call position; `P` handles it | ~28 |
| Local + Upval atoms (tags 6, 7)                     | unified into tag 6 with `"S"`/`"U"` storage marker; single handler | ~22 |
| Generic-for `__iter` fallback in micro-VM           | force_gfor3 rewrites `for k,v in t do` into `for k,v in next, t, nil do` | ~52 |
| NumericFor step support                             | dropped — verified macro-VM never emits step    | ~80 |
| Multi-target Assign for non-Local kinds             | split_assign rewrites single-target Assign by kind (Local/Upval → t==20, Global → t==22, Index → t==23); multi-target only sees Local | ~120 |
| `if`/`elseif`/`else` IIFE in t==32                  | flattened to a single (cond, block) pair list; first branch is `(c0, t0)`, else as separate slot | ~40 |
| Generic-for 2-slot flatten                          | force_gfor3 inlines the slot pair as `(s1, s2)` directly in the atom | ~12 |
| Q's frame/upvalue setup                             | baked into per-function closure-builders in F[i] | ~180 |
| Top-level return value (caller-side void)           | dropped: `F[1](nil,J)()(...)` instead of `return F[1]()...` | ~7 |
| `tp`/`tu` constants                                 | passed in as micro-VM parameters; `H` break sentinel reuses the `M` function | ~50 |
| Various local-variable hoisting and code rearranging | shared `v`, `x`, `r` locals; `M(A[n], fr)` always uses P; etc. | ~200 |
| **Total approx.**                                   |                                                 | **~2950** |

(Baseline 4708 → current 1713 = ~2995 actual. The remaining delta is
small whitespace tweaks and inlining.)


## What the micro-VM contains

In source order, the top-level function `function(K, F, E, tp, tu, ...)`:

* `local z, P, J` — forward declarations for the three mutually
  recursive functions.
* **`M(A, fr)`** — evaluates an atom list and returns `(packArray,
  count)`. The last element is always routed through `P` so multi-return
  values expand naturally. Used by Table construction, Call args,
  multi-target Assign, multi-source LocalDecl, GenericFor sources, and
  Return.
* **`z(n, fr)`** — single-value expression evaluator. Handles tags
  4, 6, 8, 9, 10, 12, 13, 16, 17. `local t, k, m = n[1], n[2], n[3]`
  at the start aliases the three most commonly used atom positions.
* **`P(n, fr)`** — call/multret evaluator. Returns a pack table
  (`{n=N, [1]=..., [2]=..., ...}`). Handles tags 10 (Call) and 5
  (Vararg); everything else falls through to `tp(z(n,fr))`.
* **`J(bl, fr)`** — block executor. Walks `bl[2]` (the statement list)
  and dispatches by tag. Local-hoisted `v, x, r` are reused across
  iterations to avoid per-iter `local` allocations.
* **`F[1](nil, J)()(...)`** — entry point. The macro-VM's main chunk is
  `F[1]`. `F[1](nil, J)` runs the predecoded function's upvalue baker
  (with no parent frame) and returns the macro-VM's main closure;
  `()` invokes it (no args — the main chunk takes none); `(...)`
  calls the user-facing closure it returns with the caller's args.

That's the whole micro-VM.


## What the predecoder does

`tools/predecode.py` reads `build/macrovm.bin` (compiled with the
offline compiler) into a Python AST, then applies these rewrites in
order on every atom:

1. **`fold-bool`**: `[1]` (Nil), `[2]` (True), `[3]` (False) become
   `[4, idx]` where `K[idx]` holds the corresponding value. Adds three
   entries to the constant pool.
2. **`rewrite-ops`**: `[14, opCode, a, b]` (BinOp) becomes
   `[10, [8, B_idx], [a, b], 1]` (a Call atom calling the global
   `B<opCode>` with two args, multret-1). Similarly for `[15]` (UnOp).
   Adds 17 string constants to K: `"B1"`..`"B14"`, `"U1"`..`"U3"`.
3. **Local/Upval unify**: `[6, slot]` (Local) becomes
   `[6, "S", slot]`; `[7, slot]` (Upval) becomes `[6, "U", slot]`.
   The micro-VM's `z` handler then dispatches via `fr[k][m][1]`
   (a single lookup regardless of storage kind).
4. **`force-gfor3`**: `[36, slots, [src], body]` (1-source GenericFor)
   becomes `[36, slots, [Global("next"), src, Const(nil)], body]`.
   Plus all 2-slot variants are flattened to `[36, s1, s2, sources, body]`
   so the micro-VM can read both slot indices without a list lookup.
5. **NumericFor step drop**: `[35, slot, from, to, None, body]` becomes
   `[35, slot, from, to, body]` (no step slot). All NumericFors in the
   macro-VM source use the default step of 1.
6. **If flatten**: `[32, c0, t0, elseifs, else]` becomes
   `[32, [[c0, t0]] ++ elseifs, else]`. The main cond becomes the first
   `(cond, block)` pair in a uniform list.
7. **`split-assign`**: Single-target `[30, [target], [value]]` becomes
   one of:
   * `[20, "S", slot, value]` — local assign
   * `[20, "U", slot, value]` — upvalue assign
   * `[22, name_idx, value]` — global assign
   * `[23, tableAtom, keyAtom, value]` — indexed assign
   Multi-target `[30, [targets...], [values...]]` is only kept when all
   targets are local; the targets list is flattened to slot integers.
8. **Function bake**: Each function record is replaced with a Lua
   closure-builder source string:

   ```lua
   function(pa, J)
     local lr = {pa.S[3], pa.U[1], ...}    -- captures from parent
     return function(...)
       local fr = {S = {}, U = lr, V = tp(select(NP+1, ...))}
       for i = 1, NP do fr.S[i] = {(select(i, ...))} end
       local r = J(BODY_TREE, fr)
       if r then return tu(r, 1, r.n) end
     end
   end
   ```

   The `tp` and `tu` references close over the bundle's enclosing scope,
   so they don't need to be parameters of the inner closure.

After all rewrites, the predecoder emits a Lua module returning the
new `K` and `F` lists as a single expression:

```lua
--!nocheck
return {"string", "byte", ..., "B1", ..., "U3", nil, true, false},
       {function(pa,J) ... end, function(pa,J) ... end, ...}
```

The micro-VM consumes this via `F[k](fr, J)` whenever it processes a
Closure atom (`t == 12`).


## Sentinels and signalling

The micro-VM uses a single sentinel — the `M` function itself —
for the **break** signal returned from `J`. When `J` encounters a
Break statement (`t == 38`), it `return M`. The enclosing loop
handler checks `x == M` and breaks. Using the local `M` function as
the sentinel avoids needing a separate `local H = {}` allocation
and saves a few bytes.

The `r` return-pack from `J` is otherwise a table (the multret pack
from a Return statement). Loops and Ifs forward non-nil non-`M`
values upward via `return x`.


## Implementation notes

* **Boxed locals.** Each local slot is a one-element table `{value}`.
  Closures capture the box, so writes via upvalue are visible. This is
  the standard upvalue trick used by every tree-walking Lua interpreter.
* **Hoisted scratch.** `local v, x, r` are declared once at the top of
  `J`'s outer loop, not per iteration. Branches reuse them. `v` is
  used both for the assign value pack (t==30/31) and as the selected
  If branch (t==32) — there's no overlap because the variable is
  dead at the end of every handler.
* **Storage-marker reads.** `fr[p][h][1] = z(u, fr)` (t==20) selects
  the storage table by the marker `p` (the string `"S"` or `"U"`),
  the slot by `h`, and the boxed value by `[1]`. The marker is a
  string from K, baked in by the predecoder as a Lua `Raw` literal.
* **No `Q` function.** The "closure constructor" the older revision
  shipped — `Q(ix, pa)` that built a function record's closure — has
  been inlined. Each `F[i]` is itself the constructor: calling
  `F[ix](fr, J)` returns the bound closure directly.
* **No bytecode reader.** Earlier revisions had a varint/atom reader
  taking ~1.1 KB. The predecoder emits Lua tables directly, so the
  micro-VM never does I/O on a byte stream.
* **`tp` / `tu` from the env, not stdlib.** They're parameters of the
  micro-VM (`function(K, F, E, tp, tu, ...)`). The bundle defines
  `local tp, tu = table.pack, table.unpack` once at the top, so both
  the micro-VM call site and the predecoded F closures share them as
  upvalues, saving a few bytes per closure.

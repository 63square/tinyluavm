# Bytecode format

There are two stages of "format" in `tinyvm`:

1. The **wire format** that `tools/compiler.py` emits — a compact
   binary file with varints and packed doubles. This is what user
   programs are compiled to, and it's what the macro-VM reads at run
   time when interpreting user code.
2. The **runtime atom shape** the micro-VM actually walks — a tree of
   Lua tables produced by `tools/predecode.py` from the wire format.
   The predecoder applies several rewrites on top of the wire format.
   The micro-VM never sees the wire format directly anymore; only the
   macro-VM does.

The rest of this document covers both.


## Wire format (what the compiler emits)

All integers are LEB128 unsigned varints unless stated.
Signed integers are zig-zag encoded varints.
Doubles are 8 bytes little-endian (`string.pack("<d", x)`).
Strings are `varint(length)` followed by raw bytes.

### Top-level layout

```
  varint nk                       constant count
  nk × (u8 kind, payload)         the constant pool
  varint nf                       function count
  nf  × function record           the function pool
```

The "main chunk" is `F[1]`. Execution begins there.

### Constant kinds

| kind | meaning           | payload                       |
|------|-------------------|-------------------------------|
| 0    | nil               | (none)                        |
| 1    | false             | (none)                        |
| 2    | true              | (none)                        |
| 3    | int               | zig-zag varint                |
| 4    | double            | 8 raw bytes, little-endian    |
| 5    | string            | varint length + raw bytes     |

### Function record

```
  u8     numparams
  u8     isvararg              (0 or 1)
  varint numupvalues
  numupvalues × (
      u8     fromKind          (0 = parent local, 1 = parent upvalue)
      varint index             (1-based)
  )
  atom   body                  always a Block atom (tag 50)
```

### Atom tags emitted by the compiler

Each atom is `u8 tag` followed by tag-specific payload.

#### Expression tags

| tag | name        | payload                                  |
|-----|-------------|------------------------------------------|
| 1   | Nil         | (none)                                   |
| 2   | True        | (none)                                   |
| 3   | False       | (none)                                   |
| 4   | Const       | varint ki                                |
| 5   | Vararg      | (none) — must be inside a vararg fn      |
| 6   | Local       | varint slot                              |
| 7   | Upval       | varint idx                               |
| 8   | Global      | varint ki — `env[K[ki]]`                 |
| 9   | Index       | atom obj, atom key                       |
| 10  | Call        | atom fn, atom-list args, u8 multret      |
| 11  | MethodCall  | atom obj, varint nameKi, atom-list args, u8 multret  |
| 12  | Closure     | varint funcIdx                           |
| 13  | Table       | varint narr, varint nhash, narr × atom, nhash × (atom key, atom val) |
| 14  | BinOp       | u8 op, atom a, atom b                    |
| 15  | UnOp        | u8 op, atom a                            |
| 16  | And         | atom a, atom b                           |
| 17  | Or          | atom a, atom b                           |
| 18  | IfExpr      | atom cond, atom thenVal, atom elseVal    |
| 19  | Paren       | atom inner — forces single value         |

#### Statement tags

| tag | name        | payload                                  |
|-----|-------------|------------------------------------------|
| 30  | Assign      | atom-list targets, atom-list values      |
| 31  | LocalDecl   | varint-list slots, atom-list values      |
| 32  | If          | atom cond, atom thenBlock, atom-pair-list elseifs, u8 hasElse, [atom elseBlock] |
| 33  | While       | atom cond, atom body                     |
| 34  | Repeat      | atom body, atom cond                     |
| 35  | NumFor      | varint slot, atom start, atom stop, u8 hasStep, [atom step], atom body |
| 36  | GenFor      | varint-list slots, atom-list sources, atom body |
| 37  | Return      | atom-list values                         |
| 38  | Break       | (none)                                   |
| 39  | Continue    | (none)                                   |
| 40  | Do          | atom body                                |
| 41  | ExprStmt    | atom                                     |

#### Block tag

| tag | name  | payload                                       |
|-----|-------|-----------------------------------------------|
| 50  | Block | varint nstmts, nstmts × (varint line, atom stmt) |

### Operator codes

#### Binary (u8)

| code | op  | code | op  |
|------|-----|------|-----|
| 1    | +   | 8    | ..  |
| 2    | -   | 9    | ==  |
| 3    | *   | 10   | ~=  |
| 4    | /   | 11   | <   |
| 5    | //  | 12   | <=  |
| 6    | %   | 13   | >   |
| 7    | ^   | 14   | >=  |

#### Unary (u8)

| code | op    |
|------|-------|
| 1    | -     |
| 2    | not   |
| 3    | #     |

Logical `and` / `or` are tags 16 / 17, not BinOp codes, so the runtime
can short-circuit.

### Multi-return semantics

Atoms with tags 5, 10, and 11 can produce more than one value. The
runtime expands them only when they're at the tail position of a
value list (last arg in a call, last entry in a table constructor's
array section, last value in a return / multi-assign / local-decl).

For Call / MethodCall, the trailing `multret` u8 controls whether the
result is kept multi (1) or truncated to one value (0). The compiler
sets `multret = 0` for parenthesized calls and `multret = 1` everywhere
else; the runtime then truncates further in single-value contexts.


## Predecoder rewrites (what the micro-VM actually sees)

The macro-VM source `src/macrovm.luau` is compiled to wire format
(`build/macrovm.bin`), then `tools/predecode.py` rewrites it into a
Lua expression `(K, F)` saved at `build/macrovm-ast.luau`. The
following rewrites are applied (each is optional but all are enabled
by `tools/build.py`):

### `--fold-bool`: Nil/True/False → Const

The atoms `[1]` (Nil), `[2]` (True), `[3]` (False) become `[4, idx]`
where `K[idx]` holds `nil` / `true` / `false`. The predecoder appends
those three values to K.

The micro-VM has **no** handlers for tags 1, 2, 3 — they no longer
appear after this pass.

### `--rewrite-ops`: BinOp/UnOp → Call

Each `[14, opCode, a, b]` becomes `[10, [8, B_idx], [a, b], 1]`,
a Call atom whose function is the global `B<opCode>` (one of `B1`..`B14`)
applied to `(a, b)` with multret 1. Similarly `[15, opCode, a]`
becomes a Call of `U<opCode>` (`U1`..`U3`) on `(a)`.

The predecoder appends 17 string constants to K: `"B1"`..`"B14"`,
`"U1"`..`"U3"`. The caller-provided env must expose those names as
functions; the bundle's `_E(u)` helper does this automatically.

The micro-VM has **no** handlers for tags 14 or 15.

### Local/Upval unify

Local atoms `[6, slot]` become `[6, "S", slot]`; Upval atoms
`[7, slot]` become `[6, "U", slot]`. The shared handler is:

```lua
elseif t == 6 then return fr[k][m][1]
```

where `k` is the storage marker (`"S"` or `"U"`) and `m` is the slot
index. `fr.S` and `fr.U` are the per-frame local-stack and upvalue
tables respectively, so `fr["S"]` and `fr["U"]` resolve correctly.

The micro-VM has **no** handler for tag 7.

### `--force-gfor3`: GenericFor 3-source form + 2-slot flatten

Atom `[36, slots, [singleSrc], body]` becomes
`[36, slots, [Global("next"), singleSrc, Const(nil)], body]`. This
removes the need for the micro-VM to special-case `for k,v in tbl do`
(where `tbl` is iterated via the `__iter` metamethod or fallback
`next` semantics).

The predecoder appends `"next"` to K.

Additionally, if `slots` has exactly 2 entries (the common case for
`for k, v in ...`), they're hoisted into the atom directly:
`[36, s1, s2, sources, body]` (5 elements instead of 4 with a
sublist).

### NumericFor step drop

`[35, slot, from, to, None, body]` (NumericFor without step) becomes
`[35, slot, from, to, body]` (no step slot). All NumericFors in the
macro-VM source use step = 1.

The micro-VM's handler is simply `for j = z(h, fr), z(u, fr) do ...`
— no step variable, no NaN guard, no direction selection.

### If flatten

`[32, c0, t0, elseifs, else]` becomes
`[32, [[c0, t0]] ++ elseifs, else]`. The main cond/then are folded
into the first entry of a uniform `(cond, block)` pair list:

```lua
elseif t == 32 then
  local bk = h                            -- start with else block
  for _, e in p do                        -- p = pair list
    if z(e[1], fr) then bk = e[2]; break end
  end
  r = bk and J(bk, fr)
  if r then return r end
end
```

Layout: `it[2]` = pair list, `it[3]` = else block.

### `--split-assign`: Assign by target kind

Single-target `[30, [target], [value]]` becomes:

| target shape       | output                              |
|--------------------|-------------------------------------|
| `[6, "S", slot]`   | `[20, "S", slot, value]`            |
| `[6, "U", slot]`   | `[20, "U", slot, value]`            |
| `[8, name_idx]`    | `[22, name_idx, value]`             |
| `[9, table, key]`  | `[23, table, key, value]`           |

Multi-target Assign (only used in 1 place in the macro-VM, and only
with all-local targets) becomes `[30, [slot1, slot2, ...], values]`
— the targets list is flattened from atoms to slot ints.

### Function bake

Each function record `{np, va, L, b}` is replaced with a Lua source
string for a closure-builder:

```lua
function(pa, J)
  local lr = {pa.S[3], pa.U[1], ...}      -- one entry per upvalue
  return function(...)
    local fr = {S = {}, U = lr, V = tp(select(NP+1, ...))}
    for i = 1, NP do fr.S[i] = {(select(i, ...))} end
    local r = J(BODY_TREE, fr)
    if r then return tu(r, 1, r.n) end
  end
end
```

`tp` and `tu` are captured from the bundle's enclosing scope (they're
local to the bundle, not stdlib globals).

The body tree (`BODY_TREE`) is emitted as a literal Lua table
expression matching the atom shape.

## Atoms the micro-VM handles

After all rewrites, the micro-VM dispatches on this reduced atom set:

### In `z` (expression evaluator)

| tag | meaning                                  | handler                                |
|-----|------------------------------------------|----------------------------------------|
| 4   | Const                                    | `return K[k]`                          |
| 6   | Local *or* Upval (with storage marker)   | `return fr[k][m][1]`                   |
| 8   | Global                                   | `return E[K[k]]`                       |
| 9   | Index                                    | `return z(k, fr)[z(m, fr)]`            |
| 10  | Call (single-value context)              | `return P(n, fr)[1]`                   |
| 12  | Closure                                  | `return F[k](fr, J)`                   |
| 13  | Table constructor                        | array via `M`, then hash entries       |
| 16  | And                                      | `return z(k,fr) and z(m,fr)`           |
| 17  | Or                                       | `return z(k,fr) or z(m,fr)`            |

### In `P` (multret-aware call evaluator)

| tag | meaning            | handler                                  |
|-----|--------------------|------------------------------------------|
| 10  | Call               | `tp(fn(tu(args, 1, count)))`             |
| 5   | Vararg             | `return fr.V`                            |
| else                                    | `return tp(z(n, fr))`               |

### In `J` (statement executor)

| tag | meaning                          | notes                                                |
|-----|----------------------------------|------------------------------------------------------|
| 20  | Local/Upval Assign               | `fr[p][h][1] = z(u, fr)` — `p` is `"S"` or `"U"`     |
| 22  | Global Assign                    | `E[K[p]] = z(h, fr)`                                 |
| 23  | Index Assign                     | `z(p, fr)[z(h, fr)] = z(u, fr)`                      |
| 30  | Multi-target Local Assign        | iterate slot ints, `fr.S[s][1] = v[j]`               |
| 31  | LocalDecl                        | iterate slot ints, `fr.S[s] = {v[j]}` (fresh box)    |
| 32  | If (flattened pair list)         | first matching cond wins; else block as fallback     |
| 33  | While                            | standard; break propagates the `M` sentinel          |
| 35  | NumericFor (no step)             | `for j = z(h, fr), z(u, fr) do ... end`              |
| 36  | GenericFor (2-slot, 3-source)    | `for k, vv in v[1], v[2], v[3] do ... end`           |
| 37  | Return                           | pack via `M`, set `.n`, return                       |
| 38  | Break                            | `return M` (the M function used as sentinel)         |
| 41  | ExprStmt                         | `z(p, fr)` (discard result)                          |
| 50  | Block                            | not in J's switch; it's the outer iteration target   |

The following compiler-emitted tags are **never seen by the micro-VM**
because the macro-VM never emits them in its own source: 11
(MethodCall), 18 (IfExpr), 19 (Paren), 34 (Repeat), 39 (Continue), 40
(Do). User code using these features works fine because the macro-VM
implements them when interpreting user bytecode.


## Scoping

* Slots are per-function, 1-based, never reused. Every `local`
  declaration in source allocates a fresh slot. This makes closures
  that capture a loop-iteration variable see *that iteration's* boxed
  cell, matching Luau's `local`-per-iteration semantics.
* Upvalues are resolved at compile time. Each function's upvalue list
  is baked into a Lua expression `{pa.S[3], pa.U[1], ...}` by the
  predecoder, evaluated once at closure-build time.
* Free identifiers compile to `Global` atoms (tag 8); they read/write
  the caller-provided environment table by name. Writes go through
  the micro-VM's `t == 22` handler.

# Bytecode format

All integers are LEB128 unsigned varints unless stated.
Signed integers are zig-zag encoded varints.
Doubles are 8 bytes little-endian (`string.pack("<d", x)`).
Strings are `varint(length)` followed by raw bytes.

## Top-level layout

```
  varint nk                       constant count
  nk × (u8 kind, payload)         the constant pool
  varint nf                       function count
  nf  × function record           the function pool
```

The "main chunk" is `F[1]`. Execution begins there.

## Constant kinds

| kind | meaning           | payload                       |
|------|-------------------|-------------------------------|
| 0    | nil               | (none)                        |
| 1    | false             | (none)                        |
| 2    | true              | (none)                        |
| 3    | int               | zig-zag varint                |
| 4    | double            | 8 raw bytes, little-endian    |
| 5    | string            | varint length + raw bytes     |

The compiler may store any number as either int or double at its
discretion. The micro-VM only handles int + string (which is all the
macro-VM emits).

## Function record

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

## Atom tags

Each atom is `u8 tag` followed by tag-specific payload. The micro-VM
decodes them into Lua arrays `{tag, ...payload}` for the tree-walker.

### Expression tags

| tag | name        | payload                                  |
|-----|-------------|------------------------------------------|
| 1   | Nil         | (none)                                   |
| 2   | True        | (none)                                   |
| 3   | False       | (none)                                   |
| 4   | Const       | varint ki                                |
| 5   | Vararg      | (none) — must be inside a vararg fn      |
| 6   | Local       | varint slot                              |
| 7   | Upval       | varint idx                               |
| 8   | Env         | varint ki — `env[K[ki]]`                 |
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

### Statement tags

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

### Block tag

| tag | name  | payload                                       |
|-----|-------|-----------------------------------------------|
| 50  | Block | varint nstmts, nstmts × (varint line, atom stmt) |

## Operator codes

### Binary (u8)

| code | op  | code | op  |
|------|-----|------|-----|
| 1    | +   | 8    | ..  |
| 2    | -   | 9    | ==  |
| 3    | *   | 10   | ~=  |
| 4    | /   | 11   | <   |
| 5    | //  | 12   | <=  |
| 6    | %   | 13   | >   |
| 7    | ^   | 14   | >=  |

### Unary (u8)

| code | op    |
|------|-------|
| 1    | -     |
| 2    | not   |
| 3    | #     |

Logical `and` / `or` are tags 16 / 17, not BinOp codes, so the runtime
can short-circuit.

## Multi-return semantics

Atoms with tags 5, 10, and 11 can produce more than one value. The
runtime expands them only when they're at the tail position of a
value list (last arg in a call, last entry in a table constructor's
array section, last value in a return / multi-assign / local-decl).

For Call / MethodCall, the trailing `multret` u8 controls whether the
result is kept multi (1) or truncated to one value (0). The compiler
sets `multret = 0` for parenthesized calls and `multret = 1` everywhere
else; the runtime then truncates further in single-value contexts.

## Scoping

* Slots are per-function, 1-based, never reused. Every `local` declaration
  in source allocates a fresh slot. This makes closures that capture a
  loop-iteration variable see *that iteration's* boxed cell, matching
  Lua's `local`-per-iteration semantics.
* Upvalues are resolved at compile time. Each `Upval` index references
  the closure's own upvalue array, filled at closure creation by
  following the `fromKind`/`index` chain into the enclosing function's
  locals or upvalues.
* Free identifiers compile to `Env` atoms; they read/write the caller-
  provided environment table by name.

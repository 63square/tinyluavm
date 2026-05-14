#!/usr/bin/env python3
"""Pre-decode a .bin file into a Lua source expression returning (K, F).

Optionally rewrites atoms to shrink the micro-VM:
  --rewrite-ops  : BinOp/UnOp atoms -> Call(global B1..B14, U1..U3)
  --fold-bool    : Nil/True/False atoms -> Const ref
"""
from __future__ import annotations
import sys, pathlib, struct, argparse, collections

def read_bin(data: bytes):
    p = [0]
    def rb():
        b = data[p[0]]; p[0] += 1
        return b
    def rv():
        r,s = 0,0
        while True:
            c = data[p[0]]; p[0] += 1
            r += (c & 0x7f) << s
            if c < 128: return r
            s += 7
    def rs():
        n = rv(); s = data[p[0]:p[0]+n]; p[0] += n
        return s.decode("latin-1")
    def rf64():
        v = struct.unpack("<d", data[p[0]:p[0]+8])[0]; p[0] += 8
        return v
    nk = rv()
    K = []
    for _ in range(nk):
        k = rb()
        if   k == 0: K.append(None)
        elif k == 1: K.append(False)
        elif k == 2: K.append(True)
        elif k == 3:
            n = rv(); h = n & 1
            K.append((n >> 1) * (1 - 2*h) - h)
        elif k == 4: K.append(rf64())
        elif k == 5: K.append(rs())
        else: raise Exception(f"unknown const kind {k}")

    def ra():
        t = rb()
        if t in (1,2,3,5,38,39): return [t]
        if t in (4,6,7,8,12):    return [t, rv()]
        if t == 9:               return [t, ra(), ra()]
        if t == 10:
            fn = ra(); n = rv()
            a = [ra() for _ in range(n)]
            return [t, fn, a, rb()]
        if t == 11:
            o = ra(); ki = rv(); n = rv()
            a = [ra() for _ in range(n)]
            return [t, o, ki, a, rb()]
        if t == 13:
            na = rv(); nh = rv()
            A = [ra() for _ in range(na)]
            H = [[ra(), ra()] for _ in range(nh)]
            return [t, A, H]
        if t == 14: op = rb(); return [t, op, ra(), ra()]
        if t == 15: op = rb(); return [t, op, ra()]
        if t in (16,17): return [t, ra(), ra()]
        if t == 18: return [t, ra(), ra(), ra()]
        if t == 19: return [t, ra()]
        if t == 30:
            n = rv(); L = [ra() for _ in range(n)]
            m = rv(); R = [ra() for _ in range(m)]
            return [t, L, R]
        if t == 31:
            n = rv(); S = [rv() for _ in range(n)]
            m = rv(); R = [ra() for _ in range(m)]
            return [t, S, R]
        if t == 32:
            c = ra(); th = ra(); n = rv()
            E = [[ra(), ra()] for _ in range(n)]
            he = rb()
            el = ra() if he == 1 else None
            return [t, c, th, E, el]
        if t == 33: return [t, ra(), ra()]
        if t == 34: return [t, ra(), ra()]
        if t == 35:
            s = rv(); a = ra(); c = ra(); hs = rb()
            st = ra() if hs == 1 else None
            body = ra()
            return [t, s, a, c, st, body]
        if t == 36:
            n = rv(); S = [rv() for _ in range(n)]
            m = rv(); R = [ra() for _ in range(m)]
            return [t, S, R, ra()]
        if t == 37:
            n = rv(); return [t, [ra() for _ in range(n)]]
        if t == 40: return [t, ra()]
        if t == 41: return [t, ra()]
        if t == 50:
            n = rv(); items = []; lines = []
            for _ in range(n):
                lines.append(rv()); items.append(ra())
            return [t, items, lines]
        raise Exception(f"unknown atom tag {t}")

    nf = rv()
    F = []
    for _ in range(nf):
        np = rb(); va = rb(); nu = rv()
        L = []
        for _ in range(nu):
            L.append([rb(), rv()])
        body = ra()
        F.append({"np": np, "va": va, "L": L, "b": body})
    return K, F

# atom-shape table: tag -> (atom_slots, atomlist_slots, pairlist_slots)
SHAPES = {
    # 6 (Local/Upval after unify): [6, "S"/"U", slot] -- no atom children
    6: ([], [], []),
    20: ([3], [], []),  # after unify: [20, storage, slot, valueAtom]
    21: ([2], [], []),  # not used after unify
    22: ([2], [], []),
    23: ([1,2,3], [], []),
    9: ([1,2], [], []),
    10: ([1], [2], []),
    11: ([1], [3], []),
    13: ([], [1], [2]),
    14: ([2,3], [], []),
    15: ([2], [], []),
    16: ([1,2], [], []),
    17: ([1,2], [], []),
    18: ([1,2,3], [], []),
    19: ([1], [], []),
    30: ([], [1,2], []),
    31: ([], [2], []),
    32: ([1,2,4], [], [3]),  # before flatten
    # After flatten: shape is ([2], [], [1]) -- branches is pair_list at index 1, else is atom at index 2
    33: ([1,2], [], []),
    34: ([1,2], [], []),
    35: ([2,3,4,5], [], []),  # original layout if step present
    # After dropping step, [35, slot, from, to, body] - atoms at 2,3,4. Walk will see len==5 and only walk valid indexes anyway via `if i < len(atom)`
    36: ([3], [2], []),  # original: [36, slots, sources, body]; after force_gfor3 flatten 2-slot: [36, s1, s2, sources, body]
    37: ([], [1], []),
    40: ([1], [], []),
    41: ([1], [], []),
    50: ([], [1], []),
}

def walk(atom, fn):
    if not isinstance(atom, list) or not atom: return atom
    t = atom[0]
    shape = SHAPES.get(t)
    if shape:
        ats, lats, plats = shape
        for i in ats:
            if i < len(atom) and atom[i] is not None:
                atom[i] = walk(atom[i], fn)
        for i in lats:
            if i < len(atom):
                L = atom[i]
                for j in range(len(L)): L[j] = walk(L[j], fn)
        for i in plats:
            if i < len(atom):
                L = atom[i]
                for j in range(len(L)):
                    L[j][0] = walk(L[j][0], fn)
                    L[j][1] = walk(L[j][1], fn)
    return fn(atom)

def count_tags(F):
    c = collections.Counter()
    def visit(a):
        if not isinstance(a, list) or not a: return a
        c[a[0]] += 1
        return a
    for tr in F:
        walk(tr['b'], visit)
    return c

def rewrite(K, F, *, for_micro=False):
    """Apply rewrites to the AST.

    When `for_micro` is False, only the rewrites that the macro-VM can also
    handle natively (in source) are applied. This keeps the output consumable
    by the macro-VM when used for pre-decoded user programs.

    When `for_micro` is True, additionally apply the micro-VM-specific atom
    rewrites that shrink the micro-VM source: Local/Upval unify, If flatten,
    NumericFor step drop, GenericFor 2-slot flatten, Assign split.
    """
    new_consts = []
    def add_const(v):
        new_consts.append(v)
        return len(K) + len(new_consts)

    # All the rewrites are micro-VM-only. The macro-VM handles the original
    # atom set natively (Nil/True/False/BinOp/UnOp/GenericFor with __iter
    # fallback), so when we're predecoding USER code (for_micro=False) we
    # leave it alone and only convert the wire format to JSON-friendly tables.
    nil_idx = true_idx = false_idx = None
    binop_base = unop_base = next_name_idx = None
    if for_micro:
        nil_idx       = add_const(None)
        true_idx      = add_const(True)
        false_idx     = add_const(False)
        binop_base    = len(K) + len(new_consts) + 1
        for i in range(1, 15): add_const(f"B{i}")
        unop_base     = len(K) + len(new_consts) + 1
        for i in range(1, 4):  add_const(f"U{i}")
        next_name_idx = add_const("next")

    def fn(atom):
        if not isinstance(atom, list) or not atom: return atom
        if not for_micro: return atom
        t = atom[0]
        # Fold Nil/True/False to Const refs (saves three branches in the micro-VM)
        if t == 1: return [4, nil_idx]
        if t == 2: return [4, true_idx]
        if t == 3: return [4, false_idx]
        # Rewrite BinOp/UnOp atoms as Call atoms targeting env-supplied helpers.
        if t == 14:
            return [10, [8, binop_base + atom[1] - 1], [atom[2], atom[3]], 1]
        if t == 15:
            return [10, [8, unop_base + atom[1] - 1], [atom[2]], 1]
        # GenericFor: force 3-source form and flatten the 2-slot variant.
        # Only safe in `for_micro` mode -- user code may pass `pairs(t)` which
        # is a single Call atom returning 3 values via multret expansion; we
        # must not wrap it in [Global("next"), src, nil] as that would treat
        # the call's first return value as the entire iterator.
        if t == 36:
            slots, vals, body = atom[1], atom[2], atom[3]
            if len(vals) == 1:
                vals = [[8, next_name_idx], vals[0], [4, nil_idx]]
            if len(slots) == 2:
                return [36, slots[0], slots[1], vals, body]
            return [36, slots, vals, body]
        # Local/Upval unify
        if t == 6:
            return [6, Raw('"S"'), atom[1]]
        if t == 7:
            return [6, Raw('"U"'), atom[1]]
        # NumericFor step drop (when step is None)
        if t == 35 and atom[4] is None:
            return [35, atom[1], atom[2], atom[3], atom[5]]
        # If flatten: prepend (cond0, then0) to elseifs list
        if t == 32:
            c0, t0, elifs, el = atom[1], atom[2], atom[3], atom[4]
            return [32, [[c0, t0]] + elifs, el]
        # Single-target Assign split
        if t == 30:
            targets, values = atom[1], atom[2]
            def is_local(g):
                return g[0] == 6 and isinstance(g[1], Raw) and g[1].s == '"S"'
            def is_upval(g):
                return g[0] == 6 and isinstance(g[1], Raw) and g[1].s == '"U"'
            if len(targets) == 1 and len(values) == 1:
                g, v = targets[0], values[0]
                if is_local(g):
                    return [20, Raw('"S"'), g[2], v]
                if is_upval(g):
                    return [20, Raw('"U"'), g[2], v]
                if g[0] == 8:
                    return [22, g[1], v]
                if g[0] == 9:
                    return [23, g[1], g[2], v]
            if all(is_local(g) for g in targets):
                slots = [g[2] for g in targets]
                return [30, slots, values]
        return atom
    for tr in F:
        tr['b'] = walk(tr['b'], fn)
    return list(K) + new_consts, F

class Raw:
    """Wrapper for emitting raw Lua source."""
    __slots__ = ("s",)
    def __init__(self, s): self.s = s

def emit(v, out):
    if v is None: out.append("nil")
    elif v is False: out.append("false")
    elif v is True: out.append("true")
    elif isinstance(v, Raw): out.append(v.s)
    elif isinstance(v, int): out.append(str(v))
    elif isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            out.append(f"{int(v)}.0")
        else:
            out.append(repr(v))
    elif isinstance(v, str): out.append(lua_str(v))
    elif isinstance(v, list):
        out.append("{")
        for i, x in enumerate(v):
            if i: out.append(",")
            emit(x, out)
        out.append("}")
    elif isinstance(v, dict):
        out.append("{")
        first = True
        for k, val in v.items():
            if not first: out.append(",")
            first = False
            out.append(f"{k}=")
            emit(val, out)
        out.append("}")
    else:
        raise Exception(f"bad {type(v)}")

def lua_str(s: str) -> str:
    out = ['"']
    for ch in s:
        b = ord(ch)
        if   b == 0x22: out.append('\\"')
        elif b == 0x5c: out.append('\\\\')
        elif b == 0x0a: out.append('\\n')
        elif b == 0x0d: out.append('\\r')
        elif b == 0x09: out.append('\\t')
        elif b == 0x00: out.append('\\0')
        elif 32 <= b < 127: out.append(chr(b))
        else: out.append(f"\\{b}")
    out.append('"')
    return "".join(out)

def _predecode_one(bin_path: pathlib.Path, for_micro: bool):
    """Read a .bin file and return (K, F) in the JSON-friendly shape.

    Returns the K list and a list of {np, va, L, b} dicts. When for_micro
    is set, applies the micro-VM-specific atom rewrites and uses string
    storage markers in L; otherwise uses raw int kinds the macro-VM
    consumes natively.
    """
    K, F = read_bin(bin_path.read_bytes())
    K, F = rewrite(K, F, for_micro=for_micro)
    new_F = []
    for tr in F:
        if for_micro:
            L = [[("S" if kind == 0 else "U"), idx] for kind, idx in tr['L']]
        else:
            L = [[kind, idx] for kind, idx in tr['L']]
        new_F.append({"np": tr['np'], "va": tr['va'], "L": L, "b": tr['b']})
    return K, new_F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="macro-VM bytecode (.bin)")
    ap.add_argument("output", help="output file path")
    ap.add_argument("--for-micro", action="store_true",
                    help="apply the micro-VM-specific atom rewrites "
                         "(use when predecoding the macro-VM itself)")
    ap.add_argument("--user", metavar="PATH",
                    help="also predecode this user-program bytecode and "
                         "emit a combined `inputData` payload "
                         "`{macro=[K,F], user=[K,F]}`")
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--json", action="store_true",
                    help="emit pure JSON instead of a Luau module")
    args = ap.parse_args()

    in_path = pathlib.Path(args.input)
    out_path = pathlib.Path(args.output)

    if args.census:
        K, F = read_bin(in_path.read_bytes())
        cnt = count_tags(F)
        for tag, n in sorted(cnt.items()): print(f"  tag {tag}: {n}")
        return

    macro_K, macro_F = _predecode_one(in_path, for_micro=args.for_micro)
    user_K = user_F = None
    if args.user:
        # User code is consumed by the macro-VM at runtime; never apply
        # the micro-VM-specific atom rewrites.
        user_K, user_F = _predecode_one(pathlib.Path(args.user), for_micro=False)

    if args.json:
        import json
        def to_json_safe(v):
            if isinstance(v, Raw):
                s = v.s
                if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
                    return s[1:-1]
                raise Exception(f"unhandled Raw: {s!r}")
            if isinstance(v, list):
                return [to_json_safe(x) for x in v]
            if isinstance(v, dict):
                return {k: to_json_safe(x) for k, x in v.items()}
            return v
        if args.user:
            # Single-letter keys "m" and "u" keep the wire payload small and
            # match the micro-VM's accesses (D.m / D.u).
            payload = {
                "m": [to_json_safe(macro_K), to_json_safe(macro_F)],
                "u": [to_json_safe(user_K),  to_json_safe(user_F)],
            }
        else:
            payload = [to_json_safe(macro_K), to_json_safe(macro_F)]
        out_path.write_text(json.dumps(payload, separators=(",", ":")),
                            encoding="utf-8", newline="")
        print(f"wrote {out_path.stat().st_size} bytes (JSON)")
        return

    # Default Luau-module output.
    parts = ["--!nocheck\nreturn "]
    if args.user:
        parts.append("{m={")
        emit(macro_K, parts); parts.append(",")
        emit(macro_F, parts); parts.append("},u={")
        emit(user_K, parts); parts.append(",")
        emit(user_F, parts); parts.append("}}\n")
    else:
        parts.append("{")
        emit(macro_K, parts); parts.append(",")
        emit(macro_F, parts); parts.append("}\n")
    out_path.write_text("".join(parts), encoding="latin-1", newline="")
    print(f"wrote {out_path.stat().st_size} bytes")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
LuaU -> compact bytecode compiler for the embedded interpreter in run.luau.

Usage:
    python compiler.py input.luau output.bin

Scope:
  * Full Lua 5.1/5.3 syntax + LuaU additions: continue, if-expression,
    compound assignments (+= -= *= /= //= %= ^= ..=), generalized for-in,
    string interpolation (backtick strings), generic-typed declarations
    (types are parsed and discarded), `::` cast operator (discarded),
    `type X = ...` / `export type` (parsed and discarded).
  * Bitwise ops are not in Luau syntax (Luau uses bit32 library), so we
    don't accept &|~<<>> as operators. (`~` is unary not-equal-only-in-pair;
    we treat `~=` as inequality.)
  * `goto`/labels: not supported (Luau dropped them; we error if seen).

Output format: see format.md
"""

from __future__ import annotations
import sys, struct, os
from dataclasses import dataclass, field
from typing import Any

# ----------------------------- Lexer ---------------------------------------

KEYWORDS = {
    "and","break","do","else","elseif","end","false","for","function","if",
    "in","local","nil","not","or","repeat","return","then","true","until",
    "while",
    # NOTE: "continue", "type", and "export" are contextual keywords in Luau.
    # We lex them as NAME tokens and recognize them as keywords only when they
    # appear in their statement positions (see parser).
}

class Tok:
    __slots__ = ("k","v","line")
    def __init__(self,k,v,line):
        self.k=k; self.v=v; self.line=line
    def __repr__(self): return f"Tok({self.k!r},{self.v!r})"

def lex(src: str):
    i, n = 0, len(src)
    line = 1
    toks = []
    def err(m): raise SyntaxError(f"line {line}: {m}")
    while i < n:
        c = src[i]
        if c in " \t\r":
            i += 1; continue
        if c == "\n":
            line += 1; i += 1; continue
        if c == "-" and i+1 < n and src[i+1] == "-":
            i += 2
            # long comment?
            if i < n and src[i] == "[":
                j = i+1
                eqs = 0
                while j < n and src[j] == "=":
                    eqs += 1; j += 1
                if j < n and src[j] == "[":
                    close = "]" + "="*eqs + "]"
                    e = src.find(close, j+1)
                    if e < 0: err("unterminated long comment")
                    line += src[i:e].count("\n")
                    i = e + len(close)
                    continue
            # line comment
            while i < n and src[i] != "\n": i += 1
            continue
        if c == "[":
            # long string?
            j = i+1; eqs = 0
            while j < n and src[j] == "=":
                eqs += 1; j += 1
            if j < n and src[j] == "[":
                close = "]" + "="*eqs + "]"
                start = j+1
                # optional first newline ignored (handle both \n and \r\n)
                if start < n and src[start] == "\r":
                    start += 1
                    if start < n and src[start] == "\n": start += 1
                    line += 1
                elif start < n and src[start] == "\n":
                    start += 1; line += 1
                e = src.find(close, start)
                if e < 0: err("unterminated long string")
                s = src[start:e]
                # Lua: convert \r\n and lone \r to \n inside long strings
                s = s.replace("\r\n", "\n").replace("\r", "\n")
                line += s.count("\n")
                toks.append(Tok("STR", s, line))
                i = e + len(close)
                continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            if w in KEYWORDS:
                toks.append(Tok(w, w, line))
            else:
                toks.append(Tok("NAME", w, line))
            i = j; continue
        if c.isdigit() or (c == "." and i+1 < n and src[i+1].isdigit()):
            j = i
            if c == "0" and i+1 < n and src[i+1] in "xX":
                j += 2
                while j < n and (src[j] in "0123456789abcdefABCDEF._pP+-" and
                                 not (src[j] in "+-" and src[j-1] not in "pP")):
                    j += 1
                w = src[i:j]
                try: v = int(w, 16) if not any(ch in w for ch in ".pP") else float.fromhex(w)
                except Exception: err(f"bad number {w}")
            elif c == "0" and i+1 < n and src[i+1] in "bB":
                j += 2
                while j < n and src[j] in "01_":
                    j += 1
                w = src[i:j].replace("_","")
                v = int(w[2:], 2)
            else:
                while j < n and (src[j].isdigit() or src[j] == "."):
                    j += 1
                if j < n and src[j] in "eE":
                    j += 1
                    if j < n and src[j] in "+-": j += 1
                    while j < n and src[j].isdigit(): j += 1
                w = src[i:j]
                v = float(w) if ("." in w or "e" in w or "E" in w) else int(w)
            toks.append(Tok("NUM", v, line))
            i = j; continue
        if c == '"' or c == "'":
            q = c; j = i+1; buf = []
            while j < n and src[j] != q:
                if src[j] == "\\":
                    if j+1 >= n: err("bad escape")
                    e = src[j+1]
                    if e == "n": buf.append("\n"); j += 2
                    elif e == "t": buf.append("\t"); j += 2
                    elif e == "r": buf.append("\r"); j += 2
                    elif e == "\\": buf.append("\\"); j += 2
                    elif e == "'": buf.append("'"); j += 2
                    elif e == '"': buf.append('"'); j += 2
                    elif e == "a": buf.append("\a"); j += 2
                    elif e == "b": buf.append("\b"); j += 2
                    elif e == "f": buf.append("\f"); j += 2
                    elif e == "v": buf.append("\v"); j += 2
                    elif e == "\n": buf.append("\n"); line += 1; j += 2
                    elif e == "\r":
                        buf.append("\n"); line += 1
                        if j+2 < n and src[j+2] == "\n": j += 3
                        else: j += 2
                    elif e == "x":
                        buf.append(chr(int(src[j+2:j+4],16))); j += 4
                    elif e == "u":
                        # \u{XXXX} unicode escape -- emit UTF-8 bytes
                        if j+2 < n and src[j+2] == "{":
                            k = j+3
                            while k < n and src[k] != "}": k += 1
                            if k >= n: err("bad \\u escape")
                            cp = int(src[j+3:k], 16)
                            # convert to UTF-8 byte string -> append each byte as latin-1 char
                            try:
                                utf8 = chr(cp).encode("utf-8")
                            except Exception:
                                err("bad \\u codepoint")
                            for b8 in utf8: buf.append(chr(b8))
                            j = k+1
                        else:
                            err("bad \\u escape")
                    elif e == "z":
                        j += 2
                        while j < n and src[j] in " \t\r\n":
                            if src[j] == "\n": line += 1
                            j += 1
                    elif e.isdigit():
                        k = j+1; m = 0
                        while m < 3 and k < n and src[k].isdigit():
                            k += 1; m += 1
                        buf.append(chr(int(src[j+1:k]))); j = k
                    else:
                        buf.append(e); j += 2
                else:
                    if src[j] == "\n": err("newline in string")
                    buf.append(src[j]); j += 1
            if j >= n: err("unterminated string")
            toks.append(Tok("STR","".join(buf), line))
            i = j+1; continue
        if c == "`":
            # backtick string: produces a sequence of string pieces and {expr} pieces
            j = i+1
            pieces = []
            buf = []
            while j < n and src[j] != "`":
                if src[j] == "\\" and j+1 < n:
                    e = src[j+1]
                    if e == "n": buf.append("\n"); j += 2; continue
                    elif e == "t": buf.append("\t"); j += 2; continue
                    elif e == "r": buf.append("\r"); j += 2; continue
                    elif e == "a": buf.append("\a"); j += 2; continue
                    elif e == "b": buf.append("\b"); j += 2; continue
                    elif e == "f": buf.append("\f"); j += 2; continue
                    elif e == "v": buf.append("\v"); j += 2; continue
                    elif e == "\\": buf.append("\\"); j += 2; continue
                    elif e == "`": buf.append("`"); j += 2; continue
                    elif e == "{": buf.append("{"); j += 2; continue
                    elif e == "}": buf.append("}"); j += 2; continue
                    elif e == "'": buf.append("'"); j += 2; continue
                    elif e == '"': buf.append('"'); j += 2; continue
                    elif e == "x":
                        buf.append(chr(int(src[j+2:j+4],16))); j += 4; continue
                    elif e == "u" and j+2 < n and src[j+2] == "{":
                        k = j+3
                        while k < n and src[k] != "}": k += 1
                        if k >= n: err("bad \\u escape")
                        cp = int(src[j+3:k], 16)
                        for b8 in chr(cp).encode("utf-8"): buf.append(chr(b8))
                        j = k+1; continue
                    elif e.isdigit():
                        k = j+1; m = 0
                        while m < 3 and k < n and src[k].isdigit():
                            k += 1; m += 1
                        buf.append(chr(int(src[j+1:k]))); j = k; continue
                    else:
                        buf.append(e); j += 2; continue
                if src[j] == "{":
                    pieces.append(("S","".join(buf))); buf = []
                    # parse expression up to matching }
                    depth = 1; k = j+1; start = k
                    while k < n and depth > 0:
                        if src[k] == "{": depth += 1
                        elif src[k] == "}": depth -= 1
                        if depth == 0: break
                        k += 1
                    if k >= n: err("unterminated interp expr")
                    expr_src = src[start:k]
                    pieces.append(("E", expr_src, line))
                    j = k+1; continue
                if src[j] == "\n": line += 1
                buf.append(src[j]); j += 1
            if j >= n: err("unterminated backtick string")
            pieces.append(("S","".join(buf)))
            toks.append(Tok("INTERP", pieces, line))
            i = j+1; continue
        # multi-char operators
        two = src[i:i+2]; three = src[i:i+3]
        if three == "...":
            toks.append(Tok("...","...", line)); i += 3; continue
        if three in ("..=","//="):
            toks.append(Tok(three, three, line)); i += 3; continue
        if two in ("==","~=","<=",">=","..","::","+=","-=","*=","/=","%=","^=","//","->"):
            toks.append(Tok(two, two, line)); i += 2; continue
        if c in "+-*/%^#=<>(){}[];:,.&|~?":
            toks.append(Tok(c, c, line)); i += 1; continue
        err(f"unexpected char {c!r}")
    toks.append(Tok("EOF","",line))
    return toks

# ----------------------------- AST nodes -----------------------------------
# We use nested tuples/lists to match the bytecode shape directly.
# Tags as named constants:

# Exprs
NIL=1; TRUE=2; FALSE=3; KCONST=4; VARARG=5
LOCAL=6; UPVAL=7; ENV=8
INDEX=9; CALL=10; MCALL=11
FUNC=12; TABLE=13; BINOP=14; UNOP=15
ANDN=16; ORN=17; IFEXPR=18
# Stmts
ASSIGN=30; LDECL=31; IFN=32; WHILEN=33; REPEATN=34
NFOR=35; GFOR=36; RET=37; BRK=38; CONT=39; DON=40; ESTMT=41
BLOCK=50

BINOP_MAP = {
    "+":1,"-":2,"*":3,"/":4,"//":5,"%":6,"^":7,"..":8,
    "==":9,"~=":10,"<":11,"<=":12,">":13,">=":14,
}
UNOP_MAP = {"-":1,"not":2,"#":3}

# ----------------------------- Parser --------------------------------------

class Parser:
    def __init__(self, toks):
        self.t = toks; self.p = 0
    def peek(self, k=0): return self.t[self.p+k]
    def at(self, *kinds): return self.peek().k in kinds
    def eat(self, k, v=None):
        tk = self.peek()
        if tk.k != k or (v is not None and tk.v != v):
            raise SyntaxError(f"line {tk.line}: expected {k}{'='+v if v else ''}, got {tk.k}={tk.v!r}")
        self.p += 1; return tk
    def match(self, k, v=None):
        tk = self.peek()
        if tk.k == k and (v is None or tk.v == v):
            self.p += 1; return tk
        return None

    # ---- type skipping (LuaU types) ----
    # A complete LuaU type grammar, used to consume and discard type
    # annotations. After skip_type() returns, the parser position is just past
    # a full type expression and ready for whatever follows in the surrounding
    # grammar (`=`, `,`, `)`, etc.).

    # Tokens that can start a type atom.
    _TYPE_START = {"NAME","nil","true","false","STR","NUM","(","{","..."}

    def skip_type(self):
        """Consume one full type expression and discard it."""
        self._parse_type_outer()

    def skip_return_type(self):
        # A return type after `: ` in a function declaration. Same as a regular type.
        self.skip_type()

    def _parse_type_outer(self):
        """Type with union/intersection continuations."""
        # Optional leading `|` or `&` (Luau allows these).
        if self.peek().k == "|" or self.peek().k == "&":
            self.p += 1
        self._parse_type_one()
        # Continuation: '?' (optional), '|' Type, '&' Type, '->' Type (function type)
        while True:
            tk = self.peek()
            if tk.k == "?":
                self.p += 1
            elif tk.k == "|" or tk.k == "&":
                self.p += 1
                self._parse_type_one()
            elif tk.k == "->":
                self.p += 1
                self._parse_type_one()
            else:
                break

    def _parse_type_one(self):
        """One type atom (no continuations)."""
        tk = self.peek()
        if tk.k == "<":
            # Generic function type: `<T,U>(args...) -> Ret`
            self._skip_balanced("<", ">")
            # must be followed by a function type
            if self.peek().k == "(":
                self._skip_balanced("(", ")")
                if self.peek().k == "->":
                    self.p += 1
                    self._parse_type_one()
            return
        if tk.k == "...":
            # Variadic type: `...T` or just `...`
            self.p += 1
            if self.peek().k in self._TYPE_START:
                self._parse_type_one()
            return
        if tk.k in ("nil","true","false","STR","NUM"):
            self.p += 1
            return
        if tk.k == "NAME":
            # contextual `typeof` keyword
            if tk.v == "typeof":
                self.p += 1
                if self.peek().k == "(":
                    self._skip_balanced("(", ")")
                return
            self.p += 1
            # Module-qualified: Name.Name
            while self.peek().k == "." and self.peek(1).k == "NAME":
                self.p += 2
            # Generic args: <T,U>
            if self.peek().k == "<":
                self._skip_balanced("<", ">")
            return
        if tk.k == "(":
            # Parenthesized type, function param list, or return tuple.
            self._skip_balanced("(", ")")
            # Optional return continuation: `-> Type` (function type)
            if self.peek().k == "->":
                self.p += 1
                self._parse_type_one()
            return
        if tk.k == "{":
            # Table type body. Skip balanced; the body may contain `:` and `,`
            # but those are inside the braces.
            self._skip_balanced("{", "}")
            return
        # Otherwise: not a recognizable type-start. Just bail to let the caller
        # detect the error if any (we'd rather over-consume than crash).
        return

    def _skip_balanced(self, open_k, close_k):
        # Helper that skips a balanced delimited region, ignoring everything inside.
        assert self.peek().k == open_k
        self.p += 1
        depth = 1
        while depth > 0:
            tk = self.peek()
            if tk.k == "EOF": return
            if tk.k == open_k: depth += 1
            elif tk.k == close_k: depth -= 1
            self.p += 1

    def skip_generic_params(self):
        # `<T, U, ...>` — generic type parameter list. We just skip until the
        # matching `>`.
        if self.match("<"):
            depth = 1
            while depth > 0:
                tk = self.peek()
                if tk.k == "EOF": raise SyntaxError("unterminated <")
                if tk.k == "<": depth += 1
                elif tk.k == ">": depth -= 1
                self.p += 1

    # ---- program ----
    def parse_chunk(self):
        b = self.block(top=True)
        self.eat("EOF")
        return b

    def block(self, top=False):
        stmts = []  # list of (line, stmt) pairs
        while True:
            tk = self.peek()
            if tk.k in ("EOF","end","else","elseif","until"): break
            if tk.k == "return":
                rl = tk.line
                self.p += 1
                args = []
                if not self.at("EOF","end","else","elseif","until",";"):
                    args = self.exprlist()
                self.match(";")
                stmts.append((rl, (RET, args)))
                break
            sl = tk.line
            s = self.stmt()
            if s is not None:
                stmts.append((sl, s))
        return (BLOCK, stmts)

    def is_ctx_kw(self, off=0, *names):
        """Check if token at offset is a contextual keyword (NAME with given value)."""
        tk = self.peek(off)
        return tk.k == "NAME" and tk.v in names

    def stmt(self):
        tk = self.peek()
        k = tk.k
        if k == ";":
            self.p += 1; return None
        if k == "if": return self.stmt_if()
        if k == "while": return self.stmt_while()
        if k == "do":
            self.p += 1
            b = self.block(); self.eat("end")
            return (DON, b)
        if k == "for": return self.stmt_for()
        if k == "repeat": return self.stmt_repeat()
        if k == "function": return self.stmt_function()
        if k == "local": return self.stmt_local()
        if k == "break":
            self.p += 1; return (BRK,)
        # contextual `continue`: only a keyword when followed by something that
        # cannot continue an expression (i.e., next stmt token).
        if self.is_ctx_kw(0, "continue"):
            nxt = self.peek(1)
            if nxt.k in (";", "end", "else", "elseif", "until", "EOF") or self.is_stmt_start(nxt):
                self.p += 1
                return (CONT,)
        # contextual `type`: only a keyword when followed by a NAME and `<` or `=`
        if self.is_ctx_kw(0, "type"):
            n1 = self.peek(1); n2 = self.peek(2)
            if n1.k == "NAME" and (n2.k == "=" or n2.k == "<"):
                self.p += 1
                self.eat("NAME")
                self.skip_generic_params()
                self.eat("=")
                self.skip_type_stmt()
                return None
        # contextual `export type`
        if self.is_ctx_kw(0, "export") and self.is_ctx_kw(1, "type"):
            self.p += 2
            self.eat("NAME")
            self.skip_generic_params()
            self.eat("=")
            self.skip_type_stmt()
            return None
        # Else: expression-statement or assignment
        return self.stmt_expr_or_assign()

    def skip_type_stmt(self):
        # Body of a `type X = ...` alias: a single type expression.
        self.skip_type()

    def is_stmt_start(self, tk):
        if tk.k in ("if","while","do","for","repeat","function","local","break","return"):
            return True
        if tk.k == "NAME" and tk.v in ("continue","type","export"):
            return True
        return False

    def stmt_if(self):
        self.eat("if")
        c = self.expr()
        self.eat("then")
        th = self.block()
        elifs = []
        el = None
        while self.match("elseif"):
            ec = self.expr()
            self.eat("then")
            eb = self.block()
            elifs.append((ec, eb))
        if self.match("else"):
            el = self.block()
        self.eat("end")
        return (IFN, c, th, elifs, el)

    def stmt_while(self):
        self.eat("while")
        c = self.expr()
        self.eat("do")
        b = self.block()
        self.eat("end")
        return (WHILEN, c, b)

    def stmt_repeat(self):
        self.eat("repeat")
        b = self.block()
        self.eat("until")
        c = self.expr()
        return (REPEATN, b, c)

    def stmt_for(self):
        self.eat("for")
        n1 = self.eat("NAME").v
        # optional type
        if self.match(":"):
            self.skip_type()
        if self.match("="):
            a = self.expr(); self.eat(",")
            bv = self.expr()
            cv = None
            if self.match(","): cv = self.expr()
            self.eat("do")
            body = self.block(); self.eat("end")
            return ("NFOR_RAW", n1, a, bv, cv, body)
        names = [n1]
        while self.match(","):
            names.append(self.eat("NAME").v)
            if self.match(":"): self.skip_type()
        self.eat("in")
        exprs = self.exprlist()
        self.eat("do")
        body = self.block(); self.eat("end")
        return ("GFOR_RAW", names, exprs, body)

    def funcbody(self, ismethod=False):
        # < generics >? ( params ) (: rettype)? block end
        self.skip_generic_params()
        self.eat("(")
        params = []
        if ismethod:
            params.append("self")
        is_vararg = False
        if not self.at(")"):
            while True:
                if self.match("..."):
                    is_vararg = True
                    if self.match(":"): self.skip_type()
                    break
                pname = self.eat("NAME").v
                if self.match(":"): self.skip_type()
                params.append(pname)
                if not self.match(","): break
        self.eat(")")
        if self.match(":"):
            self.skip_return_type()
        body = self.block()
        self.eat("end")
        return params, is_vararg, body

    def stmt_function(self):
        self.eat("function")
        # name: Name { . Name } [ : Name ]
        n0 = self.eat("NAME").v
        chain = [n0]
        is_method = False
        while self.match("."):
            chain.append(self.eat("NAME").v)
        if self.match(":"):
            chain.append(self.eat("NAME").v)
            is_method = True
        params, va, body = self.funcbody(ismethod=is_method)
        # Build assign target: chain
        target = ("NAME_REF", chain[0])
        for c in chain[1:]:
            target = ("FIELD_REF", target, c)
        return ("FNDECL_RAW", target, params, va, body)

    def stmt_local(self):
        self.eat("local")
        if self.match("function"):
            name = self.eat("NAME").v
            params, va, body = self.funcbody(ismethod=False)
            return ("LFNDECL_RAW", name, params, va, body)
        names = [self.eat("NAME").v]
        if self.match(":"): self.skip_type()
        while self.match(","):
            names.append(self.eat("NAME").v)
            if self.match(":"): self.skip_type()
        vals = []
        if self.match("="):
            vals = self.exprlist()
        return ("LDECL_RAW", names, vals)

    def stmt_expr_or_assign(self):
        e = self.suffixed_expr()
        # compound assignment?
        compound = None
        for op in ("+=","-=","*=","/=","//=","%=","^=","..="):
            if self.at(op):
                compound = op[:-1]
                self.p += 1
                break
        if compound is not None:
            rhs = self.expr()
            return ("CASSIGN_RAW", e, compound, rhs)
        if self.at("=") or self.at(","):
            targets = [e]
            while self.match(","):
                targets.append(self.suffixed_expr())
            self.eat("=")
            vals = self.exprlist()
            return ("ASSIGN_RAW", targets, vals)
        # else expression statement; must be call
        if not (isinstance(e, tuple) and e[0] in ("CALL_RAW","MCALL_RAW")):
            raise SyntaxError(f"line {self.peek().line}: syntax error (expected statement)")
        return (ESTMT, e)

    # ---- expressions ----
    # Precedence levels per Lua 5.3 (Luau is similar):
    BIN_PREC = {
        "or":(1,1),
        "and":(2,2),
        "<":(3,3),">":(3,3),"<=":(3,3),">=":(3,3),"~=":(3,3),"==":(3,3),
        "..":(5,4),  # right
        "+":(6,6),"-":(6,6),
        "*":(7,7),"/":(7,7),"//":(7,7),"%":(7,7),
        # unary at 8
        "^":(10,9),  # right
    }
    UNARY_PREC = 8

    def expr(self):
        # `if cond then a else b` expression (LuaU)
        if self.at("if"):
            return self.if_expr()
        return self.binop_expr(0)

    def if_expr(self):
        self.eat("if")
        c = self.expr(); self.eat("then")
        a = self.expr()
        # may have elseif chains
        chain = []
        while self.match("elseif"):
            ec = self.expr(); self.eat("then")
            ea = self.expr()
            chain.append((ec, ea))
        self.eat("else")
        b = self.expr()
        # build nested IfExpr
        for (ec, ea) in reversed(chain):
            b = (IFEXPR, ec, ea, b)
        return (IFEXPR, c, a, b)

    def binop_expr(self, limit):
        # unary
        tk = self.peek()
        if tk.k in ("-","not","#"):
            self.p += 1
            op = tk.k
            r = self.binop_expr(self.UNARY_PREC)
            left = (UNOP, UNOP_MAP[op], r)
        elif tk.k == "if":
            left = self.if_expr()
        else:
            left = self.simple_expr()
        # `::` type casts are postfix on any expression; consume and discard.
        while self.peek().k == "::":
            self.p += 1
            self.skip_type()
        while True:
            tk = self.peek()
            op = tk.k
            if op not in self.BIN_PREC: break
            lp, rp = self.BIN_PREC[op]
            if lp <= limit: break
            self.p += 1
            right = self.binop_expr(rp)
            if op == "and":
                left = (ANDN, left, right)
            elif op == "or":
                left = (ORN, left, right)
            else:
                left = (BINOP, BINOP_MAP[op], left, right)
            # Allow `::` chains after a binop too: `a + b :: number`
            while self.peek().k == "::":
                self.p += 1
                self.skip_type()
        return left

    def simple_expr(self):
        tk = self.peek()
        if tk.k == "NUM":
            self.p += 1; return ("KVAL_RAW", tk.v)
        if tk.k == "STR":
            self.p += 1; return ("KVAL_RAW", tk.v)
        if tk.k == "INTERP":
            self.p += 1
            return self.build_interp(tk.v)
        if tk.k == "nil":
            self.p += 1; return (NIL,)
        if tk.k == "true":
            self.p += 1; return (TRUE,)
        if tk.k == "false":
            self.p += 1; return (FALSE,)
        if tk.k == "...":
            self.p += 1; return (VARARG,)
        if tk.k == "function":
            self.p += 1
            params, va, body = self.funcbody()
            return ("FUNCEXPR_RAW", params, va, body)
        if tk.k == "{":
            return self.table_cons()
        # suffixed
        return self.suffixed_expr()

    def build_interp(self, pieces):
        # pieces: list of ("S", text) and ("E", src, line)
        # produce: tostring(piece1) .. piece2 .. ... using literal strings for S
        parts = []
        for pc in pieces:
            if pc[0] == "S":
                if pc[1] != "":
                    parts.append(("KVAL_RAW", pc[1]))
            else:
                # parse the expression as a fresh sub-parser sharing toks? Simpler: re-lex+parse.
                sub_toks = lex(pc[1])
                sub = Parser(sub_toks)
                e = sub.expr()
                if not sub.at("EOF"):
                    raise SyntaxError("extra tokens in interp expr")
                # wrap in tostring(...)
                e = ("CALL_RAW", ("NAME_REF", "tostring"), [e], False)
                parts.append(e)
        if not parts:
            return ("KVAL_RAW", "")
        # left-associative concat
        cur = parts[0]
        for p in parts[1:]:
            cur = (BINOP, BINOP_MAP[".."], cur, p)
        # ensure result is a string even if single non-string-literal
        if len(parts) == 1 and not (isinstance(parts[0], tuple) and parts[0][0] == "KVAL_RAW" and isinstance(parts[0][1], str)):
            # wrap: "" .. cur
            cur = (BINOP, BINOP_MAP[".."], ("KVAL_RAW",""), cur)
        return cur

    def table_cons(self):
        self.eat("{")
        arr = []
        hsh = []
        while not self.at("}"):
            if self.at("["):
                self.p += 1
                k = self.expr()
                self.eat("]")
                self.eat("=")
                v = self.expr()
                hsh.append((k, v))
            elif self.peek().k == "NAME" and self.t[self.p+1].k == "=":
                name = self.eat("NAME").v
                self.eat("=")
                v = self.expr()
                hsh.append((("KVAL_RAW", name), v))
            else:
                arr.append(self.expr())
            if not (self.match(",") or self.match(";")):
                break
        self.eat("}")
        return ("TABLE_RAW", arr, hsh)

    def suffixed_expr(self):
        # primary
        tk = self.peek()
        if tk.k == "(":
            self.p += 1
            e = self.expr()
            self.eat(")")
            base = ("PAREN_RAW", e)
        elif tk.k == "NAME":
            self.p += 1
            base = ("NAME_REF", tk.v)
        else:
            raise SyntaxError(f"line {tk.line}: unexpected {tk.k}={tk.v!r}")
        while True:
            tk = self.peek()
            if tk.k == ".":
                self.p += 1
                n = self.eat("NAME").v
                base = ("FIELD_REF", base, n)
            elif tk.k == "[":
                self.p += 1
                k = self.expr()
                self.eat("]")
                base = ("INDEX_REF", base, k)
            elif tk.k == ":":
                self.p += 1
                # could be a type annotation in some contexts, but in a suffixed expr
                # at statement/expr level it's a method call OR a cast `::` (handled separately)
                # Here `:` then NAME then ( args ) is method call
                mname = self.eat("NAME").v
                args = self.call_args()
                base = ("MCALL_RAW", base, mname, args[0], args[1])
            elif tk.k == "(" or tk.k == "STR" or tk.k == "INTERP" or tk.k == "{":
                args, ismulti = self.call_args_or_lit()
                base = ("CALL_RAW", base, args, ismulti)
            else:
                break
        return base

    def call_args(self):
        # returns (args_list, last_is_multi_capable_marker_unused)
        tk = self.peek()
        if tk.k == "(":
            self.p += 1
            args = []
            if not self.at(")"):
                args = self.exprlist()
            self.eat(")")
            return (args, True)
        if tk.k == "STR":
            self.p += 1
            return ([("KVAL_RAW", tk.v)], True)
        if tk.k == "INTERP":
            self.p += 1
            return ([self.build_interp(tk.v)], True)
        if tk.k == "{":
            t = self.table_cons()
            return ([t], True)
        raise SyntaxError(f"line {tk.line}: expected call args")

    def call_args_or_lit(self):
        return self.call_args()

    def exprlist(self):
        out = [self.expr()]
        while self.match(","):
            out.append(self.expr())
        return out

# ----------------------------- Resolver ------------------------------------
# Convert "raw" AST to resolved AST with slot/upval/env decisions, and
# desugar compound assigns and function/local-function declarations.

@dataclass(eq=False)
class FuncCtx:
    parent: "FuncCtx|None" = None
    params: list = field(default_factory=list)
    is_vararg: bool = False
    locals_stack: list = field(default_factory=list)  # list of dicts (scopes), name -> slot
    next_slot: int = 1  # 1-based to match Lua arrays in interpreter
    upvals: list = field(default_factory=list)  # list of (fromKind, idx)  fromKind: 0=local,1=upval
    upval_names: list = field(default_factory=list)  # for lookup
    body: Any = None
    def __hash__(self): return id(self)

class Compiler:
    def __init__(self):
        self.K = []                # constant pool values
        self.K_index = {}          # value -> index (1-based)
        self.F = []                # function records
        self.func_counter = 0      # for unique slot creation if needed

    def kindex(self, v):
        # nil and NaN cannot be dict keys directly for NaN; handle by id
        key = (type(v).__name__, v) if not (isinstance(v, float)) else ("float", repr(v))
        if v is None:
            key = ("nil",)
        if key in self.K_index:
            return self.K_index[key]
        self.K.append(v)
        idx = len(self.K)  # 1-based for Lua
        self.K_index[key] = idx
        return idx

    # --- scope helpers ---
    def push_scope(self, fc): fc.locals_stack.append({})
    def pop_scope(self, fc): fc.locals_stack.pop()
    def declare(self, fc, name):
        slot = fc.next_slot
        fc.next_slot += 1
        fc.locals_stack[-1][name] = slot
        return slot
    def find_local(self, fc, name):
        for sc in reversed(fc.locals_stack):
            if name in sc: return sc[name]
        return None
    def resolve_upval(self, fc, name):
        # check existing upvals
        for i, un in enumerate(fc.upval_names):
            if un == name: return i + 1  # 1-based
        if fc.parent is None: return None
        # parent local?
        slot = self.find_local(fc.parent, name)
        if slot is not None:
            fc.upvals.append((0, slot))
            fc.upval_names.append(name)
            return len(fc.upvals)
        # parent upval?
        u = self.resolve_upval(fc.parent, name)
        if u is not None:
            fc.upvals.append((1, u))
            fc.upval_names.append(name)
            return len(fc.upvals)
        return None

    def resolve_name(self, fc, name):
        s = self.find_local(fc, name)
        if s is not None: return (LOCAL, s)
        u = self.resolve_upval(fc, name)
        if u is not None: return (UPVAL, u)
        return (ENV, self.kindex(name))

    # --- compile ---
    def compile_chunk(self, raw_block):
        # main function: no params, vararg=true
        fc = FuncCtx(parent=None, params=[], is_vararg=True)
        self.push_scope(fc)
        body = self.compile_block(fc, raw_block)
        self.pop_scope(fc)
        fc.body = body
        # main is function index 1 (1-based)
        self.F.insert(0, fc)
        return fc

    def compile_block(self, fc, raw):
        assert raw[0] == BLOCK
        self.push_scope(fc)
        out = []   # nodes
        lns = []   # parallel line numbers
        for (ln, s) in raw[1]:
            n = self.compile_stmt(fc, s)
            if n is not None:
                if isinstance(n, list):
                    for nn in n: out.append(nn); lns.append(ln)
                else:
                    out.append(n); lns.append(ln)
        self.pop_scope(fc)
        return (BLOCK, out, lns)

    def compile_stmt(self, fc, s):
        tag = s[0]
        if tag == "ASSIGN_RAW":
            _, targets, vals = s
            tgts = [self.compile_lvalue(fc, t) for t in targets]
            vs = [self.compile_expr(fc, v) for v in vals]
            return (ASSIGN, tgts, vs)
        if tag == "CASSIGN_RAW":
            _, lhs, op, rhs = s
            # Desugar to single-eval form when lhs is indexed
            if lhs[0] in ("FIELD_REF","INDEX_REF"):
                # local _o = obj; local _k = key; _o[_k] = _o[_k] OP rhs
                # We synthesize hidden locals in the current scope.
                # Allocate synthetic names.
                sname_o = f"$o{self.func_counter}"; self.func_counter += 1
                sname_k = f"$k{self.func_counter}"; self.func_counter += 1
                obj_expr = lhs[1]
                key_expr = lhs[2] if lhs[0] == "INDEX_REF" else ("KVAL_RAW", lhs[2])
                # declare locals
                slot_o = self.declare(fc, sname_o)
                slot_k = self.declare(fc, sname_k)
                obj_c = self.compile_expr(fc, obj_expr)
                key_c = self.compile_expr(fc, key_expr)
                # LocalDecl two locals (use single LDECL for grouping)
                decl = (LDECL, [slot_o, slot_k], [obj_c, key_c])
                # read = _o[_k]
                read = (INDEX, (LOCAL, slot_o), (LOCAL, slot_k))
                rhs_c = self.compile_expr(fc, rhs)
                if op == "..":
                    newv = (BINOP, BINOP_MAP[".."], read, rhs_c)
                else:
                    newv = (BINOP, BINOP_MAP[op], read, rhs_c)
                tgt = (INDEX, (LOCAL, slot_o), (LOCAL, slot_k))
                return [decl, (ASSIGN, [tgt], [newv])]
            else:
                # NAME_REF or PAREN_REF — simple double-eval is fine because side-effect-free
                lhs_c = self.compile_lvalue(fc, lhs)
                rhs_c = self.compile_expr(fc, rhs)
                # read-side: resolve name as expression
                if lhs[0] == "NAME_REF":
                    rd = self.compile_expr(fc, lhs)
                else:
                    raise SyntaxError("invalid compound assignment lhs")
                if op == "..":
                    newv = (BINOP, BINOP_MAP[".."], rd, rhs_c)
                else:
                    newv = (BINOP, BINOP_MAP[op], rd, rhs_c)
                return (ASSIGN, [lhs_c], [newv])
        if tag == "LDECL_RAW":
            _, names, vals = s
            # Declare slots AFTER evaluating RHS (so `local x = x` reads outer x)
            vs = [self.compile_expr(fc, v) for v in vals]
            slots = [self.declare(fc, n) for n in names]
            return (LDECL, slots, vs)
        if tag == "LFNDECL_RAW":
            _, name, params, va, body = s
            slot = self.declare(fc, name)  # declare first to allow recursion
            # local f = nil  (creates the boxed cell so the closure can capture it)
            decl = (LDECL, [slot], [(NIL,)])
            fexpr = self.compile_funcexpr(fc, params, va, body)
            assign = (ASSIGN, [(LOCAL, slot)], [fexpr])
            return [decl, assign]
        if tag == "FNDECL_RAW":
            _, target, params, va, body = s
            # Method? handled at parse-time by prepending 'self'.
            fexpr = self.compile_funcexpr(fc, params, va, body)
            tgt = self.compile_lvalue(fc, target)
            return (ASSIGN, [tgt], [fexpr])
        if tag == IFN:
            _, c, th, elifs, el = s
            cc = self.compile_expr(fc, c)
            tc = self.compile_block(fc, th)
            ec = [(self.compile_expr(fc, a), self.compile_block(fc, b)) for (a,b) in elifs]
            elc = self.compile_block(fc, el) if el is not None else None
            return (IFN, cc, tc, ec, elc)
        if tag == WHILEN:
            _, c, b = s
            return (WHILEN, self.compile_expr(fc, c), self.compile_block(fc, b))
        if tag == REPEATN:
            _, b, c = s
            # condition must see body locals; we open a scope manually
            self.push_scope(fc)
            stmts = []; lns = []
            for (ln, st) in b[1]:
                n = self.compile_stmt(fc, st)
                if n is not None:
                    if isinstance(n, list):
                        for nn in n: stmts.append(nn); lns.append(ln)
                    else:
                        stmts.append(n); lns.append(ln)
            body_node = (BLOCK, stmts, lns)
            cond_node = self.compile_expr(fc, c)
            self.pop_scope(fc)
            return (REPEATN, body_node, cond_node)
        if tag == DON:
            _, b = s
            return (DON, self.compile_block(fc, b))
        if tag == "NFOR_RAW":
            _, name, a, bv, cv, body = s
            ac = self.compile_expr(fc, a)
            bc = self.compile_expr(fc, bv)
            cc = self.compile_expr(fc, cv) if cv is not None else None
            self.push_scope(fc)
            slot = self.declare(fc, name)
            body_c = self.compile_block_inplace(fc, body)
            self.pop_scope(fc)
            return (NFOR, slot, ac, bc, cc, body_c)
        if tag == "GFOR_RAW":
            _, names, exprs, body = s
            es = [self.compile_expr(fc, e) for e in exprs]
            self.push_scope(fc)
            slots = [self.declare(fc, n) for n in names]
            body_c = self.compile_block_inplace(fc, body)
            self.pop_scope(fc)
            return (GFOR, slots, es, body_c)
        if tag == RET:
            _, vals = s
            vs = [self.compile_expr(fc, v) for v in vals]
            return (RET, vs)
        if tag == BRK: return (BRK,)
        if tag == CONT: return (CONT,)
        if tag == ESTMT:
            _, e = s
            ce = self.compile_expr(fc, e)
            # force multret=0 for statement-level calls (efficiency, not correctness)
            if isinstance(ce, tuple) and ce[0] == CALL:
                ce = (CALL, ce[1], ce[2], 0)
            elif isinstance(ce, tuple) and ce[0] == MCALL:
                ce = (MCALL, ce[1], ce[2], ce[3], 0)
            return (ESTMT, ce)
        raise SyntaxError(f"unknown stmt {tag}")

    def compile_block_inplace(self, fc, raw):
        # Like compile_block but does not push another scope (caller manages).
        assert raw[0] == BLOCK
        out = []; lns = []
        for (ln, s) in raw[1]:
            n = self.compile_stmt(fc, s)
            if n is not None:
                if isinstance(n, list):
                    for nn in n: out.append(nn); lns.append(ln)
                else:
                    out.append(n); lns.append(ln)
        return (BLOCK, out, lns)

    def compile_lvalue(self, fc, t):
        tag = t[0]
        if tag == "NAME_REF":
            k = self.resolve_name(fc, t[1])
            if k[0] == LOCAL: return (LOCAL, k[1])
            if k[0] == UPVAL: return (UPVAL, k[1])
            return (ENV, k[1])
        if tag == "FIELD_REF":
            return (INDEX, self.compile_expr(fc, t[1]), (KCONST, self.kindex(t[2])))
        if tag == "INDEX_REF":
            return (INDEX, self.compile_expr(fc, t[1]), self.compile_expr(fc, t[2]))
        if tag == "PAREN_RAW":
            # (e) = ... is invalid
            raise SyntaxError("cannot assign to parenthesized expression")
        raise SyntaxError(f"invalid lvalue {tag}")

    def compile_expr(self, fc, e):
        tag = e[0]
        if tag == "KVAL_RAW":
            v = e[1]
            return (KCONST, self.kindex(v))
        if tag in (NIL, TRUE, FALSE, VARARG):
            return (tag,)
        if tag == "NAME_REF":
            k = self.resolve_name(fc, e[1])
            return k  # (LOCAL, slot) etc.
        if tag == "FIELD_REF":
            return (INDEX, self.compile_expr(fc, e[1]), (KCONST, self.kindex(e[2])))
        if tag == "INDEX_REF":
            return (INDEX, self.compile_expr(fc, e[1]), self.compile_expr(fc, e[2]))
        if tag == "PAREN_RAW":
            # Parens truncate multi-return to single. Easiest: compile inner; the call site
            # decides single vs many. If inner is a Call/MCall/Vararg the parens force single.
            inner = self.compile_expr(fc, e[1])
            if isinstance(inner, tuple) and inner[0] in (CALL, MCALL):
                # force multret = 0
                if inner[0] == CALL:
                    return (CALL, inner[1], inner[2], 0)
                else:
                    return (MCALL, inner[1], inner[2], inner[3], 0)
            if isinstance(inner, tuple) and inner[0] == VARARG:
                # ... in parens -> truncate to one; we can model by indexing a temp,
                # but the interpreter naturally truncates when used in a single-value context.
                # Force single by wrapping: (select(1, ...)) is complex. Simpler hack:
                # leave as VARARG; one() returns first vararg, so single-value contexts are fine.
                # For multi-value contexts (e.g. as last arg of a call), we want truncation.
                # We'll wrap with a synthetic call: (function(x) return x end)(...)
                return inner  # Note: imperfect; parens semantics on vararg are an edge case.
            return inner
        if tag == "CALL_RAW":
            _, callee, args, _ = e
            ccallee = self.compile_expr(fc, callee)
            cargs = [self.compile_expr(fc, a) for a in args]
            return (CALL, ccallee, cargs, 1)  # multret=1; caller may force 0
        if tag == "MCALL_RAW":
            _, base, name, args, _ = e
            cb = self.compile_expr(fc, base)
            ki = self.kindex(name)
            cargs = [self.compile_expr(fc, a) for a in args]
            return (MCALL, cb, ki, cargs, 1)
        if tag == "FUNCEXPR_RAW":
            _, params, va, body = e
            return self.compile_funcexpr(fc, params, va, body)
        if tag == "TABLE_RAW":
            _, arr, hsh = e
            ca = [self.compile_expr(fc, a) for a in arr]
            ch = [(self.compile_expr(fc, k), self.compile_expr(fc, v)) for (k,v) in hsh]
            return (TABLE, ca, ch)
        if tag == BINOP:
            _, op, a, b = e
            return (BINOP, op, self.compile_expr(fc, a), self.compile_expr(fc, b))
        if tag == UNOP:
            _, op, a = e
            return (UNOP, op, self.compile_expr(fc, a))
        if tag == ANDN:
            _, a, b = e
            return (ANDN, self.compile_expr(fc, a), self.compile_expr(fc, b))
        if tag == ORN:
            _, a, b = e
            return (ORN, self.compile_expr(fc, a), self.compile_expr(fc, b))
        if tag == IFEXPR:
            _, c, a, b = e
            return (IFEXPR, self.compile_expr(fc, c), self.compile_expr(fc, a), self.compile_expr(fc, b))
        raise SyntaxError(f"unknown expr {tag}")

    def compile_funcexpr(self, fc, params, va, body):
        sub = FuncCtx(parent=fc, params=list(params), is_vararg=va)
        self.push_scope(sub)
        for p in params:
            self.declare(sub, p)
        sub.body = self.compile_block_inplace(sub, body)
        self.pop_scope(sub)
        self.F.append(sub)
        idx = len(self.F)  # 1-based; but main is at index 1 (we insert main at the front later).
        # We will reindex at emit time.
        return (FUNC, sub)  # store the FuncCtx; we'll resolve to its index when emitting.

    # ---------- emit ----------
    def emit(self):
        # Reindex F to 1-based with main first.
        # Note: in compile_chunk we insert main at index 0. Other functions appended in self.F in creation order.
        # Build mapping from FuncCtx object -> 1-based index.
        idx_of = {f: i+1 for i, f in enumerate(self.F)}
        out = bytearray()

        def emit_varint(v):
            assert v >= 0
            while True:
                b = v & 0x7f
                v >>= 7
                if v:
                    out.append(b | 0x80)
                else:
                    out.append(b); return

        def emit_zigzag(v):
            z = (v << 1) ^ (v >> 63) if v < 0 else (v << 1)
            emit_varint(z & ((1<<64)-1))

        def emit_node(n):
            t = n[0]
            out.append(t)
            if t in (NIL, TRUE, FALSE, VARARG, BRK, CONT):
                return
            if t == KCONST:
                emit_varint(n[1]); return
            if t == LOCAL or t == UPVAL or t == ENV:
                emit_varint(n[1]); return
            if t == INDEX:
                emit_node(n[1]); emit_node(n[2]); return
            if t == CALL:
                emit_node(n[1])
                emit_varint(len(n[2]))
                for a in n[2]: emit_node(a)
                out.append(n[3])  # multret flag
                return
            if t == MCALL:
                emit_node(n[1])
                emit_varint(n[2])
                emit_varint(len(n[3]))
                for a in n[3]: emit_node(a)
                out.append(n[4])
                return
            if t == FUNC:
                emit_varint(idx_of[n[1]])
                return
            if t == TABLE:
                emit_varint(len(n[1])); emit_varint(len(n[2]))
                for a in n[1]: emit_node(a)
                for (k, v) in n[2]:
                    emit_node(k); emit_node(v)
                return
            if t == BINOP:
                out.append(n[1]); emit_node(n[2]); emit_node(n[3]); return
            if t == UNOP:
                out.append(n[1]); emit_node(n[2]); return
            if t == ANDN or t == ORN:
                emit_node(n[1]); emit_node(n[2]); return
            if t == IFEXPR:
                emit_node(n[1]); emit_node(n[2]); emit_node(n[3]); return
            if t == ASSIGN:
                emit_varint(len(n[1]))
                for l in n[1]: emit_node(l)
                emit_varint(len(n[2]))
                for v in n[2]: emit_node(v)
                return
            if t == LDECL:
                emit_varint(len(n[1]))
                for s in n[1]: emit_varint(s)
                emit_varint(len(n[2]))
                for v in n[2]: emit_node(v)
                return
            if t == IFN:
                emit_node(n[1])  # cond
                emit_node(n[2])  # then block
                emit_varint(len(n[3]))
                for (c, b) in n[3]:
                    emit_node(c); emit_node(b)
                if n[4] is not None:
                    out.append(1); emit_node(n[4])
                else:
                    out.append(0)
                return
            if t == WHILEN:
                emit_node(n[1]); emit_node(n[2]); return
            if t == REPEATN:
                emit_node(n[1]); emit_node(n[2]); return
            if t == NFOR:
                emit_varint(n[1])
                emit_node(n[2]); emit_node(n[3])
                if n[4] is not None:
                    out.append(1); emit_node(n[4])
                else:
                    out.append(0)
                emit_node(n[5])
                return
            if t == GFOR:
                emit_varint(len(n[1]))
                for s in n[1]: emit_varint(s)
                emit_varint(len(n[2]))
                for v in n[2]: emit_node(v)
                emit_node(n[3])
                return
            if t == RET:
                emit_varint(len(n[1]))
                for v in n[1]: emit_node(v)
                return
            if t == DON or t == ESTMT:
                emit_node(n[1]); return
            if t == BLOCK:
                ss, lns = n[1], n[2]
                emit_varint(len(ss))
                for i in range(len(ss)):
                    emit_varint(max(0, lns[i]))
                    emit_node(ss[i])
                return
            raise RuntimeError(f"emit: unknown tag {t}")

        # Constants
        emit_varint(len(self.K))
        for v in self.K:
            if v is None:
                out.append(0)
            elif v is False:
                out.append(1)
            elif v is True:
                out.append(2)
            elif isinstance(v, bool):
                out.append(2 if v else 1)
            elif isinstance(v, int):
                out.append(3); emit_zigzag(v)
            elif isinstance(v, float):
                out.append(4); out += struct.pack("<d", v)
            elif isinstance(v, str):
                # Use latin-1 to preserve raw byte content (Lua strings are
                # byte sequences, not unicode).
                bs = v.encode("latin-1", errors="replace")
                out.append(5); emit_varint(len(bs)); out += bs
            else:
                raise RuntimeError(f"bad const {v!r}")

        # Functions
        emit_varint(len(self.F))
        for fc in self.F:
            out.append(len(fc.params))
            out.append(1 if fc.is_vararg else 0)
            emit_varint(len(fc.upvals))
            for (kind, idx) in fc.upvals:
                out.append(kind); emit_varint(idx)
            emit_node(fc.body)

        return bytes(out)

def compile_source(src: str) -> bytes:
    toks = lex(src)
    parser = Parser(toks)
    raw = parser.parse_chunk()
    c = Compiler()
    c.compile_chunk(raw)
    return c.emit()

def _hex_literal(data: bytes) -> str:
    return "".join(f"\\x{b:02x}" for b in data)

def emit_test_program(data: bytes, chunkname: str, run_module: str) -> str:
    """Produce a Luau test program that `require`s the interpreter module and
    runs the embedded bytecode against a permissive environment that mirrors
    `_G` (with a writable `_G` shadow).

    The generated file is a drop-in test harness:
        luau out.luau

    `run_module` is the Lua module path / string passed to `require(...)`.
    The default points at this repo's `run.luau` relative to the project root
    so `luau` invoked from the workspace root can resolve it. Override with
    `--run-module` to fit your host's require resolution (Roblox path, lune
    alias, etc.).
    """
    hex_lit = _hex_literal(data)
    # Escape the module string for embedding in double-quoted Lua literal.
    mod_lit = run_module.replace("\\", "\\\\").replace('"', '\\"')
    return f"""--!nocheck
-- Auto-generated test harness for the embedded interpreter.
-- Loads the interpreter module via require(...) and runs the embedded asset.

local run = require("{mod_lit}")

local _data = "{hex_lit}"

-- Build a writable environment that mirrors _G for reads, with a writable _G
-- shadow so interpreted code can assign globals without hitting a readonly _G.
local env = setmetatable({{}}, {{ __index = _G }})
env._G = env

local ok, err = pcall(function() return run(_data, env, "{chunkname}") end)
if ok then
    print("OK")
else
    print("ERR: " .. tostring(err))
    error(err, 0)
end
"""

def main():
    import argparse
    ap = argparse.ArgumentParser(prog="compiler.py")
    ap.add_argument("input", help="input .luau source file")
    ap.add_argument("output", help="output file (.bin by default; .luau if --test-program)")
    ap.add_argument("--test-program", action="store_true",
                    help="emit a standalone Luau test program that imports the "
                         "interpreter module and runs the compiled asset, instead of a raw .bin")
    ap.add_argument("--run-module", default=None,
                    help="module string passed to require() in the generated "
                         "test program. If omitted, computed as a relative "
                         "path from the output file to run.luau (Luau's "
                         "require requires a './', '../' or '@' prefix).")
    ap.add_argument("--chunkname", default=None,
                    help="chunkname passed to the interpreter (default: input basename)")
    args = ap.parse_args()

    # Lua source files can contain arbitrary byte sequences inside string
    # literals; treat the file as latin-1 so every byte maps to one codepoint.
    src = open(args.input, "r", encoding="latin-1").read()
    data = compile_source(src)

    if args.test_program:
        chunkname = args.chunkname or os.path.basename(args.input)
        run_module = args.run_module
        if run_module is None:
            # Default: compute a relative path from the output's directory to
            # the canonical interpreter module next to compiler.py. We prefer
            # run-final.luau (stealth-hardened) if present, falling back to
            # run.luau. Luau requires a './' or '../' prefix.
            here = os.path.dirname(os.path.abspath(__file__))
            candidate = os.path.join(here, "run-final.luau")
            if not os.path.exists(candidate):
                candidate = os.path.join(here, "run.luau")
            out_dir = os.path.dirname(os.path.abspath(args.output))
            rel = os.path.relpath(candidate, out_dir).replace("\\", "/")
            # Strip the .luau extension; require() typically wants the bare name.
            if rel.endswith(".luau"):
                rel = rel[:-len(".luau")]
            elif rel.endswith(".lua"):
                rel = rel[:-len(".lua")]
            # Ensure it starts with ./ or ../ as Luau's require requires.
            if not (rel.startswith("./") or rel.startswith("../")):
                rel = "./" + rel
            run_module = rel
        prog = emit_test_program(data, chunkname, run_module)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(prog)
        print(f"wrote test program: {args.output} ({len(data)} bytes of bytecode embedded)")
    else:
        with open(args.output, "wb") as f:
            f.write(data)
        print(f"wrote {len(data)} bytes")

if __name__ == "__main__":
    main()

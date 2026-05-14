--!nocheck
-- Split-deploy launcher for tinyvm.
--
-- This is what you write yourself when you want to ship the micro-VM
-- source separately from the macro-VM AST and the user program. It
-- loads three Luau modules:
--
--   1. ./tinyvm        -- the micro-VM (a function)
--   2. ./macrovm-ast   -- the pre-decoded macro-VM AST  (returns {K, F})
--   3. ./user-ast      -- the pre-decoded user program  (returns {K, F})
--
-- combines (2) and (3) into the `inputData` table the micro-VM expects,
-- and hands it a plain user env.
--
-- In a real Roblox project the three modules would live anywhere -- in
-- this example they're laid out flat next to this file so plain
-- `require("./...")` works.
local micro   = require("./tinyvm")
local mvmAst  = require("./macrovm-ast")  -- returns {K, F}
local userAst = require("./user-ast")     -- returns {K, F}

-- The inputData payload. `D.m` is the macro-VM AST, `D.u` the user one.
local inputData = {m = mvmAst, u = userAst}

-- ---------------------------------------------------------------------------
-- Build the env the user program sees as its globals. A writable shadow
-- of _G is usually what you want: the user can read everything stdlib
-- gives them, and writes don't leak into the host's _G.
--
-- The micro-VM doesn't need a separate "shadow env" -- BinOp/UnOp atoms
-- are handled natively by the micro-VM, so the macro-VM resolves its
-- own globals (string, table, error, ...) directly through this env.
-- ---------------------------------------------------------------------------
local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv

-- Anything you stick on `userEnv` is visible to the user program as a
-- global. Anything you *don't* add and that's not on `_G` is invisible.
userEnv.hostInfo = {
    appName    = "tinyvm-split-deploy-example",
    appVersion = "1.0",
}

-- ---------------------------------------------------------------------------
-- Run the user program.
--
-- Signature: micro(inputData, userEnv, label)
--   inputData  - {m = macro-VM AST, u = user program AST}
--   userEnv    - what the user program sees as its _G
--   label      - chunk name shown in diagnostic messages
-- ---------------------------------------------------------------------------
print("== launcher: starting user program ==")
local ok, err = pcall(micro, inputData, userEnv, "user.luau")
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
